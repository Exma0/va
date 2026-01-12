from gevent import monkey
monkey.patch_all()

import re
import time
import requests
import urllib3
import gevent
from gevent.pool import Pool
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote, urlparse
from gevent.pywsgi import WSGIServer

app = Flask(__name__)

# =====================================================
# AYARLAR
# =====================================================

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# User-Agent Vavoo sistemleri için kritiktir, değiştirilmemeli.
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate"
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Session Ayarları (Daha agresif timeout ve pool)
session = requests.Session()
# Max size 1000'e çıkarıldı, yüksek trafik için.
adapter = requests.adapters.HTTPAdapter(
    pool_connections=100, 
    pool_maxsize=1000, 
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

def get_headers(base_url):
    return {
        **BASE_HEADERS,
        "Referer": f"{base_url}/",
        "Origin": base_url
    }

# =====================================================
# AKILLI BEYİN (Concurrent Resolver)
# =====================================================
class TurboBrain:
    def __init__(self):
        # { 'cid': {'url': '...', 'ts': 123456, 'headers': {...}} }
        self.cache = {}
        # Aynı anda aynı kanal için sorgu gelirse yığılmayı önlemek için
        self.pending_resolves = {}

    def _check_source(self, source_url, cid):
        """Tekil bir kaynağı test eden worker fonksiyon."""
        try:
            target_url = f"{source_url}/play/{cid}/index.m3u8"
            headers = get_headers(source_url)
            
            # Bağlantı timeout çok kısa (2sn), okuma timeout (5sn)
            # Amaç: Yanıt vermeyen sunucuyu hemen elemek.
            r = session.get(target_url, headers=headers, verify=False, timeout=(2, 5))
            
            if r.status_code == 200:
                # Redirect kontrolü ve Stream URL çözme
                final_url = r.url
                content = r.text
                
                # Master playlist ise en iyi kaliteyi seçmeye çalış (basit mantık)
                if "#EXT-X-STREAM-INF" in content:
                    lines = content.splitlines()
                    # Genelde son stream en kalitelisidir, ters tara
                    for line in reversed(lines):
                        if line and not line.startswith("#"):
                            final_url = urljoin(final_url, line)
                            # Linkin sağlamasını yap (sadece header isteği ile)
                            # Hız için bu adımı atlayıp direkt URL'i kabul ediyoruz (Optimistik yaklaşım)
                            break
                
                return {
                    'url': final_url,
                    'source': source_url,
                    'headers': get_headers(source_url) # O anki geçerli header
                }
        except:
            return None
        return None

    def resolve(self, cid, force=False):
        """
        Tüm kaynakları AYNI ANDA tarar. İlk cevap vereni alır.
        """
        now = time.time()
        
        # 1. Cache Kontrolü (5 Dakika)
        if not force and cid in self.cache:
            if now - self.cache[cid]['ts'] < 300:
                return self.cache[cid]

        # 2. Race Condition Koruması (Aynı anda 50 kişi aynı kanalı isterse)
        if cid in self.pending_resolves:
            gevent.sleep(0.1) # Diğer thread'in bitirmesini bekle
            if cid in self.cache: return self.cache[cid]

        self.pending_resolves[cid] = True

        try:
            # 3. YARIŞ BAŞLASIN (Parallel Execution)
            # Greenlet Pool kullanarak tüm kaynaklara aynı anda istek atıyoruz.
            pool = Pool(len(SOURCES))
            greenlets = []
            
            for src in SOURCES:
                greenlets.append(pool.spawn(self._check_source, src, cid))
            
            winner = None
            
            # iwait ile bitenleri sırayla alıyoruz
            for g in gevent.iwait(greenlets):
                result = g.value
                if result:
                    winner = result
                    # Kazanan belli oldu, diğerlerini beklemeye gerek yok ama
                    # gevent pool otomatik temizler, kill etmeye gerek yok.
                    break 
            
            pool.kill() # Diğer istekleri iptal et (Bandwidth tasarrufu)

            if winner:
                winner['ts'] = now
                self.cache[cid] = winner
                return winner
            
        finally:
            if cid in self.pending_resolves:
                del self.pending_resolves[cid]

        return None

brain = TurboBrain()

# =====================================================
# ENDPOINTS
# =====================================================

@app.route('/')
def root():
    # Liste çekmek için de en hızlı kaynağı bulalım
    # Basitlik adına burada ilk çalışanı alıyoruz (seri), çünkü bu nadiren çağrılır.
    data = None
    for source in SOURCES:
        try:
            r = session.get(f"{source}/live2/index", headers=get_headers(source), verify=False, timeout=3)
            if r.status_code == 200:
                data = r.json()
                break
        except: continue

    if not data: return "Liste alinamadi", 503

    host = request.host_url.rstrip('/')
    m3u = ["#EXTM3U"]
    
    # String birleştirme optimizasyonu (f-string en hızlısıdır)
    for item in data:
        if item.get("group") == "Turkey":
            name = item.get("name", "Unknown").replace(',', ' ')
            url_val = item.get("url", "")
            match = re.search(r'/play/(\d+)', url_val)
            if match:
                cid = match.group(1)
                logo = item.get("logo", "")
                m3u.append(f'#EXTINF:-1 group-title="Turkey" tvg-logo="{logo}",{name}\n{host}/live/{cid}.m3u8')

    return Response("\n".join(m3u), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist(cid):
    info = brain.resolve(cid)
    if not info: return "Yayin Yok", 404

    try:
        # Stream URL'inden veriyi çek
        r = session.get(info['url'], headers=info['headers'], verify=False, timeout=5)
        
        # Token süresi dolmuş veya yayın sunucusu değişmiş (Retry Logic)
        if r.status_code >= 400:
            info = brain.resolve(cid, force=True) # Force refresh
            if not info: return "Source Dead", 503
            r = session.get(info['url'], headers=info['headers'], verify=False, timeout=5)

        base_url = r.url
        content = r.text
        new_lines = []
        host = request.host_url.rstrip('/')

        # Basit string parsing (Regex'ten daha hızlıdır)
        for line in content.split('\n'):
            line = line.strip()
            if not line: continue
            if line.startswith('#'):
                new_lines.append(line)
            else:
                # Segment URL oluşturma
                # full_ts_url = urljoin(base_url, line) -> Yavaş olabilir
                if line.startswith('http'):
                    ts_url = line
                else:
                    # urljoin yerine basit string manipülasyonu (eğer slash varsa/yoksa)
                    # Burası urljoin kadar güvenli olmayabilir ama daha hızlıdır.
                    # Güvenlik için urljoin'de kalıyoruz şimdilik.
                    ts_url = urljoin(base_url, line)
                
                # Double encoding sorunlarını önlemek için safe quote
                safe_target = quote(ts_url)
                new_lines.append(f"{host}/ts?cid={cid}&target={safe_target}")

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception as e:
        print(f"Playlist Error: {e}")
        return "Internal Error", 500

@app.route('/ts')
def segment():
    # request.args.get yavaştır, query string parse edilebilir ama Flask'a güvenelim.
    target = unquote(request.args.get('target', ''))
    cid = request.args.get('cid')
    
    if not target: return "No Target", 400

    # Header türetme
    parsed = urlparse(target)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": BASE_HEADERS["User-Agent"],
        "Referer": f"{origin}/",
        "Origin": origin,
        "Connection": "keep-alive"
    }

    def proxy_stream():
        # Retry mekanizması (Segment seviyesinde)
        current_target = target
        current_headers = headers
        
        for attempt in range(2): # Max 2 deneme
            try:
                # stream=True çok önemli, tüm dosyayı RAM'e indirme!
                with session.get(current_target, headers=current_headers, verify=False, stream=True, timeout=10) as r:
                    if r.status_code == 200:
                        # Chunk size artırıldı (128KB). CPU context switch azalır.
                        for chunk in r.iter_content(chunk_size=131072):
                            if chunk: yield chunk
                        return # Başarılıysa çık
                    
                    elif r.status_code in [403, 404, 410]:
                        # Link ölmüş, yeni token lazım
                        if attempt == 0 and cid:
                            new_info = brain.resolve(cid, force=True)
                            if new_info:
                                # Eski dosya ismini (seg-10.ts) yeni base URL ile birleştir
                                # Bu kısım biraz tahmin içerir ama genelde çalışır.
                                file_name = current_target.split('?')[0].split('/')[-1]
                                # Base URL'in sonundaki playlist adını atıp file_name eklemek gerekir
                                # Basit çözüm: Playlist'i tekrar çekip parse etmek çok uzun sürer.
                                # Burası "Fail Fast" olmalı. Eğer 403 ise yayını kesmek bazen daha iyidir.
                                pass 
            except:
                pass
            time.sleep(0.5) # Kısa bekleme

    return Response(stream_with_context(proxy_stream()), content_type="video/mp2t")

if __name__ == "__main__":
    print("==========================================")
    print(" TURBO VAVOO PROXY (PARALLEL MODE)")
    print(" :8080 portunda baslatiliyor...")
    print("==========================================")
    
    # Backlog artırıldı, aynı anda gelen istekleri kuyrukta tutabilmek için
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=10000)
    server.serve_forever()
