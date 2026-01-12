# ==============================================================================
# VAVOO SINGULARITY - VOID WALKER EDITION
# Fix: 0-Byte 200 OK Loop | Tech: Content Validation | Instant Source Banning
# Status: UNSTOPPABLE
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
from urllib.parse import quote, unquote

# ------------------------------------------------------------------------------
# 1. SYSTEM TUNING
# ------------------------------------------------------------------------------
sys.setswitchinterval(0.001)
gc.set_threshold(100000, 50, 50)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# CRITICAL: Any segment smaller than 1KB is considered "Corrupted/Empty"
MIN_VALID_SIZE = 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Silence all logs
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
# 3. SINGULARITY CORE (WITH VOID FILTER)
# ------------------------------------------------------------------------------
class SingularityCore:
    def __init__(self):
        self.health = {src: 100.0 for src in SOURCES}
        self.playlist_store = {} 
        self.lock = lock.RLock()
        # Separate lock for health updates to avoid congestion
        self.health_lock = lock.RLock()
        spawn(self._optimizer)

    def _optimizer(self):
        while True:
            sleep(5)
            with self.health_lock:
                # Slowly forgive bad sources
                for src in self.health:
                    if self.health[src] < 100: self.health[src] += 10

    def punish(self, source, amount=50):
        """Heavy punishment for 0-byte offenders"""
        with self.health_lock:
            self.health[source] -= amount

    def get_top_sources(self):
        """Get best sources, sorted by health."""
        with self.health_lock:
            return sorted(SOURCES, key=lambda s: self.health[s], reverse=True)

    def _fetch_blob_validated(self, url, source):
        """Fetches data AND validates size."""
        try:
            h = get_headers(source)
            with session.get(url, headers=h, verify=False, timeout=(2, 4)) as r:
                if r.status_code == 200:
                    data = r.content
                    # THE VOID FILTER: Reject empty/small responses
                    if len(data) > MIN_VALID_SIZE:
                        return data
                    else:
                        self.punish(source, 100) # Instant Ban for 0-byte
                else:
                    self.punish(source, 20)
        except:
            self.punish(source, 20)
        return None

    def resolve_playlist(self, cid):
        now = time.time()
        cid = cid.split('.')[0] # Clean ID

        if cid in self.playlist_store:
            entry = self.playlist_store[cid]
            if now < entry['expires']: return entry['data']

        # Try sources in order of health
        candidates = self.get_top_sources()
        
        for src in candidates:
            url = f"{src}/play/{cid}/index.m3u8"
            data = self._fetch_blob_validated(url, src)
            if data:
                # Success
                result = {
                    'content': data,
                    'base': f"{src}/play/{cid}",
                    'source': src
                }
                self.playlist_store[cid] = {'expires': now + 300, 'data': result}
                return result
        
        return None

singularity = SingularityCore()

# ------------------------------------------------------------------------------
# 4. FAILOVER STREAMING ENGINE
# ------------------------------------------------------------------------------
def failover_streamer(target_path_suffix, cid):
    """
    Attempts to download the segment from sources in priority order.
    If Source A returns 0 bytes, it IMMEDIATELY tries Source B.
    """
    # 1. Get ordered list of healthy sources
    sources = singularity.get_top_sources()
    
    # We strip the query string if present to get clean filename
    filename = target_path_suffix.split('?')[0]
    
    # Track if we found ANY valid data
    success = False

    for src in sources:
        # Construct URL for this specific source
        # Structure: https://huhu.to/play/{cid}/{seg-X.ts}
        real_url = f"{src}/play/{cid}/{filename}"
        
        try:
            h = get_headers(src)
            # Stream=True for memory efficiency
            with session.get(real_url, headers=h, verify=False, stream=True, timeout=(2, 5)) as r:
                if r.status_code == 200:
                    # PEEK at the first chunk to validate size/existence
                    first_chunk = next(r.iter_content(chunk_size=4096), None)
                    
                    if first_chunk and len(first_chunk) > 0:
                        # VALID DATA FOUND!
                        success = True
                        yield first_chunk # Yield the first byte immediately
                        
                        # Stream the rest
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk: yield chunk
                        
                        # If we successfully streamed, stop trying other sources
                        return 
                    else:
                        # 0-Byte or Empty Response -> PUNISH & NEXT
                        singularity.punish(src, 100)
                        # Loop continues to next source...
                else:
                    singularity.punish(src, 20)
        except Exception:
            singularity.punish(src, 20)
            # Loop continues to next source...

    if not success:
        # If we reach here, ALL sources failed.
        # Yield nothing, let connection close.
        pass

# ------------------------------------------------------------------------------
# 5. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # Fetch list from best source
    sources = singularity.get_top_sources()
    data = None
    
    for src in sources:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=3)
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
                # Parsing Logic
                if '/play/' in u:
                    rest = u.split('/play/')[-1]
                    if '/' in rest: cid = rest.split('/')[0]
                    else: cid = rest.split('.')[0]
                    
                    if cid.isdigit(): 
                        name = item['name'].replace(',', ' ')
                        out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                        out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    clean_cid = cid.split('.')[0]
    info = singularity.resolve_playlist(clean_cid)
    
    if not info: return Response("Not Found", 404)

    # Reconstruct Playlist
    # We ignore the 'base' from info because we want to force our /ts endpoint
    # to handle failover dynamically for every segment.
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
            # This is the segment filename (e.g., seg-123.ts)
            # We extract just the filename
            line_str = line.decode()
            if line_str.startswith('http'):
                filename = line_str.split('/')[-1]
            else:
                filename = line_str
            
            # We encode the filename as 'url' parameter, but treat it as a relative path suffix
            safe_target = quote(filename).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    # Logic Change: 'url' parameter is now treated as the FILENAME (suffix)
    # The brain decides which source base URL to prepend.
    url_param = request.args.get('url')
    cid = request.args.get('cid')
    
    if not url_param or not cid: return "Bad", 400
    
    filename = unquote(url_param)
    
    # Use the Failover Streamer
    # This function loops through sources until it finds NON-ZERO bytes.
    return Response(stream_with_context(failover_streamer(filename, cid)), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO VOID WALKER (FINAL FIX)")
    print(f" ► LOGIC: 0-BYTE REJECTION & INSTANT FAILOVER")
    print(f" ► LISTENING: 8080")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
