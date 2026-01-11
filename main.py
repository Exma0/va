from gevent import monkey
monkey.patch_all()

import re
import requests
import time
import gevent
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote

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

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200, max_retries=2)
session.mount('http://', adapter)
session.mount('https://', adapter)

# =====================================================
# AKILLI YAYIN YÖNETİCİSİ (BRAIN)
# =====================================================
class StreamManager:
    def __init__(self):
        # { 'cid': {'url': '...', 'last_check': 123456, 'is_active': True} }
        self.streams = {}
    
    def get_url(self, cid):
        """Aktif en iyi URL'yi döndürür"""
        if cid in self.streams:
            self.streams[cid]['is_active'] = True # İzleniyor işareti
            return self.streams[cid]['url']
        return None

    def update_url(self, cid, new_url):
        """Yeni sunucu bulunduğunda günceller"""
        if cid not in self.streams:
            self.streams[cid] = {'url': new_url, 'last_check': time.time(), 'is_active': True}
        else:
            # Sadece URL değiştiyse güncelle
            if self.streams[cid]['url'] != new_url:
                print(f"[HOT-SWAP] Kanal {cid} icin yeni sunucuya gecildi!", file=sys.stderr)
                self.streams[cid]['url'] = new_url
            self.streams[cid]['last_check'] = time.time()

manager = StreamManager()

# =====================================================
# ARKA PLAN İŞÇİSİ (GÖLGE AVCI)
# =====================================================
def background_healer():
    """
    Her 5 saniyede bir çalışır.
    Aktif izlenen kanalları kontrol eder.
    Mevcut sunucu yavaşsa veya ölüyse yenisini bulur.
    """
    import sys
    while True:
        gevent.sleep(5) # 5 Saniye bekle
        
        # Aktif olan kanalları tara
        # (Listeyi kopyalıyoruz ki döngü sırasında hata olmasın)
        active_cids = [cid for cid, data in manager.streams.items() if data.get('is_active')]
        
        for cid in active_cids:
            # Eğer son 10 saniyedir kimse izlemiyorsa kontrolü bırak (CPU tasarrufu)
            # Burada basitleştirilmiş mantık kullanıyoruz, normalde last_access lazım.
            
            try:
                # 1. Mevcut URL'yi kontrol et (Hızlı HEAD isteği)
                current_url = manager.streams[cid]['url']
                try:
                    r = session.head(current_url, headers=HEADERS, timeout=3)
                    if r.status_code == 200:
                        # Sunucu hala sağlıklı, devam et
                        continue
                except:
                    pass # Hata verdiyse aşağı devam et ve yenisini bul

                # 2. Sunucu Ölmüş veya Yavaş! Yenisini Bul (Resolve)
                print(f"[FIX] Kanal {cid} icin sunucu yenileniyor...", file=sys.stderr)
                
                # Vavoo ana kaynağına tekrar sor
                base_vavoo = f"https://vavoo.to/play/{cid}/index.m3u8"
                r = session.get(base_vavoo, headers=HEADERS, timeout=5, allow_redirects=True)
                
                if r.status_code == 200:
                    final_url = r.url
                    content = r.text
                    
                    # En iyi kaliteyi bul
                    if "#EXT-X-STREAM-INF" in content:
                        lines = content.splitlines()
                        for line in reversed(lines):
                            if line and not line.startswith("#"):
                                final_url = urljoin(final_url, line)
                                break
                    
                    # 3. YÖNETİCİYİ GÜNCELLE (HOT SWAP)
                    manager.update_url(cid, final_url)
                    
            except Exception as e:
                print(f"[ERR] Background check fail for {cid}: {e}", file=sys.stderr)

# İşçiyi başlat
gevent.spawn(background_healer)

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

    base_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    pattern = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
    
    for m in pattern.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        id_match = re.search(r'/play/(\d+)', m.group(2))
        if id_match:
            cid = id_match.group(1)
            # Linkler /playlist/ID.m3u8 formatında
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base_url}/playlist/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/playlist/<cid>.m3u8')
def playlist_proxy(cid):
    # 1. Yöneticiden en güncel URL'yi iste
    current_url = manager.get_url(cid)
    
    # Eğer yöneticide yoksa (ilk açılış), manuel bul ve kaydet
    if not current_url:
        vavoo_url = f"https://vavoo.to/play/{cid}/index.m3u8"
        try:
            r = session.get(vavoo_url, headers=HEADERS, verify=False, timeout=8, allow_redirects=True)
            if r.status_code != 200: return Response("Yayin Yok", status=404)
            
            final_url = r.url
            content = r.text
            
            if "#EXT-X-STREAM-INF" in content:
                lines = content.splitlines()
                for line in reversed(lines):
                    if line and not line.startswith("#"):
                        final_url = urljoin(final_url, line)
                        # İçeriği de güncellememiz lazım ki aşağıda parse edebilelim
                        r2 = session.get(final_url, headers=HEADERS, timeout=8)
                        content = r2.text
                        break
            
            manager.update_url(cid, final_url)
            current_url = final_url
        except:
            return Response("Server Error", status=500)
    else:
        # Cache'deki URL'den içeriği çek
        try:
            r = session.get(current_url, headers=HEADERS, timeout=5)
            content = r.text
        except:
            # Eğer kayıtlı URL çalışmıyorsa hemen yenilemeyi dene
            # (Burada basitçe hata dönüyoruz, retry eklenebilir)
            return Response("Refresh Needed", status=503)

    # 2. M3U8 İçeriğini Düzenle
    # Burası kritik: Kullanıcıya HER ZAMAN o anki en iyi URL'den
    # gelen segmentleri sunuyoruz.
    base_ts = current_url.rsplit('/', 1)[0] + '/'
    new_lines = []
    
    for line in content.splitlines():
        line = line.strip()
        if not line: continue
        
        if line.startswith("#"):
            new_lines.append(line)
        else:
            full_ts = urljoin(base_ts, line)
            enc_url = quote(full_ts)
            new_lines.append(f"{request.host_url.rstrip('/')}/seg?url={enc_url}")

    return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

@app.route('/seg')
def segment_proxy():
    target_url = unquote(request.args.get('url'))
    if not target_url: return "No URL", 400

    def generate():
        try:
            with session.get(target_url, headers=HEADERS, verify=False, stream=True, timeout=15) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: yield chunk
        except:
            pass

    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    import sys
    # Arka plan işçisinin çalışması için gevent WSGI kullanılmalı veya
    # Gunicorn ile çalıştırılmalı.
    app.run(host="0.0.0.0", port=8080, threaded=True)
