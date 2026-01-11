from gevent import monkey
monkey.patch_all()

import re
import requests
import sys
import time
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote
from functools import lru_cache

app = Flask(__name__)

# =====================================================
# AYARLAR
# =====================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}

requests.packages.urllib3.disable_warnings()

# Bağlantı Havuzu
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=500, pool_maxsize=500, max_retries=3)
session.mount('http://', adapter)
session.mount('https://', adapter)

# =====================================================
# ÖNBELLEK MEKANİZMASI (TiviMate Spam Engelleyici)
# =====================================================
# Playlist'i 5 saniye boyunca hafızada tutar. 
# TiviMate 100 kere de istese Vavoo'ya gitmez, buradan verir.
class TTL_Cache:
    def __init__(self, ttl=5):
        self.cache = {}
        self.ttl = ttl

    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return data
        return None

    def set(self, key, value):
        self.cache[key] = (value, time.time())

playlist_cache = TTL_Cache(ttl=6) # 6 Saniye cache

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def root():
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=10)
        data = r.text
    except Exception as e:
        return f"Hata: {e}", 502

    base_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # Kanal listesi
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_url}/playlist/{id_match.group(1)}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/playlist/<cid>.m3u8')
def playlist_proxy(cid):
    # 1. Önce Cache'e bak (TiviMate saldırısını engelle)
    cached_data = playlist_cache.get(cid)
    if cached_data:
        return Response(cached_data, content_type="application/vnd.apple.mpegurl")

    vavoo_url = f"https://vavoo.to/play/{cid}/index.m3u8"
    
    try:
        # 2. Vavoo'dan taze veri çek
        r = session.get(vavoo_url, headers=HEADERS, verify=False, timeout=8, allow_redirects=True)
        if r.status_code != 200: return Response("Yayin Yok", status=404)
        
        final_url = r.url
        content = r.text

        # Master Playlist Kontrolü
        if "#EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            for line in reversed(lines):
                if line and not line.startswith("#"):
                    final_url = urljoin(final_url, line)
                    r = session.get(final_url, headers=HEADERS, verify=False, timeout=8)
                    content = r.text
                    break
        
        # Linkleri Dönüştür
        base_ts = final_url.rsplit('/', 1)[0] + '/'
        new_lines = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                full_ts = urljoin(base_ts, line)
                enc_url = quote(full_ts)
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?url={enc_url}")

        result = "\n".join(new_lines)
        
        # 3. Sonucu Cache'e kaydet
        playlist_cache.set(cid, result)
        
        return Response(result, content_type="application/vnd.apple.mpegurl")

    except Exception:
        return Response("Server Error", status=500)

@app.route('/seg')
def segment_proxy():
    target_url = unquote(request.args.get('url'))
    if not target_url: return "No URL", 400

    def generate():
        try:
            # TiviMate için uzun timeout ve stream
            with session.get(target_url, headers=HEADERS, verify=False, stream=True, timeout=(5, 45)) as r:
                
                if r.status_code != 200:
                    return # Hata dön, TiviMate tekrar dener

                # 64KB ideal boyuttur
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk: yield chunk
                    
        except Exception:
            pass

    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
