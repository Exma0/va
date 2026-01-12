# ==============================================================================
# VAVOO SINGULARITY: OMEGA (PRODUCTION READY)
# Tüm kritik hatalar düzeltildi:
# - Thread-safe session yönetimi
# - Memory leak tamamen giderildi
# - Race condition çözüldü
# - Key encryption tam destek
# - Timeout optimizasyonları
# - Channel map temizleme
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
from gevent.lock import BoundedSemaphore
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote, urljoin, urlparse

# ------------------------------------------------------------------------------
# KERNEL & PERFORMANCE TUNING
# ------------------------------------------------------------------------------
sys.setswitchinterval(0.001)
gc.set_threshold(700, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

MIN_TS_SIZE = 1024
MAX_HEADER_CACHE = 100
MAX_CHANNEL_CACHE = 500

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
    
    def delete(self, key):
        with self.lock:
            if key in self.cache:
                del self.cache[key]
    
    def clear_expired(self, check_func):
        """Expire olmuş entry'leri temizle"""
        with self.lock:
            expired = [k for k, v in self.cache.items() if not check_func(v)]
            for k in expired:
                del self.cache[k]
            return len(expired)

HEADERS_CACHE = LRUCache(MAX_HEADER_CACHE)

# ------------------------------------------------------------------------------
# THREAD-SAFE NETWORK STACK
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=50,
    pool_maxsize=200,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Thread-safe session semaphore
SESSION_LOCK = BoundedSemaphore(200)

def safe_request(url, **kwargs):
    """Thread-safe HTTP request"""
    with SESSION_LOCK:
        return session.get(url, **kwargs)

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
# OMEGA BRAIN (IMPROVED)
# ------------------------------------------------------------------------------
class OmegaBrain:
    def __init__(self):
        self.health = {src: 100.0 for src in SOURCES}
        self.channel_map = LRUCache(MAX_CHANNEL_CACHE)
        self.lock = lock.RLock()
        spawn(self._auto_healer)
        spawn(self._cache_cleaner)

    def _auto_healer(self):
        """Kaynak sağlığını otomatik iyileştir"""
        while True:
            sleep(10)
            with self.lock:
                for src in self.health:
                    if self.health[src] < 100:
                        self.health[src] = min(100, self.health[src] + 5)

    def _cache_cleaner(self):
        """Expire olmuş cache'leri temizle"""
        while True:
            sleep(60)
            now = time.time()
            cleaned = self.channel_map.clear_expired(lambda v: now < v.get('expires', 0))
            if DEBUG_MODE and cleaned > 0:
                print(f"[CACHE CLEAN] {cleaned} expired entries removed")

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
        
        # Cache kontrol
        cached = self.channel_map.get(cid)
        if cached and now < cached.get('expires', 0):
            return cached

        candidates = self.get_best_sources()
        
        for src in candidates:
            try:
                initial_url = f"{src}/play/{cid}/index.m3u8"
                h = get_headers(initial_url)
                
                r = safe_request(initial_url, headers=h, verify=False, timeout=5, allow_redirects=True)
                
                if r.status_code == 200:
                    if b"#EXTM3U" in r.content:
                        final_url = r.url
                        result = {
                            'final_url': final_url,
                            'source_root': src,
                            'content': r.content,
                            'expires': now + 300
                        }
                        self.channel_map.put(cid, result)
                        return result
                    else:
                        self.punish(src, 10)
                else:
                    self.punish(src, 5)
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[RESOLVE ERROR] {src}: {e}")
                self.punish(src, 5)
        
        return None
    
    def invalidate_channel(self, cid):
        """Kanal cache'ini geçersiz kıl"""
        self.channel_map.delete(cid)

omega = OmegaBrain()

# ------------------------------------------------------------------------------
# RAID-1 DOWNLOADER (FULLY FIXED)
# ------------------------------------------------------------------------------
def raid_downloader(target_filename, cid):
    sources = omega.get_best_sources()[:2]
    result_queue = queue.Queue()
    stop_event = event.Event()
    workers = []
    all_responses = []
    response_lock = lock.RLock()

    def worker(src):
        r = None
        try:
            if stop_event.is_set(): 
                return
            
            real_url = f"{src}/play/{cid}/{target_filename}"
            h = get_headers(real_url)
            
            r = safe_request(real_url, headers=h, verify=False, stream=True, timeout=(5, 30))
            
            # Response'u track et
            with response_lock:
                all_responses.append(r)
            
            if r.status_code == 200:
                first_chunk = next(r.iter_content(chunk_size=4096), None)
                
                if first_chunk and len(first_chunk) >= MIN_TS_SIZE:
                    # Race condition önleme - atomic check
                    if not stop_event.is_set():
                        try:
                            result_queue.put_nowait((first_chunk, r, src))
                            stop_event.set()
                            return
                        except queue.Full:
                            # Başka worker kazandı
                            pass
                else:
                    if DEBUG_MODE: 
                        print(f"[ZOMBIE] {src} empty chunk")
                    omega.punish(src, 50)
            else:
                omega.punish(src, 10)
                
        except Exception as e:
            if DEBUG_MODE: 
                print(f"[WORKER ERROR] {src}: {e}")
            omega.punish(src, 10)

    for s in sources:
        workers.append(spawn(worker, s))

    winning_response = None
    
    try:
        first_chunk, r_stream, winning_src = result_queue.get(timeout=8)
        winning_response = r_stream
        
        if DEBUG_MODE: 
            print(f"[RAID WIN] {winning_src}")
        
        # Kazanmayan tüm response'ları hemen kapat
        with response_lock:
            for resp in all_responses:
                if resp != r_stream:
                    try:
                        resp.close()
                    except:
                        pass
        
        yield first_chunk
        
        # Stream devam
        try:
            for chunk in r_stream.iter_content(chunk_size=65536):
                if chunk: 
                    yield chunk
        except Exception as e:
            if DEBUG_MODE: 
                print(f"[STREAM ERROR] {e}")
            # Client'a hata iletilebilir ama generator'da exception raise etmek
            # bağlantıyı keser, bu istenebilir
            raise
        
    except queue.Empty:
        if DEBUG_MODE: 
            print(f"[FALLBACK] {target_filename}")
        
        # Cache'i temizle ve yeniden dene
        omega.invalidate_channel(cid)
        
        info = omega.resolve_stream(cid)
        if info:
            # urljoin kullanarak güvenli URL oluştur
            fallback_url = urljoin(info['final_url'], target_filename)
            
            try:
                h = get_headers(fallback_url)
                r = safe_request(fallback_url, headers=h, verify=False, stream=True, timeout=10)
                
                with response_lock:
                    all_responses.append(r)
                
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: 
                            yield chunk
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[FALLBACK ERROR] {e}")
    
    finally:
        # Tüm response'ları garantili temizle
        with response_lock:
            for resp in all_responses:
                try:
                    resp.close()
                except:
                    pass
        
        # Tüm worker'ları öldür
        killall(workers, block=False, timeout=1)

# ------------------------------------------------------------------------------
# ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    best = omega.get_best_sources()[0]
    data = None
    
    try:
        r = safe_request(f"{best}/live2/index", verify=False, timeout=4)
        if r.status_code == 200: 
            data = r.json()
    except: 
        pass
    
    if not data:
        for s in SOURCES:
            if s == best: 
                continue
            try:
                r = safe_request(f"{s}/live2/index", verify=False, timeout=3)
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
            # EXT-X-KEY şifreleme desteği (TAM DÜZELTME)
            if b"EXT-X-KEY" in line:
                key_line = line.decode('utf-8', errors='ignore')
                if 'URI="' in key_line:
                    uri_match = re.search(r'URI="([^"]+)"', key_line)
                    if uri_match:
                        key_url = uri_match.group(1)
                        
                        # Absolute veya relative URL kontrolü
                        if key_url.startswith('http'):
                            # Absolute URL - sadece filename al
                            key_filename = key_url.split('/')[-1].split('?')[0]
                        else:
                            # Relative URL - olduğu gibi kullan
                            key_filename = key_url.split('?')[0]
                        
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
            
            # Absolute veya relative URL kontrolü
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

@app.route('/key')
def key_handler():
    """Şifreleme anahtarı proxy (TAM DÜZELTME)"""
    filename_enc = request.args.get('url')
    cid = request.args.get('cid')
    
    if not filename_enc or not cid: 
        return Response("Bad Request", 400)
    
    filename = unquote(filename_enc)
    
    info = omega.resolve_stream(cid)
    if not info: 
        return Response("Not Found", 404)
    
    # urljoin ile güvenli URL oluştur (relative/absolute URL desteği)
    key_url = urljoin(info['final_url'], filename)
    
    try:
        h = get_headers(key_url)
        r = safe_request(key_url, headers=h, verify=False, timeout=5)
        
        if r.status_code == 200:
            return Response(r.content, content_type="application/octet-stream")
        else:
            if DEBUG_MODE:
                print(f"[KEY ERROR] Status {r.status_code}: {key_url}")
            return Response("Key Not Found", 404)
            
    except Exception as e:
        if DEBUG_MODE: 
            print(f"[KEY ERROR] {e}")
        return Response("Key Error", 500)

# ------------------------------------------------------------------------------
# HEALTH CHECK
# ------------------------------------------------------------------------------
@app.route('/health')
def health_check():
    """Sistem sağlık kontrolü"""
    status = {
        'status': 'ok',
        'sources': {src: omega.health[src] for src in SOURCES},
        'cache_size': len(omega.channel_map.cache)
    }
    return Response(str(status), content_type="text/plain")

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
    print(" ► VAVOO SINGULARITY: OMEGA (PRODUCTION READY)")
    print(" ► FIXES:")
    print("   • Thread-safe session management")
    print("   • Memory leak fully resolved")
    print("   • Race condition eliminated")
    print("   • KEY encryption full support")
    print("   • Timeout optimizations")
    print("   • Cache auto-cleanup")
    print(" ► LISTENING: 0.0.0.0:8080")
    print("=" * 70)
    
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Graceful exit")
