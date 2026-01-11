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

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site"
}

requests.packages.urllib3.disable_warnings()

# =====================================================
# GELİŞMİŞ RETRY (YENİDEN DENEME) MEKANİZMASI
# =====================================================
def get_session():
    s = requests.Session()
    
    # Sunucu cevap vermezse 3 kere daha dene (Backoff ile)
    retry_strategy = Retry(
        total=3,
        backoff_factor=1, # 1s, 2s, 4s bekle
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=100,
        pool_maxsize=100
    )
    
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

# Global session yerine her işlemde taze session veya
# pool kullanan yapıya geçiyoruz.
global_session = get_session()

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def root():
    try:
        # Timeout artırıldı (Connect: 10s, Read: 30s)
        r = global_session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=(10, 30))
        r.raise_for_status()
        data = r.text
    except Exception as e:
        return f"Main List Error: {str(e)}", 500

    base_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_url}/playlist/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/playlist/<cid>.m3u8')
def playlist_proxy(cid):
    vavoo_url = f"https://vavoo.to/play/{cid}/index.m3u8"
    
    # 3 Kez Deneme Hakkı (Manuel Retry)
    for attempt in range(3):
        try:
            # Timeout (Connect: 5s, Read: 25s) -> Read timeout hatasını çözer
            r = global_session.get(vavoo_url, headers=HEADERS, verify=False, timeout=(5, 25))
            
            if r.status_code == 200:
                content = r.text
                if not content or len(content) < 10:
                    # Boş geldiyse hata fırlat ki retry devreye girsin
                    raise ValueError("Empty Response")
                
                # Master Playlist Kontrolü
                if "#EXT-X-STREAM-INF" in content:
                    lines = content.splitlines()
                    for line in reversed(lines):
                        if line and not line.startswith("#"):
                            vavoo_url = urljoin(vavoo_url, line) # URL güncelle
                            # Döngüyü kırmadan bir sonraki 'request' adımına geçmek için
                            # recursive yerine continue kullanıp request atacağız ama 
                            # basitlik için direkt çekelim:
                            r = global_session.get(vavoo_url, headers=HEADERS, verify=False, timeout=(5, 25))
                            content = r.text
                            break
                
                # Başarılı veri alındı, işle ve çık
                base_ts_url = vavoo_url.rsplit('/', 1)[0] + '/'
                new_lines = []
                
                for line in content.splitlines():
                    line = line.strip()
                    if not line: continue
                    
                    if line.startswith("#"):
                        new_lines.append(line)
                        if "#EXT-X-TARGETDURATION" in line:
                            new_lines.append("#EXT-X-START:TIME-OFFSET=-20")
                    else:
                        full_ts_url = urljoin(base_ts_url, line)
                        encoded_url = quote(full_ts_url)
                        new_lines.append(f"{request.host_url.rstrip('/')}/seg?url={encoded_url}")
                
                return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

        except Exception as e:
            # Hata varsa logla ve tekrar dene (continue)
            print(f"Playlist Retry {attempt+1}/3 ({cid}): {e}", file=sys.stderr)
            time.sleep(1) # Biraz bekle

    return Response("Stream Unavailable", status=503)

@app.route('/seg')
def segment_proxy():
    target_url = unquote(request.args.get('url'))
    if not target_url: return "No URL", 400

    def generate():
        try:
            # Segmentler için timeout (Connect: 5, Read: 30)
            # stream=True ile anlık akış
            with global_session.get(
                target_url, 
                headers=HEADERS, 
                verify=False, 
                stream=True, 
                timeout=(5, 30) 
            ) as r:
                
                if r.status_code != 200:
                    # VLC'ye hata dön (0 byte dönme!)
                    return 

                for chunk in r.iter_content(chunk_size=131072): # 128KB chunk
                    if chunk: yield chunk
                    
        except Exception as e:
            # Read timed out olursa burada yakalanır
            print(f"Seg Error: {e}", file=sys.stderr)
            return

    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
