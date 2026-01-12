# ==============================================================================
# VAVOO SINGULARITY: OMEGA (CRITICAL FIXES APPLIED)
# Düzeltmeler:
# - EXT-X-KEY şifreleme desteği eklendi
# - Memory leak düzeltildi
# - Connection pool optimize edildi
# - Stream cleanup iyileştirildi
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import sys
import signal
import re
from collections import OrderedDict
from gevent import pool, event, spawn, sleep, lock, queue, killall
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote, urljoin, urlparse

# ------------------------------------------------------------------------------
# KERNEL & PERFORMANCE TUNING
# ------------------------------------------------------------------------------
sys.setswitchinterval(0.001)
gc.set_threshold(700, 10, 10)  # FIX: Daha dengeli GC

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

MIN_TS_SIZE = 1024
MAX_HEADER_CACHE = 100

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)

import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

DEBUG_MODE = False

# ------------------------------------------------------------------------------
# LRU CACHE
# ------------------------------------------------------------------------------
class LRUCache:
    def __init__(self, capacity):
        self.cache = OrderedDict()
        self.capacity = capacity
        self.lock = lock.RLock()
    
    def get(self, key):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None
    
    def put(self, key, value):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

HEADERS_CACHE = LRUCache(MAX_HEADER_CACHE)

# ------------------------------------------------------------------------------
# NETWORK STACK (FIXED)
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=50,    # FIX: Daha güvenli limit
    pool_maxsize=200,       # FIX: 1000'den düşürüldü
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

def get_headers(target_url):
    try:
        parsed = urlparse(target_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        
        cached = HEADERS_CACHE.get(origin)
        if cached:
            return cached
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"{origin}/",
            "Origin": origin,
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip"
        }
        
        HEADERS_CACHE.put(origin, headers)
        return headers
    except Exception as e:
        if DEBUG_MODE:
            print(f"[HEADER ERROR] {e}")
        return {"User-Agent": "Mozilla/5.0", "Connection": "keep-alive"}

# ------------------------------------------------------------------------------
# OMEGA BRAIN
# ------------------------------------------------------------------------------
class OmegaBrain:
    def __init__(self):
        self.health = {src: 100.0 for src in SOURCES}
        self.channel_map = {}
        self.lock = lock.RLock()
        spawn(self._auto_healer)

    def _auto_healer(self):
        while True:
            sleep(10)
            with self.lock:
                for src in self.health:
                    if self.health[src] < 100:
                        self.health[src] = min(100, self.health[src] + 5)

    def punish(self, source, amount=20):
        with self.lock:
            self.health[source] = max(0, self.health[source] - amount)
            if DEBUG_MODE:
                print(f"[PUNISH] {source} -> {self.health[source]:.1f}")

    def get_best_sources(self):
        with self.lock:
            return sorted(SOURCES, key=lambda s: self.health[s], reverse=True)

    def resolve_stream(self, cid):
        now = time.time()
        
        with self.lock:
            if cid in self.channel_map:
                entry = self.channel_map[cid]
                if now < entry['expires']:
                    return entry
                else:
                    del self.channel_map[cid]

        candidates = self.get_best_sources()
        
        for src in candidates:
            try:
                initial_url = f"{src}/play/{cid}/index.m3u8"
                h = get_headers(initial_url)
                
                r = session.get(initial_url, headers=h, verify=False, timeout=5, allow_redirects=True)
                
                if r.status_code == 200:
                    if b"#EXTM3U" in r.content:
                        final_url = r.url
                        result = {
                            'final_url': final_url,
                            'source_root': src,
                            'content': r.content,
                            'expires': now + 300
                        }
                        with self.lock:
                            self.channel_map[cid] = result
                        return result
                    else:
                        self.punish(src, 10)
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[RESOLVE ERROR] {src}: {e}")
                self.punish(src, 5)
        
        return None

omega = OmegaBrain()

# ------------------------------------------------------------------------------
# RAID-1 DOWNLOADER (FIXED CLEANUP)
# ------------------------------------------------------------------------------
def raid_downloader(target_filename, cid):
    sources = omega.get_best_sources()[:2]
    result_queue = queue.Queue()
    stop_event = event.Event()
    workers = []
    active_stream = None

    def worker(src):
        r = None
        try:
            if stop_event.is_set(): 
                return
            
            real_url = f"{src}/play/{cid}/{target_filename}"
            h = get_headers(real_url)
            
            r = session.get(real_url, headers=h, verify=False, stream=True, timeout=(3, 8))
            
            if r.status_code == 200:
                first_chunk = next(r.iter_content(chunk_size=4096), None)
                
                if first_chunk and len(first_chunk) >= MIN_TS_SIZE:
                    if not stop_event.is_set():
                        result_queue.put((first_chunk, r, src))
                        stop_event.set()
                        return
                else:
                    if DEBUG_MODE: 
                        print(f"[ZOMBIE] {src} empty chunk")
                    omega.punish(src, 50)
                    r.close()
            else:
                omega.punish(src, 10)
                r.close()
        except Exception as e:
            if DEBUG_MODE: 
                print(f"[WORKER ERROR] {src}: {e}")
            omega.punish(src, 10)
            if r: 
                try: 
                    r.close() 
                except: 
                    pass

    for s in sources:
        workers.append(spawn(worker, s))

    try:
        first_chunk, r_stream, winning_src = result_queue.get(timeout=8)
        active_stream = r_stream
        
        if DEBUG_MODE: 
            print(f"[RAID WIN] {winning_src}")
        
        yield first_chunk
        
        try:
            for chunk in r_stream.iter_content(chunk_size=65536):
                if chunk: 
                    yield chunk
        except Exception as e:
            if DEBUG_MODE: 
                print(f"[STREAM ERROR] {e}")
        
    except queue.Empty:
        if DEBUG_MODE: 
            print(f"[FALLBACK] {target_filename}")
        
        with omega.lock:
            if cid in omega.channel_map: 
                del omega.channel_map[cid]
        
        info = omega.resolve_stream(cid)
        if info:
            base = info['final_url'].rsplit('/', 1)[0]
            fallback_url = f"{base}/{target_filename}"
            try:
                h = get_headers(fallback_url)
                with session.get(fallback_url, headers=h, verify=False, stream=True, timeout=10) as r:
                    if r.status_code == 200:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk: 
                                yield chunk
            except Exception:
                pass
    
    finally:
        # FIX: Tüm stream'leri ve worker'ları temizle
        if active_stream:
            try: 
                active_stream.close()
            except: 
                pass
        killall(workers, block=False, timeout=1)

# ------------------------------------------------------------------------------
# ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    best = omega.get_best_sources()[0]
    data = None
    
    try:
        r = session.get(f"{best}/live2/index", verify=False, timeout=4)
        if r.status_code == 200: 
            data = r.json()
    except: 
        pass
    
    if not data:
        for s in SOURCES:
            if s == best: 
                continue
            try:
                r = session.get(f"{s}/live2/index", verify=False, timeout=3)
                if r.status_code == 200: 
                    data = r.json()
                    break
            except: 
                continue

    if not data: 
        return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item.get('url', '')
                match = re.search(r'/play/(\d+)', u)
                
                if match:
                    part = match.group(1)
                    name = item.get('name', 'Unknown').replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    out.append(host_b + b'/live/' + part.encode() + b'.m3u8')
            except Exception:
                continue

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    clean_cid = cid.split('.')[0]
    info = omega.resolve_stream(clean_cid)
    
    if not info: 
        return Response("Not Found", 404)

    host_b = request.host_url.rstrip('/').encode()
    cid_b = clean_cid.encode()
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    for line in info['content'].split(b'\n'):
        line = line.strip()
        if not line: 
            continue
        
        if line.startswith(b'#'):
            # FIX: EXT-X-KEY şifreleme desteği
            if b"EXT-X-KEY" in line:
                key_line = line.decode('utf-8', errors='ignore')
                if 'URI="' in key_line:
                    uri_match = re.search(r'URI="([^"]+)"', key_line)
                    if uri_match:
                        key_url = uri_match.group(1)
                        key_filename = key_url.split('/')[-1].split('?')[0]
                        proxy_key_url = f'{request.host_url.rstrip("/")}/key?cid={clean_cid}&url={quote(key_filename)}'
                        key_line = re.sub(r'URI="[^"]+"', f'URI="{proxy_key_url}"', key_line)
                        out.append(key_line.encode())
                        continue
                out.append(line)
                continue
            
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            line_str = line.decode('utf-8', errors='ignore')
            
            if line_str.startswith('http'):
                filename = line_str.split('/')[-1]
            else:
                filename = line_str
            
            filename = filename.split('?')[0]
            safe_target = quote(filename).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    filename_enc = request.args.get('url')
    cid = request.args.get('cid')
    
    if not filename_enc or not cid: 
        return Response("Bad Request", 400)
    
    filename = unquote(filename_enc)
    return Response(
        stream_with_context(raid_downloader(filename, cid)), 
        content_type="video/mp2t"
    )

# FIX: Eksik KEY endpoint eklendi
@app.route('/key')
def key_handler():
    """Şifreleme anahtarı proxy"""
    filename_enc = request.args.get('url')
    cid = request.args.get('cid')
    
    if not filename_enc or not cid: 
        return Response("Bad Request", 400)
    
    filename = unquote(filename_enc)
    
    info = omega.resolve_stream(cid)
    if not info: 
        return Response("Not Found", 404)
    
    base = info['final_url'].rsplit('/', 1)[0]
    key_url = f"{base}/{filename}"
    
    try:
        h = get_headers(key_url)
        r = session.get(key_url, headers=h, verify=False, timeout=5)
        if r.status_code == 200:
            return Response(r.content, content_type="application/octet-stream")
    except Exception as e:
        if DEBUG_MODE: 
            print(f"[KEY ERROR] {e}")
    
    return Response("Key Not Found", 404)

# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------
def signal_handler(signum, frame):
    print(f"\n[SHUTDOWN] Signal {signum}")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    print("=" * 70)
    print(" ► VAVOO SINGULARITY: OMEGA (CRITICAL FIXES)")
    print(" ► FIXES: KEY Encryption | Memory Leak | Stream Cleanup")
    print(" ► LISTENING: 0.0.0.0:8080")
    print("=" * 70)
    
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
