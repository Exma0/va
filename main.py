# =====================================================
# KRİTİK: BU İKİ SATIR EN TEPEDE OLMALI (HATA DÜZELTİCİ)
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
# AYARLAR VE SABİTLER
# =====================================================
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS_COMMON = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}

# SSL uyarılarını kapat
requests.packages.urllib3.disable_warnings()

# Global Session (Bağlantı Havuzu - Optimize Edildi)
session = requests.Session()
# Pool size artırıldı, böylece çoklu bağlantılarda tıkanma olmaz
adapter = requests.adapters.HTTPAdapter(
    pool_connections=1000, 
    pool_maxsize=1000, 
    max_retries=3
)
session.mount('http://', adapter)
session.mount('https://', adapter)


# =====================================================
# YARDIMCI FONKSİYONLAR
# =====================================================

def resolve_url(base, rel):
    return urljoin(base, rel)

def fetch_playlist_data(url):
    """Playlist verisini çeker - Timeout düşürüldü"""
    try:
        # Cache önlemek için timestamp ekliyoruz
        final_url = f"{url}?_={int(time.time())}"
        r = session.get(final_url, headers=HEADERS_COMMON, verify=False, timeout=5)
        return r.text, r.url
    except Exception:
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
    """ KANAL LİSTESİ OLUŞTURUCU (Hızlı Regex Modu) """
    def generate():
        yield "#EXTM3U\n"
        
        try:
            r = session.get(
                'https://vavoo.to/live2/index',
                headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
                verify=False,
                timeout=15
            )
            json_raw = r.text
        except Exception:
            yield "#EXTINF:-1,HATA: Baglanti Yok\nhttp://error\n"
            return

        if not json_raw:
            yield "#EXTINF:-1,HATA: Liste Bos\nhttp://error\n"
            return

        base_self = request.base_url

        # Regex ile listeyi parse et (JSON modülünden daha hızlıdır)
        pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.IGNORECASE)
        matches = pattern.finditer(json_raw)
        
        count = 0
        for m in matches:
            name_raw = m.group(1).encode().decode('unicode_escape')
            url_raw = m.group(2)
            
            # URL içinden ID'yi çek
            id_match = re.search(r'/play/(\d+)', url_raw)
            if id_match:
                stream_id = id_match.group(1)
                
                # İsim temizliği
                name = name_raw.replace('&amp;', '&')
                name = name.replace(',', '').replace('"', '').replace('\r', '').replace('\n', '')
                name = re.sub(r'\s*\(\d+\)$', '', name).strip()
                
                yield f'#EXTINF:-1 group-title="Turkey",{name}\n'
                yield f'{base_self}?id={stream_id}\n'
                count += 1
                
        if count == 0:
             yield "#EXTINF:-1,BILGI: Kanal Bulunamadi\nhttp://error\n"

    return Response(stream_with_context(generate()), content_type='application/x-mpegURL')


def stream_video():
    """ 
    OPTIMIZE EDİLMİŞ STREAM OYNATICI 
    - Yarış modu (Race) kaldırıldı.
    - ThreadPool kaldırıldı (CPU yükünü düşürür).
    - Anlık iletim (Direct Pipe) eklendi.
    """
    stream_id = request.args.get('id')
    master_url = f"https://vavoo.to/play/{stream_id}/index.m3u8"
    
    resp_headers = {
        'Content-Type': 'video/mp2t',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'Access-Control-Allow-Origin': '*'
    }

    def generate_stream():
        nonlocal master_url
        played_segments = [] # Oynatılanları hafızada tut
        fails = 0
        
        while True:
            try:
                # Playlist'i çek
                content, base_url = fetch_playlist_data(master_url)
                
                if not content:
                    fails += 1
                    if fails > 5: break # 5 kere üst üste hata verirse çık
                    time.sleep(1)
                    continue
                
                fails = 0

                # 1. Master Playlist Kontrolü (Kalite Seçimi)
                # Eğer gelen dosya başka m3u8 linkleri içeriyorsa en iyisini seç
                if '#EXT-X-STREAM-INF' in content:
                    lines = content.splitlines()
                    best_url = None
                    # Genelde listenin sonundaki link en yüksek kalitedir
                    for line in reversed(lines):
                        if line and not line.startswith('#'):
                            best_url = resolve_url(base_url, line.strip())
                            break
                    
                    if best_url:
                        master_url = best_url
                        continue

                # 2. Segmentleri Parse Et ve Oynat
                lines = content.splitlines()
                found_new = False
                target_duration = 4.0 # Varsayılan segment süresi

                for line in lines:
                    line = line.strip()
                    
                    # Segment süresini yakala
                    if line.startswith('#EXTINF:'):
                        try:
                            target_duration = float(line.split(':')[1].split(',')[0])
                        except:
                            pass

                    if line and not line.startswith('#'):
                        ts_url = resolve_url(base_url, line)
                        ts_name = urlparse(ts_url).path.split('/')[-1]
                        
                        # Eğer bu parça daha önce oynatılmadıysa İNDİR ve GÖNDER
                        if ts_name not in played_segments:
                            try:
                                # stream=True ile veriyi RAM'e yüklemeden anında izleyiciye akıt
                                with session.get(ts_url, headers=HEADERS_COMMON, verify=False, stream=True, timeout=10) as r:
                                    if r.status_code == 200:
                                        # 64KB'lık parçalar halinde gönder (Optimum boyut)
                                        for chunk in r.iter_content(chunk_size=65536):
                                            if chunk: yield chunk
                                            
                                # Listeye ekle
                                played_segments.append(ts_name)
                                # Hafıza şişmesini önlemek için eski kayıtları sil (Son 20 parça yeterli)
                                if len(played_segments) > 20:
                                    played_segments.pop(0)
                                
                                found_new = True
                            except Exception:
                                # İndirme hatası olursa pas geç, bir sonrakini dene
                                pass

                # 3. Akıllı Bekleme Döngüsü
                if found_new:
                    # Eğer yeni parça bulduysak, canlı yayının ilerlemesi için beklemiyoruz.
                    # Çünkü video oynatılırken geçen süre zaten bekleme yerine geçer.
                    # Sadece çok hafif bir nefes alma süresi.
                    pass 
                else:
                    # Yeni parça yoksa, sunucuyu yormamak için segment süresinin yarısı kadar bekle
                    time.sleep(target_duration / 2)
            
            except GeneratorExit:
                # İstemci (VLC) bağlantıyı keserse döngüyü kır
                break
            except Exception:
                time.sleep(1)

    return Response(stream_with_context(generate_stream()), headers=resp_headers)

if __name__ == '__main__':
    # Threaded mod performans için şarttır
    app.run(host='0.0.0.0', port=8080, threaded=True)
