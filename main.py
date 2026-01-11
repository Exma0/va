# =====================================================
# GEVENT YAMASI (Çoklu Bağlantı İçin Şart)
# =====================================================
from gevent import monkey
monkey.patch_all()

import re
import requests
import time
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote

app = Flask(__name__)

# =====================================================
# AYARLAR
# =====================================================
# Vavoo'nun en sevdiği User-Agent
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive",
    "Accept": "*/*"
}

requests.packages.urllib3.disable_warnings()

# Bağlantı Havuzu (VLC aynı anda 5 parça isteyeceği için sayıyı artırdık)
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=200, 
    pool_maxsize=200, 
    max_retries=3
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# =====================================================
# ROTA 1: KANAL LİSTESİ
# =====================================================
@app.route('/')
def root():
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=10)
        data = r.text
    except:
        return "Vavoo Error", 500

    base_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # Hızlı Regex
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        # Linkin içinden ID'yi alıyoruz
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            # Linki /playlist/ID.m3u8 formatına çeviriyoruz
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_url}/playlist/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

# =====================================================
# ROTA 2: M3U8 DÜZENLEYİCİ (VLC'YE YOL GÖSTEREN)
# =====================================================
@app.route('/playlist/<cid>.m3u8')
def playlist_proxy(cid):
    vavoo_url = f"https://vavoo.to/play/{cid}/index.m3u8"
    
    try:
        # 1. Vavoo'dan asıl listeyi çek
        r = session.get(vavoo_url, headers=HEADERS, verify=False, timeout=6)
        content = r.text
        
        # 2. Eğer bu bir Master Playlist ise (Kalite seçenekleri varsa)
        if "#EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            # En iyi kaliteyi bul (Son satırlar genelde en iyisidir)
            for line in reversed(lines):
                if line and not line.startswith("#"):
                    # Gerçek yayın linkini bul ve tekrar bu fonksiyonu çağır
                    real_url = urljoin(vavoo_url, line)
                    # Buradan tekrar veriyi çekmek yerine direkt yönlendirme yapabilirdik 
                    # ama Vavoo linkleri değişebiliyor, o yüzden çekiyoruz.
                    r = session.get(real_url, headers=HEADERS, verify=False, timeout=6)
                    content = r.text
                    vavoo_url = real_url # Base URL'i güncelle
                    break

        base_ts_url = vavoo_url.rsplit('/', 1)[0] + '/'
        new_lines = []
        
        # 3. Satırları işle
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
                # VLC'nin hızlı açılması için buffer ayarı
                if "#EXT-X-TARGETDURATION" in line:
                    new_lines.append("#EXT-X-START:TIME-OFFSET=-15") 
            else:
                # TS linkini tam adres haline getir
                full_ts_url = urljoin(base_ts_url, line)
                # Bizim sunucu üzerinden geçmesi için şifrele
                # quote() kullanarak URL içindeki karakterlerin bozulmasını önlüyoruz
                proxy_line = f"{request.host_url.rstrip('/')}/seg?url={quote(full_ts_url)}"
                new_lines.append(proxy_line)
        
        return Response("\n".join(new_lines), content_type="application/x-mpegURL")

    except Exception as e:
        return str(e), 500

# =====================================================
# ROTA 3: SEGMENT PROXY (SADECE KÖPRÜ)
# =====================================================
@app.route('/seg')
def segment_proxy():
    # URL'yi çöz
    target_url = unquote(request.args.get('url'))
    
    if not target_url: return "No URL", 400

    def generate():
        try:
            # stream=True ile veriyi RAM'de tutmadan direkt VLC'ye akıt
            # timeout=10 yeterli, Vavoo vermezse VLC diğer parçaya geçer
            with session.get(target_url, headers=HEADERS, verify=False, stream=True, timeout=10) as r:
                # VLC 404 alırsa panik yapmaz, bir sonrakini dener.
                # O yüzden sadece 200 (OK) ise veri yolluyoruz.
                if r.status_code == 200:
                    # 32KB chunk ideal bir denge
                    for chunk in r.iter_content(chunk_size=32768):
                        if chunk: yield chunk
        except:
            pass

    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    # Threaded mod burada HAYATİ önem taşır çünkü VLC aynı anda 
    # hem m3u8 dosyasını hem de ts dosyasını ister.
    app.run(host="0.0.0.0", port=8080, threaded=True)
