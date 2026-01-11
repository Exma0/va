# =====================================================
# GEVENT YAMASI (EN ÜSTTE)
# =====================================================
from gevent import monkey
monkey.patch_all()

import re
import requests
import sys
import time
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote

app = Flask(__name__)

# =====================================================
# AYARLAR
# =====================================================
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

# Ortak Headerlar (Referer ŞARTTIR)
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
# ROTA 1: KANAL LİSTESİ
# =====================================================
@app.route('/')
def root():
    try:
        # Liste için tek kullanımlık istek atıyoruz (Session yok)
        r = requests.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=15)
        data = r.text
    except Exception as e:
        return f"Liste Hatasi: {str(e)}", 500

    base_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # Kanal ismini ve ID'yi al
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            # Linki bizim proxy'ye yönlendir
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_url}/playlist/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

# =====================================================
# ROTA 2: M3U8 OLUŞTURUCU (AKILLI PROXY)
# =====================================================
@app.route('/playlist/<cid>.m3u8')
def playlist_proxy(cid):
    vavoo_url = f"https://vavoo.to/play/{cid}/index.m3u8"
    
    try:
        # 1. M3U8'i çek (Redirectleri takip et)
        r = requests.get(vavoo_url, headers=HEADERS, verify=False, timeout=10, allow_redirects=True)
        if r.status_code != 200: return Response("Yayin Kapali", status=404)
        
        final_url = r.url # Yönlendirme varsa son adresi al
        content = r.text
        
        # 2. Master Playlist Kontrolü (Kalite Seçimi)
        if "#EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            for line in reversed(lines):
                if line and not line.startswith("#"):
                    final_url = urljoin(final_url, line)
                    # Gerçek yayına git
                    r = requests.get(final_url, headers=HEADERS, verify=False, timeout=10)
                    content = r.text
                    break

        base_ts_url = final_url.rsplit('/', 1)[0] + '/'
        new_lines = []
        
        # 3. Satırları işle ve Proxy linkine çevir
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
                # Donma önleyici buffer (15 sn)
                if "#EXT-X-TARGETDURATION" in line:
                    new_lines.append("#EXT-X-START:TIME-OFFSET=-15")
            else:
                # Segment URL'sini tam hale getir
                full_ts_url = urljoin(base_ts_url, line)
                
                # URL'yi güvenli şekilde paketle (Quote)
                # Buradaki quote işlemi linkin bozulmasını engeller
                encoded_url = quote(full_ts_url)
                
                # Proxy linkini oluştur
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?url={encoded_url}")
        
        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception as e:
        print(f"Playlist Error: {e}", file=sys.stderr)
        return Response("Server Error", status=500)

# =====================================================
# ROTA 3: SEGMENT PROXY (GLOBAL SESSION YOK!)
# =====================================================
@app.route('/seg')
def segment_proxy():
    # URL'yi paketten çıkar
    target_url = unquote(request.args.get('url'))
    if not target_url: return "No URL", 400

    def generate():
        try:
            # KRİTİK NOKTA: Burada global 'session' YERİNE
            # 'requests.get' kullanıyoruz. Bu her parça için taze bir
            # bağlantı açar. Thread çakışmasını engeller.
            
            # Timeout değerini artırdık (Vavoo bazen geç yanıt verir)
            with requests.get(
                target_url, 
                headers=HEADERS, 
                verify=False, 
                stream=True, 
                timeout=20 
            ) as r:
                
                # Eğer Vavoo hata verirse (403/404), biz de hata verelim ki
                # VLC "0 byte" indirmesin, tekrar denesin.
                if r.status_code != 200:
                    # Loglara hata bas
                    print(f"TS Error {r.status_code}: {target_url}", file=sys.stderr)
                    return 

                # Veriyi 64KB'lık paketlerle aktar
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk: yield chunk
                    
        except Exception as e:
            # Bağlantı koptuysa sessizce çık
            return

    # Direct passthrough headers
    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
