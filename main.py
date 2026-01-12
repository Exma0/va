# ==============================================================================
# VAVOO PROXY - TITAN V3 (HYPERSPEED EDITION)
# Tech: Low-Level Socket Streaming | Async Learning | Zero-Latency Loop
# Status: OPTIMIZED (Maksimum Hız)
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import random
from gevent import pool, event, spawn, lock
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ------------------------------------------------------------------------------
# 1. SİSTEM AYARLARI
# ------------------------------------------------------------------------------
gc.set_threshold(100000, 50, 50)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# Urllib3 Uyarılarını Kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
# Logları tamamen kapat (Hız için kritik)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. HIZLI NETWORK HAVUZU (RAW SOCKET POOL)
# ------------------------------------------------------------------------------
# Requests Session (Sadece Playlist ve API için)
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=1000,
    pool_maxsize=10000,
    max_retries=0,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# RAW Pool Manager (Video Akışı İçin - Requests'ten çok daha hızlıdır)
http_pool = urllib3.PoolManager(
    num_pools=1000,
    maxsize=10000,
    block=False,
    retries=False,
    timeout=urllib3.Timeout(connect=2.0, read=7.0)
)

HEADERS_MEM = {}
def get_headers(base_url):
    if base_url not in HEADERS_MEM:
        HEADERS_MEM[base_url] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{base_url}/",
            "Connection": "keep-alive"
        }
    return HEADERS_MEM[base_url]

# ------------------------------------------------------------------------------
# 3. LIGHTWEIGHT NEURAL BRAIN (HAFİFLETİLMİŞ BEYİN)
# ------------------------------------------------------------------------------
class NeuralBrain:
    def __init__(self):
        self.weights = {src: 5.0 for src in SOURCES} # 0.1 - 10.0 arası
        self.cache = {} 
        self.lock = lock.RLock() # Thread safe lock
        
        # Unutma faktörü (Memory Decay)
        spawn(self._memory_decay)

    def _memory_decay(self):
        while True:
            time.sleep(15)
            # Kilit (Lock) kullanmadan yaklaşık değerlerle işlem yap (Hız için)
            for src in SOURCES:
                if self.weights[src] > 5.0: self.weights[src] *= 0.99
                if self.weights[src] < 5.0: self.weights[src] *= 1.01

    def train_async(self, source, success):
        """Eğitimi ana akışı bloklamadan arka planda yap"""
        spawn(self._train_worker, source, success)

    def _train_worker(self, source, success):
        with self.lock:
            if success:
                self.weights[source] = min(10.0, self.weights[source] * 1.05)
            else:
                self.weights[source] = max(0.1, self.weights[source] * 0.5)

    def predict_best_source(self):
        """En iyi kaynağı seçer (Hızlı versiyon)"""
        # Hız için kopyalama yapmadan işlem yapmaya çalışıyoruz
        try:
            total = sum(self.weights.values())
            pick = random.uniform(0, total)
            current = 0
            for src, weight in self.weights.items():
                current += weight
                if current > pick: return src
        except: pass
        return SOURCES[0]

    def resolve_playlist(self, cid):
        now = time.time()
        cid_clean = cid.replace('.m3u8', '')
        
        # Cache Check
        if cid_clean in self.cache:
            entry = self.cache[cid_clean]
            if now < entry['expires']: return entry['data']

        primary = self.predict_best_source()
        
        # Tek işçi ile hızlı deneme (Parallel overhead'inden kaçınmak için önce en iyiyi dene)
        try:
            res = self._fetch_playlist(primary, cid_clean)
            if res: 
                self.cache[cid_clean] = {'expires': now + 300, 'data': res}
                self.train_async(primary, True)
                return res
        except:
            self.train_async(primary, False)

        # Eğer favori başarısızsa, diğerlerini dene
        for src in SOURCES:
            if src == primary: continue
            try:
                res = self._fetch_playlist(src, cid_clean)
                if res:
                    self.cache[cid_clean] = {'expires': now + 300, 'data': res}
                    self.train_async(src, True)
                    return res
            except: pass
            
        return None

    def _fetch_playlist(self, src, cid):
        url = f"{src}/play/{cid}/index.m3u8"
        h = get_headers(src)
        with session.get(url, headers=h, verify=False, timeout=2.0) as r:
            if r.status_code == 200:
                return {
                    'content': r.content,
                    'base': r.url.rsplit('/', 1)[0],
                    'source': src
                }
        return None

brain = NeuralBrain()

# ------------------------------------------------------------------------------
# 4. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # En basit haliyle listeyi çek
    best_src = brain.predict_best_source()
    data = None
    
    # Önce en iyi kaynaktan dene
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=3)
        if r.status_code == 200: data = r.json()
    except: pass
    
    # Olmazsa yedeklerden biri
    if not data:
        for src in SOURCES:
            if src == best_src: continue
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=3)
                if r.status_code == 200: 
                    data = r.json()
                    break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    # String birleştirme maliyetini azaltmak için list append kullanıyoruz
    for item in data:
        if item.get("group") == "Turkey":
            try:
                # String işlemleri CPU yorar, minimuma indirildi
                u = item['url']
                # Hızlı split
                cid = u.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                
                name = item['name'].replace(',', ' ')
                out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    info = brain.resolve_playlist(cid)
    if not info: return Response("Not Found", 404)

    base_b = info['base'].encode()
    host_b = request.host_url.rstrip('/').encode()
    cid_b = cid.replace('.m3u8', '').encode()
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    # Byte işlemi yaparak string decode/encode maliyetinden kaçıyoruz
    lines = info['content'].split(b'\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line[0] == 35: # b'#' karakterinin ASCII kodu 35
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            # Segment URL oluşturma
            if line.startswith(b'http'): 
                target = line
            else: 
                target = base_b + b'/' + line
            
            # URL encode işlemini sadece target için yap
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    # Argument parsing'i hızlandır
    args = request.args
    url_enc = args.get('url')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    # Basit kaynak tespiti
    current_source = "https://vavoo.to"
    for s in SOURCES:
        if s in target:
            current_source = s
            break
            
    h = get_headers(current_source)

    def fast_stream():
        try:
            # Requests yerine URLLIB3 kullanıyoruz (Daha Hızlı)
            # preload_content=False ile hafızaya almadan stream eder
            r = http_pool.request('GET', target, headers=h, preload_content=False)
            
            if r.status == 200:
                brain.train_async(current_source, True)
                # Tampon boyutunu artırdık: 128KB (Daha az döngü = Daha az CPU)
                # stream() metodu generator döner
                for chunk in r.stream(131072):
                    yield chunk
                r.release_conn()
            else:
                r.release_conn()
                brain.train_async(current_source, False)
                # Hata durumunda (403/404/500) boş dön, client retry yapsın
                # Proxy'nin retry yapması canlı yayında gecikme yaratır.
                return 

        except Exception:
            brain.train_async(current_source, False)
            return

    return Response(stream_with_context(fast_stream()), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► TITAN V3 - HYPERSPEED EDITION")
    print(f" ► MODE: Raw Socket Streaming")
    # Log: None (Maksimum performans)
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
