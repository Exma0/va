from gevent import monkey
monkey.patch_all()

import json
import re
import requests
import time
import sys
import urllib3
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote, urlparse
from threading import Lock, RLock
from gevent.pywsgi import WSGIServer

app = Flask(__name__)

# =====================================================
# AYARLAR VE KAYNAKLAR
# =====================================================

# Öncelik sırasına göre kaynaklar. (Huhu genelde en hızlısıdır)
SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Connection": "keep-alive"
}

# SSL Uyarılarını Kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Bağlantı Havuzu (Daha agresif ayarlandı)
session = requests.Session()
# Max size 200'e çıkarıldı, aynı anda çok istek gelirse kuyruk oluşmasın
adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200, max_retries=1)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Yardımcı Fonksiyon: Dinamik Header Oluşturucu
def get_headers(base_url):
    """İstek atılan domain'e uygun Referer ve Origin üretir."""
    headers = BASE_HEADERS.copy()
    headers["Referer"] = f"{base_url}/"
    headers["Origin"] = base_url
    return headers

# =====================================================
# THE BRAIN (Çoklu Kaynak Çözümleme Merkezi)
# =====================================================
class StreamBrain:
    def __init__(self):
        # Cache yapısı: { 'cid': {'final_url': '...', 'updated_at': 123, 'source_used': 'https://...'} }
        self.channels = {}
        self.locks = {}
        self.global_lock = RLock()

    def get_lock(self, cid):
        with self.global_lock:
            if cid not in self.locks:
                self.locks[cid] = Lock()
            return self.locks[cid]

    def resolve_stream_url(self, cid, force_refresh=False):
        """
        Kanalı bulmak için tüm kaynakları tarar.
        """
        # Cache Kontrolü (5 Dakika)
        if not force_refresh and cid in self.channels:
            if time.time() - self.channels[cid]['updated_at'] < 300:
                return self.channels[cid]['final_url']

        lock = self.get_lock(cid)
        with lock:
            # Race condition için tekrar kontrol
            if not force_refresh and cid in self.channels:
                if time.time() - self.channels[cid]['updated_at'] < 300:
                    return self.channels[cid]['final_url']
            
            # TÜM KAYNAKLARI DENE (Failover Logic)
            for source_url in SOURCES:
                try:
                    # 1. API İsteği
                    initial_url = f"{source_url}/play/{cid}/index.m3u8"
                    current_headers = get_headers(source_url)
                    
                    # Timeout düşük tutuldu, hızlıca diğer kaynağa geçsin diye (4sn)
                    r = session.get(initial_url, headers=current_headers, verify=False, timeout=4, allow_redirects=True)
                    
                    if r.status_code != 200:
                        continue # Bu site çalışmadı, sonrakine geç

                    # 2. Redirect ve Master Playlist Çözümleme
                    current_url = r.url
                    content = r.text
                    
                    # Kalite seçimi (Master Playlist ise)
                    if "#EXT-X-STREAM-INF" in content:
                        lines = content.splitlines()
                        found_variant = False
                        for line in reversed(lines):
                            if line and not line.startswith("#"):
                                variant_url = urljoin(current_url, line)
                                # Linkin erişilebilir olduğunu hızlıca test et (HEAD isteği yerine GET range ile)
                                try:
                                    # Sadece ilk byte'ları isteyerek test et (daha hızlı)
                                    test_headers = current_headers.copy()
                                    test_headers['Range'] = 'bytes=0-100'
                                    r2 = session.get(variant_url, headers=test_headers, timeout=3)
                                    if r2.status_code in [200, 206]:
                                        current_url = r2.url # Redirect varsa güncelle
                                        found_variant = True
                                        break
                                except:
                                    pass
                        if not found_variant:
                            continue # Bu kaynaktaki varyantlar bozuk, diğer siteye geç

                    # 3. Başarılı Sonucu Kaydet
                    self.channels[cid] = {
                        'final_url': current_url,
                        'updated_at': time.time(),
                        'source_used': source_url # Hangi sitenin çalıştığını bilmek istersen
                    }
                    return current_url

                except Exception as e:
                    # Hata loglarını görmek istersen: print(f"Source fail {source_url}: {e}")
                    continue

            return None # Hiçbir kaynak çalışmadı

brain = StreamBrain()

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def root():
    # Kanal listesini çekmek için kaynakları dene
    data = None
    used_source = ""
    
    for source in SOURCES:
        try:
            url = f"{source}/live2/index"
            r = session.get(url, headers=get_headers(source), verify=False, timeout=6)
            if r.status_code == 200:
                data = r.json()
                used_source = source
                break # Liste alındı, döngüden çık
        except:
            continue
            
    if not data:
        return "Hicbir kaynaktan liste alinamadi.", 502

    base_app_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # JSON verisini işle
    # Hızlı olması için string birleştirme yerine list append kullanıyoruz
    for item in data:
        # Sadece Turkey grubu
        if item.get("group") == "Turkey":
            name = item.get("name", "Unknown").replace(',', ' ')
            url_val = item.get("url", "")
            
            # URL içinden ID'yi al
            match = re.search(r'/play/(\d+)', url_val)
            if match:
                cid = match.group(1)
                logo = item.get("logo", "")
                out.append(f'#EXTINF:-1 group-title="Turkey" tvg-logo="{logo}",{name}\n{base_app_url}/live/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    final_url = brain.resolve_stream_url(cid)
    if not final_url: return Response("Yayin Bulunamadi (Tum Kaynaklar Denendi)", status=404)

    # final_url'in domainini bulup ona uygun header üretmemiz lazım
    parsed_final = urlparse(final_url)
    origin_base = f"{parsed_final.scheme}://{parsed_final.netloc}"
    req_headers = get_headers(origin_base)

    try:
        r = session.get(final_url, headers=req_headers, verify=False, timeout=5)
        
        # Token süresi dolmuşsa yenile (Force Refresh)
        if r.status_code != 200:
            final_url = brain.resolve_stream_url(cid, force_refresh=True)
            if not final_url: return Response("Yayin Kirik", status=503)
            # URL değiştiyse headerı da güncelle
            parsed_final = urlparse(final_url)
            origin_base = f"{parsed_final.scheme}://{parsed_final.netloc}"
            req_headers = get_headers(origin_base)
            
            r = session.get(final_url, headers=req_headers, verify=False, timeout=5)

        content = r.text
        base_url = r.url # Redirect sonrası gerçek URL
        new_lines = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                # TS veya Key dosyasının tam adresi
                ts_full_url = urljoin(base_url, line)
                safe_target = quote(ts_full_url)
                
                # Proxy linkini oluştur
                # cid'i parametre olarak geçiyoruz ki hata durumunda Brain yeniden çözümleyebilsin
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?cid={cid}&target={safe_target}")

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception:
        return Response("Server Error", status=500)

@app.route('/seg')
def segment_handler():
    cid = request.args.get('cid')
    target_url_encoded = request.args.get('target')
    
    if not cid or not target_url_encoded: return "Bad Request", 400
    
    current_target_url = unquote(target_url_encoded)
    
    # Target URL'den domaini çek ve header oluştur
    parsed_target = urlparse(current_target_url)
    origin_base = f"{parsed_target.scheme}://{parsed_target.netloc}"
    req_headers = get_headers(origin_base)

    final_response = None
    
    # 3 Deneme Hakkı
    for attempt in range(3):
        try:
            # Eğer ilk deneme değilse, URL'yi tazelemeyi dene
            if attempt > 0:
                # Yeni bir master URL bul
                new_base_m3u8 = brain.resolve_stream_url(cid, force_refresh=True)
                if new_base_m3u8:
                    # Eski TS dosya adını al, yeni base URL'e yapıştır
                    # Bu çok kritik çünkü tokenlar değişmiş olabilir ama dosya adı (seg-1.ts) aynıdır.
                    path_parts = parsed_target.path.split('/')
                    file_name = path_parts[-1]
                    
                    current_target_url = urljoin(new_base_m3u8, file_name)
                    
                    # Yeni URL için headerları güncelle
                    parsed_new = urlparse(current_target_url)
                    origin_base = f"{parsed_new.scheme}://{parsed_new.netloc}"
                    req_headers = get_headers(origin_base)

            upstream = session.get(current_target_url, headers=req_headers, verify=False, stream=True, timeout=8)
            
            if upstream.status_code == 200:
                final_response = upstream
                break
            elif upstream.status_code in [403, 404, 410, 503]:
                upstream.close()
                continue # Hata aldı, tekrar dene (üstteki if bloğuna girip link yenileyecek)
            else:
                upstream.close()
                continue

        except Exception:
            time.sleep(0.2)
            continue

    if not final_response:
        return Response("Segment Unavailable", status=503)

    def generate(upstream_resp):
        try:
            # Chunk size video akışı için optimize edildi
            for chunk in upstream_resp.iter_content(chunk_size=65536):
                if chunk: yield chunk
        except:
            pass
        finally:
            upstream_resp.close()

    return Response(stream_with_context(generate(final_response)), content_type="video/mp2t")

# =====================================================
# MAIN
# =====================================================
if __name__ == "__main__":
    port = 8080
    print(f"==========================================")
    print(f" YUKSEK PERFORMANS VAVOO PROXY (MULTI-SOURCE)")
    print(f" Kaynaklar: {', '.join([x.replace('https://', '') for x in SOURCES])}")
    print(f" Adres: http://0.0.0.0:{port}")
    print(f"==========================================")
    
    try:
        http_server = WSGIServer(('0.0.0.0', port), app)
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("Kapatiliyor...")
