# ==============================================================================
# VAVOO PROXY - TACHYON EDITION (V2 - BUGFIX)
# Fix: Double Extension Error (.m3u8.m3u8)
# Status: Production Ready
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import socket
from gevent import pool, event, spawn, sleep, lock
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote
from collections import deque

# ------------------------------------------------------------------------------
# 1. KERNEL & MEMORY OPTIMIZATION
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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Logları sustur
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK STACK
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=4000,
    pool_maxsize=40000,
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
# 3. TACHYON ENGINE
# ------------------------------------------------------------------------------
class TachyonBrain:
    def __init__(self):
        self.cache = {}         
        self.prefetch = {}      
        self.lock = lock.RLock()
        self.scores = {src: 10.0 for src in SOURCES} 
        spawn(self._cleaner)

    def _cleaner(self):
        while True:
            sleep(10)
            now = time.time()
            with self.lock:
                expired = [k for k, v in self.prefetch.items() if now - v['ts'] > 20]
                for k in expired: del self.prefetch[k]

    def _speculative_loader(self, ts_url, headers):
        try:
            with session.get(ts_url, headers=headers, verify=False, stream=True, timeout=5) as r:
                if r.status_code == 200:
                    data = r.content
                    with self.lock:
                        self.prefetch[ts_url] = {'data': data, 'ts': time.time()}
        except: pass

    def _worker(self, source, cid, result_box):
        try:
            url = f"{source}/play/{cid}/index.m3u8"
            h = get_headers(source)
            t0 = time.time()
            
            with session.get(url, headers=h, verify=False, timeout=(0.8, 2.0)) as r:
                if r.status_code == 200:
                    dt = (time.time() - t0) * 1000
                    self.scores[source] = (self.scores[source] * 0.7) + (dt * 0.3)
                    
                    if not result_box.ready():
                        result_box.set({
                            'source': source,
                            'content': r.content, 
                            'base': r.url.rsplit('/', 1)[0],
                            'headers': h
                        })
                else:
                    self.scores[source] += 5000
        except:
            self.scores[source] += 10000

    def resolve_playlist(self, cid):
        now = time.time()
        # ID temizliği (Her ihtimale karşı)
        cid = cid.replace('.m3u8', '')

        if cid in self.cache:
            entry = self.cache[cid]
            if now < entry['expires']: return entry['data']

        sorted_src = sorted(SOURCES, key=lambda s: self.scores[s])
        candidates = sorted_src[:2]
        
        result_box = event.AsyncResult()
        pool_ = pool.Pool(2)
        for src in candidates:
            pool_.spawn(self._worker, src, cid, result_box)
        
        try:
            winner = result_box.get(timeout=2.5)
            pool_.kill(block=False)
            
            if winner:
                self.cache[cid] = {'expires': now + 300, 'data': winner}
                try:
                    lines = winner['content'].split(B_NEWLINE)
                    first_ts = None
                    for line in lines:
                        if line and not line.startswith(b'#'):
                            if line.startswith(b'http'): first_ts = line.decode()
                            else: first_ts = f"{winner['base']}/{line.decode()}"
                            break
                    if first_ts:
                        spawn(self._speculative_loader, first_ts, winner['headers'])
                except: pass
                return winner
        except:
            pool_.kill(block=False)
        return None

brain = TachyonBrain()

# ------------------------------------------------------------------------------
# 4. ENDPOINTS (FIXED PARSING LOGIC)
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # Liste kaynağı bul
    best_src = min(SOURCES, key=lambda s: brain.scores[s])
    data = None
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=2)
        if r.status_code == 200: data = r.json()
    except: pass
    
    if not data:
        for src in SOURCES:
            if src == best_src: continue
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=2)
                if r.status_code == 200: 
                    data = r.json()
                    break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [B_EXTM3U]
    b_group = "Turkey"
    
    for item in data:
        if item.get("group") == b_group or item.get("group") == "Turkey":
            try:
                u = item['url']
                # === BURASI DÜZELTİLDİ ===
                # URL formatları değişken olabilir:
                # 1. .../play/12345/index.m3u8
                # 2. .../play/12345.m3u8
                
                # /play/'den sonrasını al
                part = u.split('/play/')[-1]
                
                cid = ""
                if '/' in part:
                    # Klasör yapısı ise (12345/index.m3u8) -> 12345 al
                    cid = part.split('/')[0]
                else:
                    # Dosya yapısı ise (12345.m3u8) -> uzantıyı temizle
                    cid = part.replace('.m3u8', '')
                
                # Ekstra güvenlik: Noktadan sonrasını at (eğer hala varsa)
                if '.' in cid: cid = cid.split('.')[0]
                
                if cid:
                    name = item['name'].replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    # Burada artık temiz cid kullanıyoruz, çift uzantı olmaz
                    out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    # Gelen istek: /live/12345.m3u8 -> cid = 12345
    # Flask <cid> kısmını alır, uzantı route'da tanımlı olduğu için gelmez.
    # Ancak eğer istek /live/12345.m3u8.m3u8 gelirse, Flask 12345.m3u8 olarak alır.
    # Bu yüzden burada da temizlik yapıyoruz.
    clean_cid = cid.replace('.m3u8', '')
    
    info = brain.resolve_playlist(clean_cid)
    if not info: return Response("Not Found", 404)

    base_b = info['base'].encode()
    host_b = request.host_url.rstrip('/').encode()
    cid_b = clean_cid.encode()
    
    out = [B_EXTM3U, b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    for line in info['content'].split(B_NEWLINE):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(B_EXTM3U) and not line.startswith(b"#EXT-X-TARGET"):
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
    
    # 1. TACHYON CHECK (RAM Hit)
    with brain.lock:
        if target in brain.prefetch:
            data = brain.prefetch.pop(target)['data']
            return Response(data, content_type="video/mp2t")

    # 2. CACHE MISS
    try:
        slash3 = target.find('/', 8)
        origin = target[:slash3]
    except: origin = "https://vavoo.to"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"{origin}/",
        "Origin": origin,
        "Connection": "keep-alive"
    }

    def stream_direct():
        try:
            with session.get(target, headers=headers, verify=False, stream=True, timeout=10) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=131072):
                        yield chunk
                    return

            if cid:
                clean_cid = cid.replace('.m3u8', '')
                if clean_cid in brain.cache: del brain.cache[clean_cid]
                info = brain.resolve_playlist(clean_cid)
                if info:
                    fname = target.rsplit('/', 1)[-1].split('?')[0]
                    new_target = f"{info['base']}/{fname}"
                    with session.get(new_target, headers=info['headers'], verify=False, stream=True, timeout=8) as r2:
                        if r2.status_code == 200:
                            for chunk in r2.iter_content(chunk_size=131072):
                                yield chunk
        except: pass

    return Response(stream_with_context(stream_direct()), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO TACHYON V2 (BUGFIXED)")
    print(f" ► LISTENING: 8080")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
