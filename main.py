# =====================================================
# KRİTİK: GEÇİKMEYİ SIFIRLAMAK İÇİN GEVENT YAMASI
# =====================================================
from gevent import monkey
monkey.patch_all()

import re
import requests
import time
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

# =====================================================
# AYARLAR (HIZ İÇİN MAXİMİZE EDİLDİ)
# =====================================================
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS_COMMON = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}

requests.packages.urllib3.disable_warnings()

# Bağlantı havuzunu daima sıcak tut
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=1000, 
    pool_maxsize=1000, 
    max_retries=3
)
session.mount('http://', adapter)
session.mount('https://', adapter)

def resolve_url(base, rel):
    return urljoin(base, rel)

def fetch_playlist_data(url):
    try:
        # Cache'i delmek için timestamp ekle
        final_url = f"{url}?_={int(time.time())}"
        # Timeout çok kısa tutuldu, cevap vermezse hemen geç
        r = session.get(final_url, headers=HEADERS_COMMON, verify=False, timeout=4)
        return r.text, r.url
    except:
        return None, None

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def main_router():
    if request.args.get('id'):
        return stream_video()
    else:
        return playlist()

def playlist():
    """ Kanal Listesi """
    def generate():
        yield "#EXTM3U\n"
        try:
            r = session.get('https://vavoo.to/live2/index', headers=HEADERS_COMMON, verify=False, timeout=10)
            data = r.text
        except:
            return

        base_self = request.base_url
        pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.IGNORECASE)
        
        for m in pattern.finditer(data):
            name = m.group(1).encode().decode('unicode_escape').replace(',', '')
            id_match = re.search(r'/play/(\d+)', m.group(2))
            if id_match:
                yield f'#EXTINF:-1 group-title="Turkey",{name}\n{base_self}?id={id_match.group(1)}\n'

    return Response(stream_with_context(generate()), content_type='application/x-mpegURL')

def stream_video():
    """ 
    INSTANT START (BURST MODE) 
    İlk açılışta son 3 parçayı beklemeden gönderir.
    """
    stream_id = request.args.get('id')
    master_url = f"https://vavoo.to/play/{stream_id}/index.m3u8"
    
    # VLC'ye "Sakın bekleme yapma" diyen başlıklar
    resp_headers = {
        'Content-Type': 'video/mp2t',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'X-Accel-Buffering': 'no' # Nginx/Render bufferlamasını kapatır
    }

    def generate_stream():
        nonlocal master_url
        played_segments = []
        first_run = True # İlk açılış bayrağı
        fails = 0
        
        while True:
            try:
                content, base_url = fetch_playlist_data(master_url)
                
                if not content:
                    fails += 1
                    if fails > 5: break
                    time.sleep(0.5)
                    continue
                fails = 0

                # Kalite Seçimi
                if '#EXT-X-STREAM-INF' in content:
                    lines = content.splitlines()
                    for line in reversed(lines):
                        if line and not line.startswith('#'):
                            master_url = resolve_url(base_url, line.strip())
                            break
                    continue

                # Segmentleri Topla
                all_segments = []
                lines = content.splitlines()
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        ts_url = resolve_url(base_url, line)
                        all_segments.append(ts_url)

                # --- BURST MODE MANTIĞI ---
                segments_to_process = []
                
                if first_run:
                    # İLK AÇILIŞ: Son 2 parçayı al (Canlı yayın geriden gelir ama ANINDA açılır)
                    # Eğer liste kısaysa hepsini al
                    segments_to_process = all_segments[-2:] if len(all_segments) >= 2 else all_segments
                    first_run = False
                else:
                    # NORMAL MOD: Sadece yeni parçaları al
                    for seg in all_segments:
                        ts_name = urlparse(seg).path.split('/')[-1]
                        if ts_name not in played_segments:
                            segments_to_process.append(seg)

                # Bulunan parçaları gönder
                found_new = False
                for ts_url in segments_to_process:
                    ts_name = urlparse(ts_url).path.split('/')[-1]
                    
                    # Güvenlik kontrolü (Tekrarı önle)
                    if ts_name not in played_segments:
                        try:
                            # stream=True ile beklemeden bas
                            with session.get(ts_url, headers=HEADERS_COMMON, verify=False, stream=True, timeout=8) as r:
                                if r.status_code == 200:
                                    # Chunk size artırıldı (Hızlı aktarım)
                                    for chunk in r.iter_content(chunk_size=131072):
                                        if chunk: yield chunk
                                        
                            played_segments.append(ts_name)
                            if len(played_segments) > 20: played_segments.pop(0)
                            found_new = True
                        except:
                            pass
                
                # Akıllı Bekleme
                if found_new:
                    # Eğer veri gönderdiysek, bir sonrakinin oluşması için çok az beklemeyiz
                    # Çünkü stream ederken zaten vakit geçti.
                    pass
                else:
                    # Yeni veri yoksa, sunucuyu yormamak için 1.5 sn bekle
                    time.sleep(1.5)

            except GeneratorExit:
                break
            except Exception:
                time.sleep(1)

    return Response(stream_with_context(generate_stream()), headers=resp_headers)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
