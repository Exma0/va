# ==============================================================================
# VAVOO OMEGA - ENDGAME EDITION
# Features: Global RAM Cache | RAID-1 Mirroring | Titanium Compatibility
# Status: APEX PREDATOR (Zirve Avcı)
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import sys
import re
from gevent import pool, event, spawn, sleep, lock, queue, killall
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote, urljoin, urlparse

# ------------------------------------------------------------------------------
# 1. MAKİNE AYARLARI
# ------------------------------------------------------------------------------
sys.setswitchinterval(0.001)
gc.set_threshold(100000, 50, 50)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

MIN_TS_SIZE = 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=5000,
    pool_maxsize=50000,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

HEADERS_MEM = {}
def get_headers(target_url):
    parsed = urlparse(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    # Vavoo Header Check
    if origin not in HEADERS_MEM:
        HEADERS_MEM[origin] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{origin}/",
            "Origin": origin,
            "Connection": "keep-alive"
        }
    return HEADERS_MEM[origin]

# ------------------------------------------------------------------------------
# 3. GLOBAL RAM CACHE (ORTAK HAFIZA)
# ------------------------------------------------------------------------------
# Aynı anda aynı segmenti isteyen kullanıcılar için veriyi RAM'de tutar.
# { 'segment_url': {'data': bytes, 'ts': time.time()} }
GLOBAL_SEGMENT_CACHE = {}
CACHE_LOCK = lock.RLock()

def cache_cleaner():
    """Eski segmentleri RAM'den siler."""
    while True:
        sleep(5)
        now = time.time()
        with CACHE_LOCK:
            # 15 saniyeden eski verileri sil
            expired = [k for k, v in GLOBAL_SEGMENT_CACHE.items() if now - v['ts'] > 15]
            for k in expired: del GLOBAL_SEGMENT_CACHE[k]

spawn(cache_cleaner)

# ------------------------------------------------------------------------------
# 4. OMEGA CORE (AKIL MERKEZİ)
# ------------------------------------------------------------------------------
class OmegaCore:
    def __init__(self):
        self.health = {src: 100.0 for src in SOURCES}
        self.channel_map = {} # {cid: {final_url, source_root, expires}}
        self.lock = lock.RLock()
        # Zamanla iyileşme
        spawn(self._healer)

    def _healer(self):
        while True:
            sleep(10)
            with self.lock:
                for src in self.health:
                    if self.health[src] < 100: self.health[src] += 10

    def punish(self, source, amount=20):
        with self.lock:
            self.health[source] -= amount

    def get_best_sources(self):
        with self.lock:
            return sorted(SOURCES, key=lambda s: self.health[s], reverse=True)

    def resolve_stream(self, cid):
        """Kanalın gerçek (tokenlı) adresini bulur."""
        now = time.time()
        
        # Cache Check
        if cid in self.channel_map:
            entry = self.channel_map[cid]
            if now < entry['expires']: return entry

        # Kaynakları sağlık sırasına göre dene
        candidates = self.get_best_sources()
        
        for src in candidates:
            try:
                # Redirect takibi açık
                initial = f"{src}/play/{cid}/index.m3u8"
                h = get_headers(initial)
                r = session.get(initial, headers=h, verify=False, timeout=4, allow_redirects=True)
                
                if r.status_code == 200 and b"#EXTM3U" in r.content:
                    final_url = r.url
                    result = {
                        'final_url': final_url,
                        'source_root': src,
                        'content': r.content,
                        'expires': now + 300
                    }
                    self.channel_map[cid] = result
                    return result
            except: 
                self.punish(src, 5)
        return None

omega = OmegaCore()

# ------------------------------------------------------------------------------
# 5. RAID-1 DOWNLOADER (ÇİFT MOTORLU İNDİRİCİ)
# ------------------------------------------------------------------------------
def download_segment_raid(target_url, cid):
    """
    Aynı dosyayı hem ana kaynaktan hem de yedekten aynı anda ister.
    Kim 0-byte olmayan veriyi önce getirirse onu kullanır.
    """
    # 1. GLOBAL CACHE CHECK (Başka biri indirdiyse direkt al)
    with CACHE_LOCK:
        if target_url in GLOBAL_SEGMENT_CACHE:
            yield GLOBAL_SEGMENT_CACHE[target_url]['data']
            return

    # 2. Kaynak Hazırlığı
    # Mevcut en iyi kaynakları al
    sources = omega.get_best_sources()[:2] # En iyi 2 kaynak
    
    # URL'den dosya ismini çıkar: seg-10.ts
    filename = target_url.split('/')[-1].split('?')[0]
    
    # Yarış Pisti
    result_queue = queue.Queue()
    finished_event = event.Event()
    
    def worker(src):
        try:
            # Her kaynak için olası URL'i oluştur
            # Vavoo yapısı: {src}/play/{cid}/{filename}
            # NOT: Bu tahminidir. Eğer başarısız olursa aşağıda Fallback var.
            real_url = f"{src}/play/{cid}/{filename}"
            h = get_headers(real_url)
            
            with session.get(real_url, headers=h, verify=False, stream=True, timeout=(2, 6)) as r:
                if r.status_code == 200:
                    # İlk paketi oku (0-Byte kontrolü)
                    first = next(r.iter_content(chunk_size=4096), None)
                    if first and len(first) > 0:
                        # Başarılı! Veriyi topla
                        data = bytearray(first)
                        for chunk in r.iter_content(chunk_size=65536):
                            if finished_event.is_set(): return
                            if chunk: data.extend(chunk)
                        
                        # Tamamlandı, kuyruğa at
                        result_queue.put(bytes(data))
                        finished_event.set() # Diğer işçiyi durdur
                    else:
                        omega.punish(src, 50) # 0-Byte cezası
                else:
                    omega.punish(src, 10)
        except:
            omega.punish(src, 10)

    # İşçileri Başlat
    greenlets = []
    for s in sources:
        greenlets.append(spawn(worker, s))
    
    # Sonucu Bekle
    try:
        # 7 saniye içinde veri gelmezse pes et
        final_data = result_queue.get(timeout=7)
        
        # Diğer işçileri temizle
        killall(greenlets, block=False)
        
        # RAM'e kaydet (Cache)
        with CACHE_LOCK:
            GLOBAL_SEGMENT_CACHE[target_url] = {'data': final_data, 'ts': time.time()}
            
        yield final_data
        
    except queue.Empty:
        # HİÇBİRİNDEN VERİ GELMEDİ -> FALLBACK MODE
        # Demek ki tahmin ettiğimiz URL yapısı (/play/cid/seg.ts) yanlış olabilir.
        # Tokenlı orijinal URL'den gitmeyi deneyelim.
        killall(greenlets, block=False)
        
        # Bu durumda tekil (RAID olmayan) güvenli indirme yapıyoruz
        try:
            h = get_headers(target_url)
            with session.get(target_url, headers=h, verify=False, stream=True, timeout=8) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        yield chunk
        except: pass

# ------------------------------------------------------------------------------
# 6. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # Liste kaynağı
    best = omega.get_best_sources()[0]
    data = None
    try:
        r = session.get(f"{best}/live2/index", verify=False, timeout=3)
        if r.status_code == 200: data = r.json()
    except: pass
    
    if not data:
        for s in SOURCES:
            if s == best: continue
            try:
                r = session.get(f"{s}/live2/index", verify=False, timeout=3)
                if r.status_code == 200: data = r.json(); break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # Gelişmiş ID Parsing
                if '/play/' in u:
                    rest = u.split('/play/')[-1]
                    if '/' in rest: cid = rest.split('/')[0]
                    else: cid = rest.split('.')[0]
                    cid = cid.split('.')[0] # Nokta temizliği
                    
                    if cid.isdigit():
                        name = item['name'].replace(',', ' ')
                        out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                        out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    clean_cid = cid.split('.')[0]
    info = omega.resolve_stream(clean_cid)
    
    if not info: return Response("Not Found", 404)

    # Base URL: http://cdn.server.com/hls/123
    base_url = info['final_url'].rsplit('/', 1)[0]
    
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
            # Segment Linki
            line_str = line.decode()
            # Mutlak URL oluştur
            full_ts_url = urljoin(base_url + "/", line_str)
            
            # Parametre olarak TAM URL'i gönderiyoruz ki
            # RAID sistemi başarısız olursa Fallback olarak bunu kullansın.
            safe_target = quote(full_ts_url).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_param = request.args.get('url')
    cid = request.args.get('cid')
    
    if not url_param: return "Bad", 400
    
    target_url = unquote(url_param)
    
    # OMEGA RAID İNDİRME BAŞLAT
    return Response(stream_with_context(download_segment_raid(target_url, cid)), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO OMEGA - ENDGAME")
    print(f" ► SYSTEM: RAID-1 + GLOBAL RAM CACHE")
    print(f" ► LISTENING: 8080")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
