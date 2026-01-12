# ==============================================================================
# VAVOO PROXY - TITAN V4 (BUFFER FIX EDITION)
# Tech: Content-Length Forwarding | 32KB Burst | Socket Tuning
# Status: CRITICAL FIX (Donma/Buffer Sorunu İçin)
# ==============================================================================

from gevent import monkey
# Soketleri en başta patchle
monkey.patch_all()

import time
import requests
import urllib3
import gc
import random
import socket
from gevent import pool, event, spawn, lock
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ------------------------------------------------------------------------------
# 1. SİSTEM AYARLARI
# ------------------------------------------------------------------------------
# Garbage Collection'ı biraz daha sıkı tut (Memory leak önlemi)
gc.set_threshold(50000, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# Urllib3 Uyarılarını Kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. HIZLI NETWORK HAVUZU (RAW SOCKET POOL)
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=500,
    pool_maxsize=1000,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Video Akışı İçin Özel Havuz
http_pool = urllib3.PoolManager(
    num_pools=500,
    maxsize=1000,
    block=False,
    retries=False,
    # Bağlantı süresini kısa tut, okuma süresini uzun tut
    timeout=urllib3.Timeout(connect=3.0, read=30.0),
    # Headerları otomatik yönetme, biz yöneteceğiz
    headers={"Connection": "keep-alive"}
)

# User Agent'ı Vavoo Android uygulaması gibi göster (Engellenmeyi azaltır)
HEADERS_MEM = {}
def get_headers(base_url):
    if base_url not in HEADERS_MEM:
        HEADERS_MEM[base_url] = {
            "User-Agent": "Vavoo/2.6 (Android; Mobile; PlayStore)",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Referer": f"{base_url}/"
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
        
        # İlk deneme
        res = self._attempt_fetch(primary, cid_clean)
        if res: return res

        # Yedekler
        for src in SOURCES:
            if src == primary: continue
            res = self._attempt_fetch(src, cid_clean)
            if res: return res
            
        return None

    def _attempt_fetch(self, src, cid):
        try:
            url = f"{src}/play/{cid}/index.m3u8"
            h = get_headers(src)
            with session.get(url, headers=h, verify=False, timeout=3.0) as r:
                if r.status_code == 200:
                    self.train_async(src, True)
                    data = {
                        'content': r.content,
                        'base': r.url.rsplit('/', 1)[0],
                        'source': src
                    }
                    self.cache[cid] = {'expires': time.time() + 300, 'data': data}
                    return data
        except:
            self.train_async(src, False)
        return None

brain = NeuralBrain()

# ------------------------------------------------------------------------------
# 4. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # Basit kanal listesi
    best_src = brain.predict_best_source()
    data = None
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=4)
        if r.status_code == 200: data = r.json()
    except: pass
    
    if not data:
        # Fallback
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
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    lines = info['content'].split(b'\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line[0] == 35:
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
    args = request.args
    url_enc = args.get('url')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    current_source = "https://vavoo.to"
    for s in SOURCES:
        if s in target:
            current_source = s
            break
            
    h = get_headers(current_source)

    try:
        # Preload False: Hafızaya alma, direkt akıt
        req = http_pool.request('GET', target, headers=h, preload_content=False)
    except Exception:
        return Response("Gateway Error", 502)

    if req.status != 200:
        req.release_conn()
        return Response("Source Error", 502)

    # --- KRİTİK DÜZELTME: HEADER YÖNETİMİ ---
    # Transfer-Encoding'i siliyoruz çünkü biz chunked göndermeyeceğiz,
    # akış yapacağız ama Content-Length varsa kesinlikle iletmeliyiz.
    excluded_headers = ['transfer-encoding', 'connection', 'content-encoding']
    headers = []
    
    for k, v in req.headers.items():
        k_lower = k.lower()
        if k_lower not in excluded_headers:
            headers.append((k, v))

    # Eğer kaynak Content-Length verdiyse, oynatıcıya bunun bittiğini söylemek için şarttır.
    # Bu, oynatıcının %100 yüklendiğini anlamasını sağlar.

    def fast_stream():
        try:
            brain.train_async(current_source, True)
            # --- KRİTİK DÜZELTME: CHUNK SIZE 32KB ---
            # 8KB yerine 32KB (32768) kullanıyoruz. 
            # Bu, CPU context switch'i azaltır ve veri akışını daha stabil yapar.
            for chunk in req.stream(32768):
                yield chunk
        except Exception:
            brain.train_async(current_source, False)
        finally:
            try: req.release_conn()
            except: pass

    return Response(stream_with_context(fast_stream()), headers=headers, content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► TITAN V4 - BUFFER FIX EDITION")
    print(f" ► MODE: Content-Length Passthrough | 32KB Chunks")
    
    # TCP Soket Ayarları (Daha agresif iletim için)
    # Bu kısım sunucunun veriyi işletim sistemi bufferında bekletmeden atmasını sağlar.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    listener.bind(('0.0.0.0', 8080))
    listener.listen(65535)

    server = WSGIServer(listener, app, log=None)
    server.serve_forever()
