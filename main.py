# =====================================================
# GEVENT YAMASI (EN ÜSTTE OLMALI)
# =====================================================
from gevent import monkey
monkey.patch_all()

import re
import requests
import time
import sys
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote

app = Flask(__name__)

# =====================================================
# AYARLAR
# =====================================================
# VLC'nin kendi User-Agent'ını kullanmak bazen Vavoo'yu şaşırtır, 
# ama Chrome taklidi yapmak en garantisidir.
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}

requests.packages.urllib3.disable_warnings()

# Bağlantı Havuzu
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=100, 
    pool_maxsize=100, 
    max_retries=3
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# =====================================================
# ROTA 1: ANA LİSTE
# =====================================================
@app.route('/')
def root():
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=15)
        r.raise_for_status() # Hata varsa dur
        data = r.text
    except Exception as e:
        print(f"Vavoo Liste Hatası: {e}", file=sys.stderr)
        return "Kaynak Hatasi", 502

    base_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # Kanal Listesi Regex
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_url}/playlist/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

# =====================================================
# ROTA 2: PLAYLIST DÜZENLEYİCİ
# =====================================================
@app.route('/playlist/<cid>.m3u8')
def playlist_proxy(cid):
    vavoo_url = f"https://vavoo.to/play/{cid}/index.m3u8"
    
    try:
        # Vavoo'dan listeyi çek
        r = session.get(vavoo_url, headers=HEADERS, verify=False, timeout=8)
        if r.status_code != 200:
            print(f"Playlist Hatası {r.status_code}: {cid}", file=sys.stderr)
            return Response("Yayin Yok", status=404)
            
        content = r.text
        
        # Master Playlist ise en iyi kaliteyi bul
        if "#EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            for line in reversed(lines):
                if line and not line.startswith("#"):
                    real_url = urljoin(vavoo_url, line)
                    # Gerçek yayına git
                    r = session.get(real_url, headers=HEADERS, verify=False, timeout=8)
                    content = r.text
                    vavoo_url = real_url
                    break

        base_ts_url = vavoo_url.rsplit('/', 1)[0] + '/'
        new_lines = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                # Segment URL'sini hazırla
                full_ts_url = urljoin(base_ts_url, line)
                # URL'yi güvenli hale getir (Encoded)
                safe_url = quote(full_ts_url)
                # Proxy linkini oluştur
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?url={safe_url}")
        
        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception as e:
        print(f"Playlist Exception: {e}", file=sys.stderr)
        return Response("Server Error", status=500)

# =====================================================
# ROTA 3: SEGMENT PROXY (HATA YUTMAZ)
# =====================================================
@app.route('/seg')
def segment_proxy():
    target_url = unquote(request.args.get('url'))
    if not target_url: return "No URL", 400

    def generate():
        try:
            # stream=True ile açıyoruz
            with session.get(target_url, headers=HEADERS, verify=False, stream=True, timeout=15) as r:
                
                # ÖNEMLİ: Vavoo 200 vermezse (403, 404, 500), biz de hata dönelim.
                # Böylece VLC "0 byte" almaz, hata alır ve tekrar dener.
                if r.status_code != 200:
                    print(f"Segment Hatası {r.status_code}: {target_url}", file=sys.stderr)
                    # Hata kodu göndererek VLC'ye "Bu parça bozuk, diğerine geç" diyoruz
                    return 

                # Veri akışı
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk: yield chunk
                    
        except Exception as e:
            # Bağlantı koparsa sessizce bitir, VLC anlar.
            print(f"Download Error: {e}", file=sys.stderr)
            return

    # Response içinde direct_passthrough kullanarak Flask'ın araya girmesini engelliyoruz
    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
