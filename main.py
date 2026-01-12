# ==============================================================================
# VAVOO PROXY - HYDRA EDITION (IDM STYLE)
# Tech: Multi-Source Swarm | Range Request Splitting | Parallel Reassembly
# Logic: 4 Sources x 1 File = Max Speed
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
from gevent import pool, event, spawn, sleep, lock, joinall
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ------------------------------------------------------------------------------
# 1. AYARLAR
# ------------------------------------------------------------------------------
gc.set_threshold(70000, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

B_NEWLINE = b"\n"
B_EXTM3U = b"#EXTM3U"
MIN_VALID_SIZE = 1024

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK KATMANI
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=1000,
    pool_maxsize=10000,
    max_retries=0,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

HEADERS_MEM = {}
def get_headers(base_url):
    if base_url not in HEADERS_MEM:
        HEADERS_MEM[base_url] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{base_url}/",
            "Origin": base_url,
            "Connection": "keep-alive"
        }
    return HEADERS_MEM[base_url]

# ------------------------------------------------------------------------------
# 3. HYDRA BRAIN (ÇOKLU KAYNAK YÖNETİCİSİ)
# ------------------------------------------------------------------------------
class HydraBrain:
    def __init__(self):
        # Cache artık tek bir URL değil, kaynak listesi tutar
        # {cid: [{'source': 'huhu', 'url': '...', 'headers': ...}, ...]}
        self.swarm_cache = {} 
        self.lock = lock.RLock()
        
    def _worker(self, source, cid, result_list):
        """Kaynağı kontrol eder ve listeye ekler"""
        try:
            url = f"{source}/play/{cid}/index.m3u8"
            h = get_headers(source)
            with session.get(url, headers=h, verify=False, timeout=2.5) as r:
                if r.status_code == 200:
                    # Base URL hesapla
                    base = r.url.rsplit('/', 1)[0]
                    content = r.content
                    
                    result_list.append({
                        'source': source,
                        'url': r.url,
                        'base': base,
                        'headers': h,
                        'content': content
                    })
        except: pass

    def get_swarm(self, cid):
        """Bir kanal için çalışan TÜM kaynakları bulur."""
        now = time.time()
        
        # Cache kontrolü
        if cid in self.swarm_cache:
            entry = self.swarm_cache[cid]
            if now < entry['expires']: return entry['nodes']

        # Tüm kaynakları tara
        valid_nodes = []
        jobs = []
        p = pool.Pool(len(SOURCES))
        
        for src in SOURCES:
            jobs.append(p.spawn(self._worker, src, cid, valid_nodes))
        
        joinall(jobs, timeout=3.0) # Hepsini bekle
        
        if valid_nodes:
            self.swarm_cache[cid] = {
                'expires': now + 300, # 5 dakika geçerli
                'nodes': valid_nodes
            }
            return valid_nodes
        return None

brain = HydraBrain()

# ------------------------------------------------------------------------------
# 4. IDM ENGINE (PARÇALI İNDİRİCİ)
# ------------------------------------------------------------------------------
def download_chunk(url, headers, start_byte, end_byte, chunk_index, results):
    """Belirli bir byte aralığını indirir."""
    try:
        # Range Header'ı ekle: "bytes=0-1024"
        req_headers = headers.copy()
        req_headers['Range'] = f"bytes={start_byte}-{end_byte}"
        
        with session.get(url, headers=req_headers, verify=False, timeout=5) as r:
            if r.status_code in [200, 206]: # 206 Partial Content
                results[chunk_index] = r.content
            else:
                results[chunk_index] = None # Fail
    except:
        results[chunk_index] = None

def fetch_file_hydra_style(target_path, nodes):
    """
    IDM MANTIĞI:
    Dosyayı node sayısı kadar parçaya böl ve paralel indir.
    """
    if not nodes: return None

    # 1. Dosya boyutunu öğren (HEAD isteği)
    file_size = 0
    leader = nodes[0]
    # URL'i oluştur
    # Target path sadece dosya ismiyse (seg-1.ts) base ile birleştir
    full_url = f"{leader['base']}/{target_path}"
    
    try:
        h = leader['headers']
        with session.head(full_url, headers=h, verify=False, timeout=2) as r:
            if 'Content-Length' in r.headers:
                file_size = int(r.headers['Content-Length'])
    except: pass
    
    # Eğer boyut alamazsak veya dosya çok küçükse (1MB altı),
    # bölmekle uğraşma, direkt indir (Overhead zararı olmasın)
    if file_size < 1000000:
        try:
            with session.get(full_url, headers=h, verify=False, timeout=5) as r:
                return r.content
        except: return None

    # 2. Parçalara Böl (Math)
    part_count = len(nodes)
    chunk_size = file_size // part_count
    
    # Sonuçları tutacak liste [Part1, Part2, Part3, Part4]
    results = [None] * part_count
    download_jobs = []
    p = pool.Pool(part_count)

    for i in range(part_count):
        start = i * chunk_size
        # Son parçaysa dosyanın sonuna kadar git
        end = file_size if i == part_count - 1 else (start + chunk_size - 1)
        
        node = nodes[i]
        node_url = f"{node['base']}/{target_path}"
        
        download_jobs.append(p.spawn(
            download_chunk, 
            node_url, 
            node['headers'], 
            start, 
            end, 
            i, 
            results
        ))
    
    # Hepsini bekle
    joinall(download_jobs, timeout=6)

    # 3. Birleştirme (Stitching)
    final_data = bytearray()
    for i, data in enumerate(results):
        if data:
            final_data.extend(data)
        else:
            # KRİTİK HATA: Bir parça eksik!
            # IDM mantığında dosya bozuk demektir.
            # Kurtarma planı: Tam dosya isteği at (Fallback)
            try:
                with session.get(full_url, headers=leader['headers'], verify=False, timeout=5) as r:
                    return r.content
            except: return None
            
    return bytes(final_data)

# ------------------------------------------------------------------------------
# 5. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # Kanal listesi için tek kaynak yeterli
    # Ama biz en hızlısını bulalım
    data = None
    for src in SOURCES:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=2)
            if r.status_code == 200:
                data = r.json()
                break
        except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [B_EXTM3U]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # Parsing
                part = u.split('/play/')[-1]
                if '/' in part: cid = part.split('/')[0]
                else: cid = part.replace('.m3u8', '')
                if '.' in cid: cid = cid.split('.')[0]
                
                if cid:
                    name = item['name'].replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    clean_cid = cid.replace('.m3u8', '')
    
    # Swarm (Sürü) Bilgisini al
    nodes = brain.get_swarm(clean_cid)
    
    if not nodes: return Response("Not Found", 404)

    # Playlisti oluşturmak için herhangi bir node'un içeriğini kullanabiliriz
    # Genelde hepsi aynıdır.
    template_node = nodes[0]
    
    base_b = template_node['base'].encode() # Bu base artık kullanılmayacak ama referans
    host_b = request.host_url.rstrip('/').encode()
    cid_b = clean_cid.encode()
    
    out = [B_EXTM3U, b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    for line in template_node['content'].split(B_NEWLINE):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(B_EXTM3U) and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            # TS dosya ismi (örn: seg-12.ts)
            # URL'e tam yol koymuyoruz, sadece dosya ismini koyuyoruz
            # Çünkü /ts endpoint'i Swarm mantığıyla tekrar base bulacak.
            if line.startswith(b'http'):
                # Full link gelirse dosya adını ayıkla
                ts_name = line.decode().split('/')[-1]
            else:
                ts_name = line.decode()
                
            safe_target = quote(ts_name).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&file=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    # Artık 'url' yerine 'file' (dosya ismi) ve 'cid' alıyoruz
    file_name = unquote(request.args.get('file', ''))
    cid = request.args.get('cid')
    
    if not file_name or not cid: return "Bad", 400
    
    # Swarm'ı çağır
    nodes = brain.get_swarm(cid)
    if not nodes: return "Source Dead", 404

    # HYDRA DOWNLOAD (IDM MODE)
    # Tüm kaynaklardan parçalı indir ve birleştir
    data = fetch_file_hydra_style(file_name, nodes)
    
    if data:
        # Flask stream yerine direkt veri dönüyoruz çünkü birleştirme RAM'de bitti
        return Response(data, content_type="video/mp2t")
    else:
        # Hata durumunda Fallback: Tekrar Swarm yenile ve dene
        if cid in brain.swarm_cache: del brain.swarm_cache[cid]
        nodes = brain.get_swarm(cid)
        if nodes:
            data = fetch_file_hydra_style(file_name, nodes)
            if data: return Response(data, content_type="video/mp2t")
            
    return Response(status=500)

if __name__ == "__main__":
    print(f" ► VAVOO HYDRA (IDM EDITION)")
    print(f" ► LOGIC: SPLIT & DOWNLOAD (4x Speed)")
    print(f" ► LISTENING: 8080")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
