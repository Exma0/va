from gevent import monkey
monkey.patch_all()

import re
import requests
import time
import sys
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote
from threading import Lock, RLock

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
adapter = requests.adapters.HTTPAdapter(pool_connections=500, pool_maxsize=500, max_retries=2)
session.mount('http://', adapter)
session.mount('https://', adapter)

# =====================================================
# THE BRAIN (Mantık Hatası Giderilmiş Versiyon)
# =====================================================
class StreamBrain:
    def __init__(self):
        # { 'cid': {'final_url': '...', 'updated_at': 123} }
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
        Kanalın en son çalışan 'index.m3u8' adresini (Redirectler çözülmüş halde) bulur.
        Base URL değil, Full URL döner.
        """
        # Cache Kontrolü
        if not force_refresh and cid in self.channels:
            # 5 Dakika (300sn) cache süresi
            if time.time() - self.channels[cid]['updated_at'] < 300:
                return self.channels[cid]['final_url']

        lock = self.get_lock(cid)
        with lock:
            # Double Check (Kilit açılınca tekrar bak)
            if not force_refresh and cid in self.channels:
                if time.time() - self.channels[cid]['updated_at'] < 300:
                    return self.channels[cid]['final_url']
            
            # --- VAVOO SORGUSU ---
            try:
                # 1. İlk İstek
                initial_url = f"https://vavoo.to/play/{cid}/index.m3u8"
                r = session.get(initial_url, headers=HEADERS, verify=False, timeout=8, allow_redirects=True)
                if r.status_code != 200: return None
                
                # 2. Redirect ve Master Playlist Çözümleme
                current_url = r.url
                content = r.text
                
                # Eğer Master Playlist ise (Kalite seçenekleri varsa)
                if "#EXT-X-STREAM-INF" in content:
                    lines = content.splitlines()
                    # En son satırdaki linki al (Genelde en yüksek kalite)
                    for line in reversed(lines):
                        if line and not line.startswith("#"):
                            # urljoin kullanımı: Mantık hatasını çözer
                            # Göreli linki tam linke çevirir
                            current_url = urljoin(current_url, line)
                            
                            # O linkin içindeki gerçek medya playlist'i doğrula
                            try:
                                r2 = session.get(current_url, headers=HEADERS, timeout=5)
                                if r2.status_code == 200:
                                    current_url = r2.url
                            except: pass
                            break
                
                # 3. Sonuçları Kaydet
                # Base URL değil, direkt çalışan son m3u8 linkini saklıyoruz.
                self.channels[cid] = {
                    'final_url': current_url,
                    'updated_at': time.time()
                }
                return current_url

            except Exception as e:
                # print(f"Brain Error: {e}", file=sys.stderr)
                return None

brain = StreamBrain()

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def root():
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=10)
        data = r.text
    except:
        return "Liste Hatasi", 502

    base_app_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_app_url}/live/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    # 1. Beyinden çalışan URL'yi al
    final_url = brain.resolve_stream_url(cid)
    if not final_url: return Response("Yayin Yok", status=404)

    try:
        # 2. İçeriği çek
        r = session.get(final_url, headers=HEADERS, verify=False, timeout=6)
        
        # Hata varsa (Token süresi dolmuş olabilir), yenile ve tekrar dene
        if r.status_code != 200:
            final_url = brain.resolve_stream_url(cid, force_refresh=True)
            if not final_url: return Response("Yayin Kirik", status=503)
            r = session.get(final_url, headers=HEADERS, verify=False, timeout=6)

        content = r.text
        new_lines = []
        
        # 3. Satırları işle
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                # MANTIK DÜZELTMESİ:
                # segment linkini oluştururken r.url (istek yapılan son adres) kullanıyoruz.
                # Böylece göreli yollar (../../segment.ts) doğru hesaplanır.
                # Şifrelemeyi kaldırıp parametreye gömüyoruz.
                
                # Dosya adını quote ile güvenli hale getiriyoruz çünkü içinde ?token= olabilir
                original_segment_url = urljoin(r.url, line)
                safe_segment_url = quote(original_segment_url)
                
                # Parametre olarak CID'yi de ekliyoruz ki segment hata verirse onarabilelim
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?cid={cid}&target={safe_segment_url}")

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception:
        return Response("Server Error", status=500)

@app.route('/seg')
def segment_handler():
    # Parametreleri al: Hem hedef URL'yi hem de Kanal ID'yi biliyoruz
    cid = request.args.get('cid')
    target_url_encoded = request.args.get('target')
    
    if not cid or not target_url_encoded: return "Bad Request", 400
    
    # İlk hedef URL (Playlistten gelen)
    current_target_url = unquote(target_url_encoded)

    # =================================================================
    # MANTIK HATASI GİDERİLMİŞ AKIŞ MİMARİSİ
    # =================================================================
    # Önce bağlantıyı kurmaya çalışıyoruz. Eğer bağlantı kurulamazsa
    # Flask'a Response nesnesi döndürmüyoruz. Hata kodunu döndürüyoruz.
    # Böylece TiviMate "200 OK" alıp boş dosya ile karşılaşmıyor.
    
    final_response = None
    
    # 3 Deneme Hakkı
    for attempt in range(3):
        try:
            # Eğer önceki deneme başarısız olduysa ve URL yenilendiyse:
            if attempt > 0:
                # Yeni base URL'yi bul
                new_base_m3u8 = brain.resolve_stream_url(cid, force_refresh=True)
                if new_base_m3u8:
                    # Eski segment ismini (filename) URL'den ayıkla
                    # Bu kısım risklidir ama Vavoo yapısında genelde dosya isimleri korunur
                    file_name = current_target_url.split('/')[-1]
                    # Yeni URL oluştur
                    current_target_url = urljoin(new_base_m3u8, file_name)

            # İsteği başlat (stream=True henüz veri indirmez, sadece başlıkları alır)
            upstream = session.get(current_target_url, headers=HEADERS, verify=False, stream=True, timeout=10)
            
            if upstream.status_code == 200:
                final_response = upstream
                break # Başarılı! Döngüden çık.
            else:
                upstream.close()
                # Başarısız. 403 veya 404.
                # Loop devam edecek -> attempt artacak -> URL yenilenecek.
                continue

        except Exception:
            time.sleep(0.5)
            continue

    # 3 deneme sonunda hala başarılı bir bağlantı yoksa HATA DÖN
    if not final_response:
        return Response("Segment Unavailable", status=503)

    # Başarılı bağlantıyı kullanıcıya akıt
    def generate(upstream_resp):
        try:
            for chunk in upstream_resp.iter_content(chunk_size=65536):
                if chunk: yield chunk
        except:
            pass
        finally:
            upstream_resp.close()

    return Response(stream_with_context(generate(final_response)), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
