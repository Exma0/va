from gevent import monkey
monkey.patch_all()

import re
import requests
import time
import sys
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote
from threading import Lock

app = Flask(__name__)

# =====================================================
# AYARLAR & SABİTLER
# =====================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}
requests.packages.urllib3.disable_warnings()

# Bağlantı Havuzu (Yüksek Performans)
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=500, pool_maxsize=500, max_retries=2)
session.mount('http://', adapter)
session.mount('https://', adapter)

# =====================================================
# THE BRAIN (ZEKA MERKEZİ)
# =====================================================
class ChannelBrain:
    def __init__(self):
        # Yapı: { 'cid': { 'base_url': '...', 'last_update': 12345, 'lock': Lock() } }
        self.channels = {}

    def get_base_url(self, cid):
        """Kanalın güncel sunucu adresini getirir."""
        if cid in self.channels:
            # Token süresi (örn: 10 dk) dolmak üzereyse yenile (Proaktif)
            if time.time() - self.channels[cid]['last_update'] > 600:
                self.refresh_channel(cid)
            return self.channels[cid]['base_url']
        
        # İlk kez isteniyorsa bul ve kaydet
        return self.refresh_channel(cid)

    def refresh_channel(self, cid):
        """
        Zeki Yenileme: Vavoo'dan taze link alır.
        Thread-Safe (Kilitli) yapısı sayesinde aynı anda 100 kişi istese de
        sunucuya sadece 1 istek gider.
        """
        # Kanal kaydı yoksa oluştur
        if cid not in self.channels:
            self.channels[cid] = {'base_url': None, 'last_update': 0, 'lock': Lock()}
            
        with self.channels[cid]['lock']:
            # Kilit açıldığında başkası güncellemiş mi kontrol et (Double-Check)
            if time.time() - self.channels[cid]['last_update'] < 10: 
                if self.channels[cid]['base_url']:
                    return self.channels[cid]['base_url']

            print(f"[BRAIN] Kanal {cid} icin yeni frekans araniyor...", file=sys.stderr)
            try:
                # Vavoo API İsteği
                vavoo_api = f"https://vavoo.to/play/{cid}/index.m3u8"
                r = session.get(vavoo_api, headers=HEADERS, verify=False, timeout=5, allow_redirects=True)
                
                if r.status_code == 200:
                    final_url = r.url
                    content = r.text
                    
                    # Master Playlist Çözümleme
                    if "#EXT-X-STREAM-INF" in content:
                        lines = content.splitlines()
                        for line in reversed(lines):
                            if line and not line.startswith("#"):
                                final_url = urljoin(final_url, line)
                                # Derinlemesine git (Redirect varsa çöz)
                                try:
                                    r2 = session.get(final_url, headers=HEADERS, timeout=5)
                                    final_url = r2.url
                                except: pass
                                break
                    
                    # Base URL'i (klasörü) kaydet
                    # Örn: https://server5.vavoo.../hls/
                    base_url = final_url.rsplit('/', 1)[0] + '/'
                    
                    self.channels[cid]['base_url'] = base_url
                    self.channels[cid]['last_update'] = time.time()
                    print(f"[BRAIN] Kanal {cid} guncellendi: {base_url[:30]}...", file=sys.stderr)
                    return base_url
            except Exception as e:
                print(f"[BRAIN ERROR] {cid}: {e}", file=sys.stderr)
        
        return self.channels[cid].get('base_url')

brain = ChannelBrain()

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def root():
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=10)
        data = r.text
    except:
        return "Liste Alinamadi", 502

    base_app_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            # URL yapısı: /live/KANAL_ID.m3u8
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_app_url}/live/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def smart_playlist(cid):
    # 1. Beyinden güncel sunucu adresini al
    base_url = brain.get_base_url(cid)
    if not base_url: return Response("Kaynak Bulunamadi", status=404)

    try:
        # 2. index.m3u8 dosyasını çek
        target_m3u8 = urljoin(base_url, "index.m3u8")
        r = session.get(target_m3u8, headers=HEADERS, verify=False, timeout=6)
        
        if r.status_code != 200:
            # Hata varsa beyne "Bu link bozuk, yenisini bul" emri ver (REPAIR)
            print(f"[REPAIR] Playlist bozuk ({r.status_code}), onariliyor...", file=sys.stderr)
            brain.refresh_channel(cid)
            return Response("Yenileniyor...", status=503)

        content = r.text
        new_lines = []
        
        # 3. İçeriği işle
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                # Segment ismini al (örn: segment_100.ts)
                # Linki şifrelemeden direkt parametre olarak geçiyoruz ama CID'yi de ekliyoruz
                # Böylece segment hataya düşerse hangi kanalı onaracağımızı biliriz.
                # Format: /seg?file=segment_100.ts&cid=12345
                
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?file={line}&cid={cid}")

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception:
        return Response("Server Error", status=500)

@app.route('/seg')
def smart_segment():
    ts_file = request.args.get('file')
    cid = request.args.get('cid')
    
    if not ts_file or not cid: return "Bad Request", 400

    def stream_content():
        # 3 Deneme Hakkı (Retry Loop)
        for attempt in range(3):
            # 1. Beyinden güncel sunucuyu al
            base_url = brain.get_base_url(cid)
            if not base_url: break

            target_url = urljoin(base_url, ts_file)

            try:
                with session.get(target_url, headers=HEADERS, verify=False, stream=True, timeout=10) as r:
                    
                    # 2. Eğer Vavoo hata verirse (403/404)
                    if r.status_code != 200:
                        print(f"[FAIL] Segment Hatasi {r.status_code}. Deneme {attempt+1}/3. Kanal onariliyor...", file=sys.stderr)
                        # KRİTİK HAMLE: Kanalı anında yenile!
                        brain.refresh_channel(cid)
                        # Döngü başa döner, yeni URL ile tekrar deneriz.
                        continue 
                    
                    # 3. Başarılıysa veriyi akıt
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: yield chunk
                    
                    # Veri bitti, döngüden çık
                    return 

            except Exception as e:
                print(f"[NET ERR] {e}. Retrying...", file=sys.stderr)
                time.sleep(0.5)
        
        # 3 denemede de olmazsa pes et
        return

    return Response(stream_with_context(stream_content()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
