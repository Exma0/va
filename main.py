# ==============================================================================
# VAVOO PROXY - LAZARUS EDITION (V5)
# Fix: M3U8 File Size Rejection | Status: RESURRECTED
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
# 1. AYARLAR
# ------------------------------------------------------------------------------
sys.setswitchinterval(0.001)
gc.set_threshold(100000, 50, 50)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# Video (TS) dosyaları için minimum boyut (1KB)
MIN_TS_SIZE = 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Logları temizle
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
    max_retries=1, # Ufak network hataları için 1 retry hakkı verelim
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
# 3. SINGULARITY CORE (LAZARUS UPDATE)
# ------------------------------------------------------------------------------
class SingularityCore:
    def __init__(self):
        self.health = {src: 100.0 for src in SOURCES}
        self.playlist_store = {} 
        self.lock = lock.RLock()
        self.health_lock = lock.RLock()
        spawn(self._optimizer)

    def _optimizer(self):
        while True:
            sleep(5)
            with self.health_lock:
                # Zamanla kaynakları affet
                for src in self.health:
                    if self.health[src] < 100: self.health[src] += 10

    def punish(self, source, amount=20):
        with self.health_lock:
            self.health[source] -= amount

    def get_top_sources(self):
        with self.health_lock:
            # Sağlık puanına göre sırala ama hepsi çok kötüyse (negatifse) bile dene
            return sorted(SOURCES, key=lambda s: self.health[s], reverse=True)

    def _fetch_playlist_validated(self, url, source):
        """
        SADECE Playlist (.m3u8) için özel indirici.
        Boyut kontrolü YAPMAZ. İçerik kontrolü YAPAR.
        """
        try:
            h = get_headers(source)
            with session.get(url, headers=h, verify=False, timeout=(2, 5)) as r:
                if r.status_code == 200:
                    data = r.content
                    # M3U8 Validasyonu: İçinde #EXTM3U var mı?
                    if b"#EXTM3U" in data:
                        return data
                    else:
                        # İçerik çöp ise
                        self.punish(source, 10)
                else:
                    self.punish(source, 20)
        except:
            self.punish(source, 20)
        return None

    def resolve_playlist(self, cid):
        now = time.time()
        cid = cid.split('.')[0] 

        if cid in self.playlist_store:
            entry = self.playlist_store[cid]
            if now < entry['expires']: return entry['data']

        candidates = self.get_top_sources()
        
        # LAZARUS PROTOCOL: Kaynakları sırayla dene, pes etme.
        for src in candidates:
            url = f"{src}/play/{cid}/index.m3u8"
            data = self._fetch_playlist_validated(url, src)
            if data:
                # Başarılı
                result = {
                    'content': data,
                    'base': f"{src}/play/{cid}",
                    'source': src
                }
                # Playlistleri 5dk cachele
                self.playlist_store[cid] = {'expires': now + 300, 'data': result}
                return result
        
        return None

singularity = SingularityCore()

# ------------------------------------------------------------------------------
# 4. STREAMING ENGINE
# ------------------------------------------------------------------------------
def failover_streamer(target_path_suffix, cid):
    """
    Video segmentleri (.ts) için akıllı indirici.
    Burada 1KB kontrolü AKTİF.
    """
    sources = singularity.get_top_sources()
    filename = target_path_suffix.split('?')[0]
    success = False

    for src in sources:
        real_url = f"{src}/play/{cid}/{filename}"
        
        try:
            h = get_headers(src)
            with session.get(real_url, headers=h, verify=False, stream=True, timeout=(2, 6)) as r:
                if r.status_code == 200:
                    # İlk paketi kontrol et (0-Byte Koruması)
                    first_chunk = next(r.iter_content(chunk_size=4096), None)
                    
                    if first_chunk and len(first_chunk) > 0:
                        success = True
                        yield first_chunk
                        
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk: yield chunk
                        return 
                    else:
                        # 0 Byte geldi -> Kaynağı banla
                        singularity.punish(src, 100)
                else:
                    singularity.punish(src, 20)
        except Exception:
            singularity.punish(src, 20)

# ------------------------------------------------------------------------------
# 5. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
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
                # Gelişmiş Parsing
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
            line_str = line.decode()
            if line_str.startswith('http'):
                filename = line_str.split('/')[-1]
            else:
                filename = line_str
            
            safe_target = quote(filename).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_param = request.args.get('url')
    cid = request.args.get('cid')
    
    if not url_param or not cid: return "Bad", 400
    
    filename = unquote(url_param)
    return Response(stream_with_context(failover_streamer(filename, cid)), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO LAZARUS (V5)")
    print(f" ► FIX: Playlist Size Check Disabled")
    print(f" ► PROTECTION: 0-Byte TS Ban Active")
    print(f" ► LISTENING: 8080")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
