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
import logging

# GC ayarları streaming için optimize edildi (Takılmaları önler)
gc.set_threshold(700, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

# Session ayarları
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=200,    # Aşırı yüksek değerler RAM şişirir, 200 idealdir
    pool_maxsize=200,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# urllib3 PoolManager - Daha hızlı raw soket işlemleri için
http_pool = urllib3.PoolManager(
    num_pools=100,
    maxsize=200,
    block=False,
    retries=False,
    timeout=urllib3.Timeout(connect=3.0, read=15.0) # Timeoutlar sıkılaştırıldı
)

HEADERS_MEM = {}
def get_headers(base_url):
    if base_url not in HEADERS_MEM:
        HEADERS_MEM[base_url] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{base_url}/",
            "Connection": "keep-alive",
            "Accept-Encoding": "identity" # Sıkıştırma istemiyoruz, direkt stream istiyoruz
        }
    return HEADERS_MEM[base_url]

class NeuralBrain:
    def __init__(self):
        self.weights = {src: 5.0 for src in SOURCES}
        self.cache = {} 
        self.lock = lock.RLock()
        
        spawn(self._memory_decay)

    def _memory_decay(self):
        while True:
            time.sleep(15)
            for src in SOURCES:
                if self.weights[src] > 5.0: self.weights[src] *= 0.99
                if self.weights[src] < 5.0: self.weights[src] *= 1.01

    def train_async(self, source, success):
        spawn(self._train_worker, source, success)

    def _train_worker(self, source, success):
        with self.lock:
            if success:
                self.weights[source] = min(10.0, self.weights[source] * 1.05)
            else:
                self.weights[source] = max(0.1, self.weights[source] * 0.5)

    def predict_best_source(self):
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
        
        if cid_clean in self.cache:
            entry = self.cache[cid_clean]
            if now < entry['expires']: return entry['data']

        primary = self.predict_best_source()
        
        try:
            res = self._fetch_playlist(primary, cid_clean)
            if res: 
                self.cache[cid_clean] = {'expires': now + 300, 'data': res}
                self.train_async(primary, True)
                return res
        except:
            self.train_async(primary, False)

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
        try:
            with session.get(url, headers=h, verify=False, timeout=4.0) as r:
                if r.status_code == 200:
                    return {
                        'content': r.content,
                        'base': r.url.rsplit('/', 1)[0],
                        'source': src
                    }
        except: pass
        return None

brain = NeuralBrain()

@app.route('/')
def root():
    best_src = brain.predict_best_source()
    data = None
    
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=4)
        if r.status_code == 200: data = r.json()
    except: pass
    
    if not data:
        for src in SOURCES:
            if src == best_src: continue
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=4)
                if r.status_code == 200: 
                    data = r.json()
                    break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item['url']
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
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3"]
    
    lines = info['content'].split(b'\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line[0] == 35: # # karakteri
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            if line.startswith(b'http'): 
                target = line
            else: 
                target = base_b + b'/' + line
            
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
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
        # preload_content=False, stream modudur.
        req = http_pool.request('GET', target, headers=h, preload_content=False)
    except Exception:
        brain.train_async(current_source, False)
        return Response("Gateway Error", 502)

    if req.status != 200:
        req.release_conn()
        brain.train_async(current_source, False)
        return Response("Source Error", 502)

    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
    headers = [
        (k, v) for k, v in req.headers.items()
        if k.lower() not in excluded_headers
    ]

    def fast_stream():
        # Yapay zeka eğitimini asenkron başlat, stream'i bekletme
        brain.train_async(current_source, True) 
        try:
            # KRİTİK DÜZELTME: Chunk size 8192 -> 65536 (64KB)
            # Daha büyük chunk = Daha az CPU kesintisi = Akıcı Yayın
            for chunk in req.stream(65536): 
                if chunk:
                    yield chunk
        except Exception:
            pass # Bağlantı koptuysa sessizce bitir
        finally:
            try: req.release_conn()
            except: pass

    return Response(stream_with_context(fast_stream()), headers=headers, content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► TITAN V3 - STABLE & FLUID EDITION")
    print(f" ► MODE: High Performance Streaming (64KB Chunks)")
    # Backlog artırıldı, yoğun isteklerde kuyruk dolmasın
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=100000, log=None)
    server.serve_forever()
