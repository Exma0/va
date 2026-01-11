import re
import requests
import time
import json
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# =====================================================
# AYARLAR VE SABİTLER
# =====================================================
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS_COMMON = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Connection": "keep-alive"
}

# SSL uyarılarını kapat
requests.packages.urllib3.disable_warnings()

# Global Session (Bağlantı Havuzu)
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
session.mount('http://', adapter)
session.mount('https://', adapter)


# =====================================================
# YARDIMCI FONKSİYONLAR
# =====================================================

def resolve_url(base, rel):
    """URL Birleştirici (PHP'deki resolve_url karşılığı)"""
    return urljoin(base, rel)

def fetch_url_race(url, headers):
    """
    --- MOTOR 2: RACE & BURST ---
    PHP'deki curl_multi mantığının Python karşılığı.
    Aynı URL'ye 3 farklı thread ile saldırır, ilk gelen veriyi alır.
    """
    racer_count = 3
    
    def _req(u, h):
        try:
            # Race modu için kısa timeout
            with session.get(u, headers=h, verify=False, timeout=6, stream=False) as r:
                if r.status_code == 200:
                    return r.content
        except Exception:
            pass
        return None

    # ThreadPool ile yarış başlat
    with ThreadPoolExecutor(max_workers=racer_count) as executor:
        futures = [executor.submit(_req, url, headers) for _ in range(racer_count)]
        
        for future in as_completed(futures):
            result = future.result()
            # Veri doluysa ve boyutu mantıklıysa (1KB+) kazananı döndür
            if result and len(result) > 1024: 
                return result
    return None

def fetch_playlist_data(url):
    """Playlist verisini çeker"""
    try:
        h = HEADERS_COMMON.copy()
        h["Connection"] = "close" # Taze veri için
        
        r = requests.get(url, headers=h, verify=False, timeout=4)
        return r.text, r.url
    except Exception:
        return None, None

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def main_router():
    """
    PHP mantığı: ?id= varsa Stream modu, yoksa Liste modu.
    """
    if request.args.get('id'):
        return stream_video()
    else:
        return playlist()

def playlist():
    """
    MOD 2: LISTE (FLASH REGEX)
    Vavoo JSON verisini çeker ve M3U formatına çevirir.
    """
    def generate():
        yield "#EXTM3U\n"
        
        try:
            r = requests.get(
                'https://vavoo.to/live2/index',
                headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
                verify=False,
                timeout=60
            )
            json_raw = r.text
        except Exception:
            yield "#EXTINF:-1,HATA: Baglanti Yok\nhttp://error\n"
            return

        if not json_raw:
            yield "#EXTINF:-1,HATA: Liste Bos\nhttp://error\n"
            return

        base_self = request.base_url

        # PHP'deki Regex'in Python karşılığı
        # "group":"Turkey" ... "name":"Kanal Adı" ... "url":"Link"
        pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.IGNORECASE)
        
        matches = pattern.finditer(json_raw)
        
        count = 0
        for m in matches:
            name_raw = m.group(1).encode().decode('unicode_escape')
            url_raw = m.group(2)
            
            # URL içinden ID'yi çek (/play/123456/...)
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
    MOD 1: FUSION OYNATICI
    """
    stream_id = request.args.get('id')
    master_url = f"https://vavoo.to/play/{stream_id}/index.m3u8"
    
    # VLC için gerekli headerlar
    resp_headers = {
        'Content-Type': 'video/mp2t',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    }

    def generate_stream():
        nonlocal master_url
        played_segments = []
        fails = 0
        first_run = True
        
        while True:
            # İstemci (VLC) bağlantıyı kestiyse döngüyü kır
            # Flask context içinde bunu kontrol etmek zordur, yield hatasıyla kırılır genelde.
            
            content, base_url = fetch_playlist_data(master_url)
            
            if not content:
                fails += 1
                if fails > 10: break
                time.sleep(0.2)
                continue
            
            fails = 0

            # Master M3U8 (Çözünürlük Seçimi) Kontrolü
            if '#EXT-X-STREAM-INF' in content:
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if '#EXT-X-STREAM-INF' in line:
                        # Genelde bir alt satır URL'dir
                        if i + 1 < len(lines):
                            master_url = resolve_url(base_url, lines[i+1].strip())
                            break
                continue

            # Segmentleri Parse Et
            lines = content.splitlines()
            duration = 4.0
            found_new = False
            
            for line in lines:
                line = line.strip()
                if line.startswith('#EXTINF:'):
                    try:
                        # Süreyi al (#EXTINF:4.000,)
                        duration = float(line.split(':')[1].split(',')[0])
                    except:
                        pass
                
                if line and not line.startswith('#'):
                    ts_url = resolve_url(base_url, line)
                    ts_name = urlparse(ts_url).path.split('/')[-1]
                    
                    # Eğer bu parça daha önce oynatılmadıysa
                    if ts_name not in played_segments:
                        
                        # --- MOTOR 1: INSTANT START (HIZ) ---
                        if first_run:
                            try:
                                # Stream=True ile veriyi parça parça hemen gönder
                                with session.get(ts_url, headers=HEADERS_COMMON, verify=False, stream=True, timeout=10) as r:
                                    for chunk in r.iter_content(chunk_size=8192):
                                        if chunk:
                                            yield chunk
                                first_run = False
                            except Exception:
                                pass
                        
                        # --- MOTOR 2: RACE & BURST (KALİTE) ---
                        else:
                            # 3 koldan saldır, en hızlısını al ve tek seferde bas
                            data = fetch_url_race(ts_url, HEADERS_COMMON)
                            if data:
                                yield data

                        # Oynatılanlar listesini güncelle
                        played_segments.append(ts_name)
                        if len(played_segments) > 40:
                            played_segments.pop(0)
                        
                        found_new = True

            if found_new:
                # Canlı yayın senkronizasyonu için bekleme
                if not first_run:
                    time.sleep(duration * 0.85)
            else:
                time.sleep(0.2)

    return Response(stream_with_context(generate_stream()), headers=resp_headers)

if __name__ == '__main__':
    # Threaded=True çoklu izleyici için şarttır
    app.run(host='0.0.0.0', port=8080, threaded=True)
