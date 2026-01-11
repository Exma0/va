# =====================================================
# 1. GEVENT YAMASI (SİSTEMİN KALBİ)
# =====================================================
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
# 2. AYARLAR & SAHTE KİMLİK
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
# 3. THE BRAIN (KANAL YÖNETİM MERKEZİ)
# =====================================================
class StreamBrain:
    def __init__(self):
        # Kanal bilgilerini tutan hafıza
        # { 'cid': {'base_url': 'https://...', 'updated_at': 123456} }
        self.channels = {}
        self.locks = {} # Her kanal için ayrı kilit (Thread-Safe)
        self.global_lock = RLock()

    def get_lock(self, cid):
        """Her kanal için özel kilit oluşturur"""
        with self.global_lock:
            if cid not in self.locks:
                self.locks[cid] = Lock()
            return self.locks[cid]

    def get_live_url(self, cid, force_refresh=False):
        """
        Kanalın en güncel sunucu adresini verir.
        Eğer adres yoksa veya force_refresh=True ise yenisini bulur.
        """
        # Hafızada varsa ve zorla yenileme istenmediyse, hafızadakini ver (HIZLI)
        if not force_refresh and cid in self.channels:
            # Token süresi 10 dakikayı geçtiyse yenile (PROAKTİF)
            if time.time() - self.channels[cid]['updated_at'] < 600:
                return self.channels[cid]['base_url']

        # Yoksa veya eskidyse yenisini bul (GÜVENLİ)
        lock = self.get_lock(cid)
        with lock:
            # Kilitliyken başkası yeniledi mi kontrol et (Double Check)
            if not force_refresh and cid in self.channels:
                 if time.time() - self.channels[cid]['updated_at'] < 600:
                    return self.channels[cid]['base_url']
            
            # --- VAVOO API SORGUSU ---
            try:
                # print(f"[BRAIN] Kanal {cid} icin yeni sunucu araniyor...", file=sys.stderr)
                r = session.get(f"https://vavoo.to/play/{cid}/index.m3u8", headers=HEADERS, verify=False, timeout=8, allow_redirects=True)
                if r.status_code != 200: return None
                
                final_url = r.url
                content = r.text
                
                # Master Playlist ise en iyi kaliteyi seç
                if "#EXT-X-STREAM-INF" in content:
                    lines = content.splitlines()
                    for line in reversed(lines):
                        if line and not line.startswith("#"):
                            final_url = urljoin(final_url, line)
                            # Redirect varsa çöz
                            try:
                                r2 = session.get(final_url, headers=HEADERS, timeout=5)
                                final_url = r2.url
                            except: pass
                            break
                
                # Base URL'i al (Sonundaki dosya ismini at, klasörü al)
                base_url = final_url.rsplit('/', 1)[0] + '/'
                
                # Hafızaya kaydet
                self.channels[cid] = {
                    'base_url': base_url,
                    'updated_at': time.time()
                }
                return base_url

            except Exception as e:
                # print(f"[ERR] Kanal {cid} yenilenemedi: {e}", file=sys.stderr)
                return None

brain = StreamBrain()

# =====================================================
# 4. ROTALAR (ENDPOINTLER)
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
            # Link yapısı: /live/KANAL_ID.m3u8
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_app_url}/live/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    # 1. Beyinden sunucu adresini iste
    base_url = brain.get_live_url(cid)
    if not base_url: return Response("Yayin Yok", status=404)

    try:
        # 2. Playlist dosyasını çek
        r = session.get(urljoin(base_url, "index.m3u8"), headers=HEADERS, verify=False, timeout=6)
        
        # Eğer sunucu hata verirse (403/404), anında yenile ve tekrar dene (Self-Heal)
        if r.status_code != 200:
            base_url = brain.get_live_url(cid, force_refresh=True)
            if not base_url: return Response("Yayin Kirik", status=503)
            r = session.get(urljoin(base_url, "index.m3u8"), headers=HEADERS, verify=False, timeout=6)

        content = r.text
        new_lines = []
        
        # 3. Satırları işle
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                # KRİTİK NOKTA: Linki şifrelemek yerine PARAMETRE olarak geçiyoruz.
                # Böylece link bozulsa bile CID üzerinden onarabiliriz.
                # Örn: /seg?cid=123&file=segment_0.ts
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?cid={cid}&file={line}")

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception:
        return Response("Server Error", status=500)

@app.route('/seg')
def segment_handler():
    # Parametreleri al
    cid = request.args.get('cid')
    file_name = request.args.get('file')
    
    if not cid or not file_name: return "Bad Request", 400

    def stream_video():
        # 3 KEZ DENEME HAKKI (RETRY LOOP)
        for attempt in range(3):
            # 1. Güncel sunucu adresini al
            base_url = brain.get_live_url(cid)
            if not base_url: break
            
            target_url = urljoin(base_url, file_name)
            
            try:
                # 2. Veriyi çekmeyi dene
                with session.get(target_url, headers=HEADERS, verify=False, stream=True, timeout=10) as r:
                    
                    # BAŞARILI İSE (200 OK)
                    if r.status_code == 200:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk: yield chunk
                        return # İşlem tamam, çık
                    
                    # HATA ALDIYSA (403/404)
                    else:
                        # Sunucu ölmüş veya token bitmiş.
                        # Beyne "Bu kanalı yenile!" emri ver.
                        # print(f"[HEAL] Kanal {cid} onariliyor (Hata: {r.status_code})...", file=sys.stderr)
                        brain.get_live_url(cid, force_refresh=True)
                        # Döngü başa dönecek ve YENİ sunucudan dosyayı isteyecek.
                        continue

            except Exception:
                # Bağlantı hatası olursa da yenile
                brain.get_live_url(cid, force_refresh=True)
                time.sleep(0.5)
        
        # 3 denemede de olmazsa
        return

    return Response(stream_with_context(stream_video()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
