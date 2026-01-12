# ==============================================================================
# VAVOO PROXY - TITANIUM EDITION (FULL COMPATIBLE)
# Architecture: Redirect Aware | Token Regenerator | Absolute/Relative Path Handler
# Status: FINAL STABLE
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
from urllib.parse import quote, unquote, urljoin, urlparse

# ------------------------------------------------------------------------------
# 1. SİSTEM AYARLARI
# ------------------------------------------------------------------------------
sys.setswitchinterval(0.001)
gc.set_threshold(100000, 50, 50)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# Video dosyası (TS) en az 1KB olmalı (Boş paket koruması)
MIN_TS_SIZE = 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Logları sustur
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK KATMANI
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=2000,
    pool_maxsize=10000,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Header Fabrikası (Dinamik Referer)
def get_headers(target_url):
    """
    Vavoo sunucuları Referer kontrolü yapar.
    İstek attığımız URL'in domaini neyse, Referer o olmalıdır.
    """
    parsed = urlparse(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"{origin}/",
        "Origin": origin,
        "Connection": "keep-alive"
    }

# ------------------------------------------------------------------------------
# 3. VAVOO CORE LOGIC
# ------------------------------------------------------------------------------
class VavooCore:
    def __init__(self):
        self.channel_cache = {} # {cid: {final_url, source, expires}}
        self.list_cache = None
        self.list_expires = 0
        self.lock = lock.RLock()

    def get_channel_list(self):
        """Kanal listesini çeker ve 10 dakika önbellekler."""
        now = time.time()
        if self.list_cache and now < self.list_expires:
            return self.list_cache

        # Kaynakları sırayla dene
        for src in SOURCES:
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=4)
                if r.status_code == 200:
                    data = r.json()
                    self.list_cache = data
                    self.list_expires = now + 600 # 10 dakika
                    return data
            except: continue
        return []

    def resolve_stream_url(self, cid):
        """
        Kanalın gerçek ve güncel (imzalı) URL'ini bulur.
        Redirectleri takip eder.
        """
        now = time.time()
        
        # Cache kontrolü
        if cid in self.channel_cache:
            entry = self.channel_cache[cid]
            if now < entry['expires']: return entry

        # Kaynakları tara
        for src in SOURCES:
            # Vavoo yapısı: /play/<id>/index.m3u8
            initial_url = f"{src}/play/{cid}/index.m3u8"
            
            try:
                # allow_redirects=True ÖNEMLİDİR.
                # Vavoo bizi huhu.to'dan -> cdn.server.com'a atar.
                h = get_headers(initial_url)
                r = session.get(initial_url, headers=h, verify=False, timeout=4, allow_redirects=True)
                
                if r.status_code == 200:
                    # Playlist Validasyonu
                    if b"#EXTM3U" not in r.content:
                        continue

                    final_url = r.url # Redirect sonrası son adres (Tokenlı)
                    
                    result = {
                        'final_url': final_url,
                        'source_root': src, # Orijinal kaynak
                        'content': r.content,
                        'expires': now + 300 # 5 dakika geçerli token
                    }
                    self.channel_cache[cid] = result
                    return result
            except: continue
        
        return None

vavoo = VavooCore()

# ------------------------------------------------------------------------------
# 4. STREAMING HANDLER (FAILOVER DESTEKLİ)
# ------------------------------------------------------------------------------
def stream_segment(target_url, cid):
    """
    TS dosyasını indirir. Hata olursa yeni token alır ve tekrar dener.
    """
    # 1. Deneme
    try:
        h = get_headers(target_url)
        with session.get(target_url, headers=h, verify=False, stream=True, timeout=(2, 6)) as r:
            if r.status_code == 200:
                # 0-Byte Kontrolü
                first_chunk = next(r.iter_content(chunk_size=4096), None)
                if first_chunk and len(first_chunk) > 0:
                    yield first_chunk
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: yield chunk
                    return # Başarılı çıkış

    except: pass

    # 2. Deneme (FALLBACK / RE-RESOLVE)
    # Eğer buraya geldiysek ya hata aldık ya da 0-byte geldi.
    # Token süresi dolmuş olabilir. Yeniden resolve et.
    if cid:
        # Cache'i sil
        if cid in vavoo.channel_cache: del vavoo.channel_cache[cid]
        
        # Yeni link bul
        info = vavoo.resolve_stream_url(cid)
        if info:
            # Yeni base URL'yi bul
            # target_url'den dosya ismini al: http://.../seg-50.ts -> seg-50.ts
            # Bazen query string olabilir: seg-50.ts?token=... -> split('?')
            filename = target_url.split('/')[-1].split('?')[0]
            
            # Yeni playlistin base URL'i
            new_base = info['final_url'].rsplit('/', 1)[0]
            
            # Yeni tam URL
            new_target_url = f"{new_base}/{filename}"
            
            # Son şans
            try:
                h = get_headers(new_target_url)
                with session.get(new_target_url, headers=h, verify=False, stream=True, timeout=5) as r2:
                    if r2.status_code == 200:
                         for chunk in r2.iter_content(chunk_size=65536):
                            yield chunk
            except: pass

# ------------------------------------------------------------------------------
# 5. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    data = vavoo.get_channel_list()
    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    for item in data:
        # Sadece Turkey grubu (İsteğe göre kaldırılabilir)
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # Vavoo URL Parse: .../play/<CID>/...
                # Örnekler:
                # http://huhu.to/play/12345/index.m3u8
                # http://vavoo.to/play/12345.m3u8
                
                cid = None
                if '/play/' in u:
                    part = u.split('/play/')[-1]
                    if '/' in part: cid = part.split('/')[0]
                    else: cid = part.replace('.m3u8', '')
                
                # CID Temizliği (Nokta vs kalmasın)
                if cid and '.' in cid: cid = cid.split('.')[0]

                if cid:
                    name = item['name'].replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    # Çift uzantı veya nokta temizliği
    cid = cid.split('.')[0]
    
    info = vavoo.resolve_stream_url(cid)
    if not info: return Response("Not Found", 404)

    # Base URL (Redirect sonrası oluşan gerçek adresin klasörü)
    # Örn: http://cdn5.huhu.to/hls/12345/index.m3u8 -> http://cdn5.huhu.to/hls/12345
    base_url = info['final_url'].rsplit('/', 1)[0]
    
    host_b = request.host_url.rstrip('/').encode()
    cid_b = cid.encode()
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    # M3U8 Satırlarını İşle
    lines = info['content'].split(b'\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue # Şifreli yayınları atla (Vavoo genelde şifresizdir ama önlem)
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            # Burası .ts linki
            line_str = line.decode()
            
            # Mutlak veya Göreli URL Birleştirme
            # urljoin hem "http://..." hem de "seg-1.ts" durumlarını doğru birleştirir.
            full_ts_url = urljoin(base_url + "/", line_str)
            
            # Proxy Linki Oluştur
            safe_target = quote(full_ts_url).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    # URL parametresi artık TAM URL (full_ts_url)
    url_param = request.args.get('url')
    cid = request.args.get('cid')
    
    if not url_param: return "Bad Request", 400
    
    target_url = unquote(url_param)
    
    # Yayını başlat
    return Response(stream_with_context(stream_segment(target_url, cid)), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO TITANIUM (FULL COMPATIBLE)")
    print(f" ► FEATURE: Auto-Redirect & Token Healing")
    print(f" ► LISTENING: 8080")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
