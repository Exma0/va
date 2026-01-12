# ==============================================================================
# VAVOO PROXY - TITAN V4.1 (LIST FIXED + STABLE STREAM)
# Tech: Low-Level Socket Streaming | Zero-Overhead Loop
# Status: FIXED (Kanal Listesi Geri Getirildi + Donma Yok)
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

http_pool = urllib3.PoolManager(
    num_pools=100,
    maxsize=1000,
    block=False,
    retries=urllib3.Retry(1, redirect=False),
    timeout=urllib3.Timeout(connect=3.0, read=10.0)
)

HEADERS_MEM = {}
def get_headers(base_url):
    if base_url not in HEADERS_MEM:
        HEADERS_MEM[base_url] = {
            "User-Agent": "Vavoo/2.6",
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
            time.sleep(30)
            for src in SOURCES:
                if self.weights[src] > 5.0: self.weights[src] *= 0.99
                if self.weights[src] < 5.0: self.weights[src] *= 1.01

    def train_async(self, source, success):
        spawn(self._train_worker, source, success)

    def _train_worker(self, source, success):
        with self.lock:
            if success:
                self.weights[source] = min(10.0, self.weights[source] + 0.5)
            else:
                self.weights[source] = max(0.1, self.weights[source] - 1.0)

    def predict_best_source(self):
        try:
            return max(self.weights, key=self.weights.get)
        except:
            return SOURCES[0]

    def resolve_playlist(self, cid):
        now = time.time()
        cid_clean = cid.replace('.m3u8', '')
        
        if cid_clean in self.cache:
            entry = self.cache[cid_clean]
            if now < entry['expires']: return entry['data']

        best = self.predict_best_source()
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
    # --- LISTE OLUŞTURMA KISMI GERİ EKLENDİ ---
    best_src = brain.predict_best_source()
    sources_to_try = [best_src] + [s for s in SOURCES if s != best_src]
    
    data = None
    
    # Kaynaklardan listeyi çekmeyi dene
    for src in sources_to_try:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=4)
            if r.status_code == 200: 
                data = r.json()
                brain.train_async(src, True)
                break
        except: 
            brain.train_async(src, False)
            continue

    if not data: 
        return Response("#EXTM3U\n#EXTINF:-1,Sunucu Hatasi - Liste Alinamadi\nhttp://localhost", content_type="application/vnd.apple.mpegurl")

    host_b = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # String birleştirme optimizasyonu (Hızlı liste oluşturma)
    for item in data:
        # Sadece Türkiye kanallarını al (İsterseniz bu if'i kaldırıp hepsini alabilirsiniz)
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # URL'den ID'yi ayıkla
                cid = u.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                
                name = item['name'].replace(',', ' ').strip()
                out.append(f'#EXTINF:-1 group-title="Turkey",{name}')
                out.append(f'{host_b}/live/{cid}.m3u8')
            except: pass

    return Response("\n".join(out), content_type="application/vnd.apple.mpegurl")

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
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            if line.startswith(b'http'): 
                target = line
            else: 
                target = base_b + b'/' + line
            
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    args = request.args
    url_enc = args.get('url')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    current_source = "https://huhu.to"
    for s in SOURCES:
        if s in target:
            current_source = s
            break
            
    h = get_headers(current_source)

    try:
        req = http_pool.request('GET', target, headers=h, preload_content=False)
    except Exception:
        brain.train_async(current_source, False)
        return Response("Err", 502)

    if req.status != 200:
        req.release_conn()
        brain.train_async(current_source, False)
        return Response("Err", 502)

    headers = {
        'Content-Type': 'video/mp2t',
        'Connection': 'keep-alive'
    }

    # DONMA SORUNUNU ÇÖZEN OPTİMİZE DÖNGÜ
    def fast_stream():
        chunk_size = 65536 # 64KB
        try:
            for chunk in req.stream(chunk_size):
                yield chunk
            brain.train_async(current_source, True)
        except Exception:
            brain.train_async(current_source, False)
        finally:
            req.release_conn()

    return Response(stream_with_context(fast_stream()), headers=headers, content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► TITAN V4.1 - LIST FIXED")
    print(f" ► MODE: 64KB CHUNKS | ZERO-OVERHEAD")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=10000, log=None)
    server.serve_forever()
