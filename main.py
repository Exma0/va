# ==============================================================================
# VAVOO PROXY - TITAN V4 (UNLEASHED EDITION)
# Tech: Low-Level Socket Streaming | Zero-Overhead Loop
# Status: FIXED (CPU Bottleneck Removed - Donma Kesin Çözüm)
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
# GC Ayarını normale çekiyoruz, agresif GC donma yaratır
gc.set_threshold(700, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. HIZLI NETWORK HAVUZU
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=100,
    pool_maxsize=1000,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Akış havuzu için ayarlar (Timeoutlar optimize edildi)
http_pool = urllib3.PoolManager(
    num_pools=100,
    maxsize=1000,
    block=False,
    retries=urllib3.Retry(1, redirect=False), # En az 1 retry hayat kurtarır
    timeout=urllib3.Timeout(connect=3.0, read=10.0)
)

HEADERS_MEM = {}
def get_headers(base_url):
    if base_url not in HEADERS_MEM:
        HEADERS_MEM[base_url] = {
            "User-Agent": "Vavoo/2.6", # User agent'ı Vavoo native yaptık
            "Referer": f"{base_url}/",
            "Connection": "keep-alive"
        }
    return HEADERS_MEM[base_url]

# ------------------------------------------------------------------------------
# 3. LIGHTWEIGHT NEURAL BRAIN
# ------------------------------------------------------------------------------
class NeuralBrain:
    def __init__(self):
        self.weights = {src: 5.0 for src in SOURCES}
        self.cache = {} 
        self.lock = lock.RLock()
        spawn(self._memory_decay)

    def _memory_decay(self):
        while True:
            time.sleep(30) # 15sn çok sıktı, 30sn yaptık
            for src in SOURCES:
                if self.weights[src] > 5.0: self.weights[src] *= 0.99
                if self.weights[src] < 5.0: self.weights[src] *= 1.01

    def train_async(self, source, success):
        # Greenlet spawn maliyetini düşürmek için kontrol
        spawn(self._train_worker, source, success)

    def _train_worker(self, source, success):
        # Basit matematiksel işlem, lock süresini minimize et
        with self.lock:
            if success:
                self.weights[source] = min(10.0, self.weights[source] + 0.5)
            else:
                self.weights[source] = max(0.1, self.weights[source] - 1.0)

    def predict_best_source(self):
        try:
            # Random seçim yerine en yüksek puanlıyı al (daha kararlı)
            return max(self.weights, key=self.weights.get)
        except:
            return SOURCES[0]

    def resolve_playlist(self, cid):
        now = time.time()
        cid_clean = cid.replace('.m3u8', '')
        
        if cid_clean in self.cache:
            entry = self.cache[cid_clean]
            if now < entry['expires']: return entry['data']

        # Sadece en iyi kaynağı dene, olmazsa hepsini gez
        # (Önceki kodda çok fazla iç içe logic vardı, sadeleştirdik)
        best = self.predict_best_source()
        
        # Liste sıralaması: [En İyi, ...Diğerleri]
        order = [best] + [s for s in SOURCES if s != best]
        
        for src in order:
            try:
                res = self._fetch_playlist(src, cid_clean)
                if res: 
                    self.cache[cid_clean] = {'expires': now + 300, 'data': res}
                    self.train_async(src, True)
                    return res
            except:
                pass
        
        return None

    def _fetch_playlist(self, src, cid):
        url = f"{src}/play/{cid}/index.m3u8"
        h = get_headers(src)
        # Timeout'u kısa tut, cevap vermiyorsa hemen diğerine geç
        with session.get(url, headers=h, verify=False, timeout=2.5) as r:
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
    return Response("Titan Proxy Active", 200)

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    info = brain.resolve_playlist(cid)
    if not info: return Response("Not Found", 404)

    base_b = info['base'].encode()
    host_b = request.host_url.rstrip('/').encode()
    cid_b = cid.replace('.m3u8', '').encode()
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    lines = info['content'].split(b'\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line[0] == 35: # b'#'
            if b"EXT-X-KEY" in line: continue # Şifreli yayınları pas geç
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            if line.startswith(b'http'): 
                target = line
            else: 
                target = base_b + b'/' + line
            
            # URL encode işlemini hızlandır
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    args = request.args
    url_enc = args.get('url')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    # Hangi kaynaktan çektiğimizi bulalım (Training için)
    current_source = "https://vavoo.to"
    for s in SOURCES:
        if s in target:
            current_source = s
            break
            
    h = get_headers(current_source)

    try:
        # preload_content=False ile hafızayı koru
        req = http_pool.request('GET', target, headers=h, preload_content=False)
    except Exception:
        brain.train_async(current_source, False)
        return Response("Err", 502)

    if req.status != 200:
        req.release_conn()
        brain.train_async(current_source, False)
        return Response("Err", 502)

    # Gereksiz headerları at
    headers = {
        'Content-Type': 'video/mp2t',
        'Connection': 'keep-alive'
    }

    # --------------------------------------------------------------------------
    # OPTİMİZE EDİLMİŞ STREAM LOOP (Donmayı Çözen Kısım)
    # --------------------------------------------------------------------------
    def fast_stream():
        chunk_size = 65536 # 64KB (8KB çok düşüktü, darboğaz yapıyordu)
        try:
            # Döngü içinde ASLA brain.train_async çağırma!
            # Veri akarken işlemci sadece veriyi pompalamalı.
            for chunk in req.stream(chunk_size):
                yield chunk
            
            # Akış başarıyla biterse döngüden çıkınca 1 kere puan ver
            brain.train_async(current_source, True)
            
        except Exception:
            brain.train_async(current_source, False)
        finally:
            req.release_conn()

    return Response(stream_with_context(fast_stream()), headers=headers, content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► TITAN V4 - UNLEASHED")
    print(f" ► MODE: 64KB CHUNKS | ZERO-LOOP-OVERHEAD")
    # worker_connections artırıldı
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=10000, log=None)
    server.serve_forever()
