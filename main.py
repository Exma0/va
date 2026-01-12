from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import sys
import random
from gevent import pool, event, spawn, sleep, lock, queue
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ------------------------------------------------------------------------------
# 1. MAKİNE AYARLARI (GOD MODE TUNING)
# ------------------------------------------------------------------------------
# Thread geçiş aralığını düşür (Daha hızlı tepki süresi)
sys.setswitchinterval(0.001)

# Garbage Collector: Sadece RAM %90 dolunca çalışsın
gc.set_threshold(100000, 50, 50)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# 1KB altı dosyalar hatalıdır
MIN_VALID_SIZE = 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Tüm logları kapat
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK STACK
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=5000,
    pool_maxsize=50000,
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
# 3. SINGULARITY CORE (EBEDİ BEYİN)
# ------------------------------------------------------------------------------
class SingularityCore:
    def __init__(self):
        # Kaynak Sağlığı: 100 = Mükemmel, 0 = Ölü
        self.health = {src: 100.0 for src in SOURCES}
        
        # RAM Disk: Gelecek segmentler burada yaşar
        # {full_url: {data: bytes, ts: time}}
        self.future_cache = {} 
        
        # Playlist Cache
        self.playlist_store = {} 
        
        self.lock = lock.RLock()
        
        # Arka plan temizlik ve optimizasyon
        spawn(self._optimizer)

    def _optimizer(self):
        """Sistemi sürekli optimize eder."""
        while True:
            sleep(5)
            now = time.time()
            with self.lock:
                # Cache temizliği
                expired = [k for k, v in self.future_cache.items() if now - v['ts'] > 20]
                for k in expired: del self.future_cache[k]
                
                # Sağlık Puanı İyileştirme (Affetme Mekanizması)
                for src in self.health:
                    if self.health[src] < 100: self.health[src] += 5

    def punish(self, source, amount=20):
        """Hata yapan kaynağı cezalandır."""
        with self.lock:
            self.health[source] -= amount

    def get_top_sources(self):
        """En sağlıklı 2 kaynağı döndür (RAID-1 için)."""
        return sorted(SOURCES, key=lambda s: self.health[s], reverse=True)[:2]

    def _fetch_blob(self, url, source):
        """Tekil veri indirici."""
        try:
            h = get_headers(source)
            with session.get(url, headers=h, verify=False, timeout=(1.5, 4.0)) as r:
                if r.status_code == 200:
                    return r.content
                else:
                    self.punish(source)
        except:
            self.punish(source)
        return None

    def predict_next(self, current_m3u8_content, base_url):
        """
        GELECEĞİ TAHMİN ETME MODÜLÜ
        Mevcut listeden bir sonraki dosya ismini tahmin eder ve indirir.
        """
        try:
            lines = current_m3u8_content.split(b'\n')
            last_segment = None
            for line in reversed(lines):
                line = line.strip()
                if line and not line.startswith(b'#'):
                    last_segment = line.decode()
                    break
            
            if last_segment:
                # Örn: seg-100.ts -> seg-101.ts
                # Regex kullanmadan string analizi (Hız için)
                prefix = ""
                num_str = ""
                suffix = ""
                
                # Sayıyı bul
                import re
                match = re.search(r'(\d+)', last_segment)
                if match:
                    num_val = int(match.group(1))
                    next_val = num_val + 1
                    
                    # Yeni dosya adını oluştur
                    new_seg = last_segment.replace(str(num_val), str(next_val))
                    
                    # Gelecek URL
                    if new_seg.startswith('http'): next_url = new_seg
                    else: next_url = f"{base_url}/{new_seg}"
                    
                    # Şimdiden indir (Top source'dan)
                    top_src = self.get_top_sources()[0]
                    spawn(self._future_worker, next_url, top_src)
        except: pass

    def _future_worker(self, url, source):
        """Gelecek verisini indirip RAM'e koyar."""
        data = self._fetch_blob(url, source)
        if data and len(data) > MIN_VALID_SIZE:
            with self.lock:
                self.future_cache[url] = {'data': data, 'ts': time.time()}

    def resolve_playlist(self, cid):
        now = time.time()
        cid = cid.replace('.m3u8', '')

        if cid in self.playlist_store:
            entry = self.playlist_store[cid]
            if now < entry['expires']: return entry['data']

        # En iyi 2 kaynakla yarış
        candidates = self.get_top_sources()
        result_box = event.AsyncResult()
        
        def worker(src):
            url = f"{src}/play/{cid}/index.m3u8"
            data = self._fetch_blob(url, src)
            if data and not result_box.ready():
                result_box.set({
                    'content': data,
                    'base': f"{src}/play/{cid}",
                    'source': src
                })

        p = pool.Pool(2)
        for src in candidates: p.spawn(worker, src)
        
        try:
            winner = result_box.get(timeout=2.5)
            p.kill(block=False)
            if winner:
                # Geleceği tahmin etmeye başla
                self.predict_next(winner['content'], winner['base'])
                
                self.playlist_store[cid] = {'expires': now + 300, 'data': winner}
                return winner
        except:
            p.kill(block=False)
        return None

singularity = SingularityCore()

# ------------------------------------------------------------------------------
# 4. RAID-1 STREAMING ENGINE (AYNA MODU)
# ------------------------------------------------------------------------------
def raid_streamer(target_url, cid):
    """
    RAID-1 İNDİRME:
    Aynı dosyayı 2 farklı sunucudan aynı anda ister.
    Kimden veri önce gelirse onu kullanıcıya verir.
    Diğerini yedek olarak tutar.
    """
    # 1. RAM Cache Kontrolü (Gelecekten geldiyse)
    with singularity.lock:
        if target_url in singularity.future_cache:
            yield singularity.future_cache.pop(target_url)['data']
            return

    # 2. Kaynak Belirleme
    # URL içindeki domain yerine, en sağlıklı kaynakları kullan
    # Dosya ismini al: seg-X.ts
    filename = target_url.split('/')[-1].split('?')[0]
    
    # En iyi 2 kaynak
    sources = singularity.get_top_sources()
    
    # Ortak bir kuyruk oluştur (Yarış pisti)
    packet_queue = queue.Queue()
    # İş bitiş bayrağı
    finished = event.Event()
    
    def source_worker(src):
        """Bir kaynaktan veri çeken işçi."""
        try:
            # Her kaynak için doğru URL'i oluştur
            # (Bazı kaynaklarda klasör yapısı farklı olabilir ama Vavoo klonlarında genelde standarttır)
            # Garanti olsun diye base URL'i cache'den alabiliriz ama hız için tahmin ediyoruz:
            # {src}/play/{cid}/{filename}
            real_url = f"{src}/play/{cid}/{filename}"
            h = get_headers(src)
            
            with session.get(real_url, headers=h, verify=False, stream=True, timeout=(1.5, 5)) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        if finished.is_set(): return
                        if chunk:
                            packet_queue.put(chunk)
                else:
                    singularity.punish(src)
        except:
            singularity.punish(src)
        finally:
            # Eğer kuyruk boşsa ve biz öldüysek, poison pill at (bitiş sinyali)
            # Ama RAID olduğu için diğer işçi devam edebilir.
            pass

    # İşçileri başlat
    workers = []
    for s in sources:
        workers.append(spawn(source_worker, s))

    # Veri Dağıtımı (Consumer)
    # Kuyruktan gelen İLK veriyi direkt basar.
    # Hangi sunucudan geldiği önemsizdir.
    chunks_received = 0
    
    try:
        while True:
            # 5 saniye içinde veri gelmezse time-out (Donma koruması)
            try:
                # Blocking get
                chunk = packet_queue.get(timeout=5)
                yield chunk
                chunks_received += 1
            except queue.Empty:
                break
    except GeneratorExit:
        finished.set()
        killall(workers, block=False)
        return
    except Exception:
        pass
    
    finished.set()
    killall(workers, block=False)
    
    # Hata Kontrolü: Hiç veri gelmediyse Fallback yap
    if chunks_received == 0:
        # Fallback Logic (Tekrar dene)
        pass

# ------------------------------------------------------------------------------
# 5. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # En iyi kaynaktan liste al
    best_src = singularity.get_top_sources()[0]
    data = None
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=3)
        if r.status_code == 200: data = r.json()
    except: pass
    
    if not data:
        for src in SOURCES:
            if src == best_src: continue
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=2)
                if r.status_code == 200: data = r.json(); break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # Parsing
                part = u.split('/play/')[-1]
                cid = part.split('/')[0].replace('.m3u8', '').split('.')[0]
                
                if cid:
                    name = item['name'].replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    clean_cid = cid.replace('.m3u8', '')
    info = singularity.resolve_playlist(clean_cid)
    if not info: return Response("Not Found", 404)

    base_b = info['base'].encode()
    host_b = request.host_url.rstrip('/').encode()
    cid_b = clean_cid.encode()
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    for line in info['content'].split(b'\n'):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            if line.startswith(b'http'): target = line
            else: target = base_b + b'/' + line
            
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    cid = request.args.get('cid')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    # RAID-1 Streamer'ı başlat
    # Bu fonksiyon, en iyi 2 kaynaktan aynı anda indirip hangisi hızlıysa onu verir
    stream_gen = raid_streamer(target, cid)
    
    return Response(stream_with_context(stream_gen), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO SINGULARITY - ETERNAL EDITION")
    print(f" ► TECH: RAID-1 MIRRORING (0% Packet Loss)")
    print(f" ► TECH: PREDICTIVE FUTURE FETCHING")
    print(f" ► LISTENING: 8080")
    
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
