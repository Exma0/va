# =====================================================
# GEVENT YAMASI (MUTLAKA EN ÜSTTE)
# =====================================================
from gevent import monkey
monkey.patch_all()

import re
import requests
import sys
import time
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# =====================================================
# AYARLAR
# =====================================================
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

requests.packages.urllib3.disable_warnings()

# =====================================================
# GELİŞMİŞ BAĞLANTI HAVUZU
# =====================================================
def get_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = HTTPAdapter(pool_connections=200, pool_maxsize=200, max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Global session yerine, her rota kendi taze session'ını kullanacak 
# ama adapter ayarları optimize edildi.

# =====================================================
# ROTA 1: KANAL LİSTESİ
# =====================================================
@app.route('/')
def root():
    session = get_session()
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=15)
        r.raise_for_status()
        data = r.text
    except Exception as e:
        return f"Liste Hatasi: {str(e)}", 500

    base_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # Hızlı Regex
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            # TiviMate için .m3u8 uzantısı önemlidir
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_url}/playlist/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

# =====================================================
# ROTA 2: M3U8 PROXY
# =====================================================
@app.route('/playlist/<cid>.m3u8')
def playlist_proxy(cid):
    vavoo_url = f"https://vavoo.to/play/{cid}/index.m3u8"
    session = get_session()

    try:
        # Vavoo'ya git
        r = session.get(vavoo_url, headers=HEADERS, verify=False, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return Response("Yayin Yok", status=404)
        
        content = r.text
        final_url = r.url # Yönlendirme olduysa son adresi al

        # Master Playlist Kontrolü
        if "#EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            for line in reversed(lines):
                if line and not line.startswith("#"):
                    final_url = urljoin(final_url, line)
                    r = session.get(final_url, headers=HEADERS, verify=False, timeout=10)
                    content = r.text
                    break
        
        base_ts = final_url.rsplit('/', 1)[0] + '/'
        new_lines = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                # TS linkini oluştur
                full_ts_url = urljoin(base_ts, line)
                # Linki şifrele (Encode)
                encoded_url = quote(full_ts_url)
                # Proxy linkini yaz
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?url={encoded_url}")

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception as e:
        print(f"Playlist Error: {e}", file=sys.stderr)
        return Response("Server Error", status=500)

# =====================================================
# ROTA 3: SEGMENT PROXY (0 BYTE FIX)
# =====================================================
@app.route('/seg')
def segment_proxy():
    target_url = unquote(request.args.get('url'))
    if not target_url: return "No URL", 400

    # 1. Önce Bağlantıyı Kur (Veri akışı başlamadan yanıt dönme!)
    session = get_session()
    try:
        # stream=True ile isteği başlatıyoruz ama içeriği henüz okumuyoruz
        upstream_req = session.get(
            target_url, 
            headers=HEADERS, 
            verify=False, 
            stream=True, 
            timeout=(5, 30), # (Connect, Read)
            allow_redirects=True
        )
        
        # 2. Vavoo hata verdiyse BİZ DE HATA VERELİM (200 OK Dönme!)
        if upstream_req.status_code != 200:
            upstream_req.close()
            return Response(f"Upstream Error {upstream_req.status_code}", status=upstream_req.status_code)
        
        # 3. İçerik uzunluğu 0 ise veya boşsa hata ver
        # (Content-Length her zaman gelmeyebilir ama kontrol etmek iyidir)
        if upstream_req.headers.get('Content-Length') == '0':
             upstream_req.close()
             return Response("Empty Stream", status=502)

        # 4. Her şey yolundaysa Jeneratörü Başlat
        def generate():
            try:
                for chunk in upstream_req.iter_content(chunk_size=65536):
                    if chunk: yield chunk
            except Exception as e:
                print(f"Stream Cut: {e}", file=sys.stderr)
            finally:
                upstream_req.close()

        # Flask'a yanıtı şimdi gönderiyoruz
        return Response(
            stream_with_context(generate()), 
            content_type="video/mp2t",
            status=200
        )

    except Exception as e:
        print(f"Proxy Connection Error: {e}", file=sys.stderr)
        return Response("Connection Failed", status=502)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
