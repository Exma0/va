# ==============================================================================
# VAVOO SINGULARITY: OMEGA (FINAL EDITION)
# Structure: Deobfuscated & Reverse Engineered
# Features: RAID-1 Mirroring | Zombie Detection | Dynamic Header Injection
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import sys
import re
from gevent import pool, event, spawn, sleep, lock, queue, killall
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote, urljoin, urlparse

# ------------------------------------------------------------------------------
# 1. KERNEL & PERFORMANCE TUNING
# ------------------------------------------------------------------------------
# İşletim sistemi seviyesinde thread geçiş hızını artır (Real-time tepki için)
sys.setswitchinterval(0.001)

# Garbage Collector optimizasyonu (Mikro takılmaları önler)
gc.set_threshold(100000, 50, 50)

# Kaynak Havuzu
SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# Validasyon Limiti: 1KB altı video dosyaları "bozuk" kabul edilir
MIN_TS_SIZE = 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)

# Log Kirliliğini Önle (Sadece kritik hatalar)
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. ADVANCED NETWORK STACK
# ------------------------------------------------------------------------------
session = requests.Session()
# Devasa bağlantı havuzu (High Concurrency)
adapter = requests.adapters.HTTPAdapter(
    pool_connections=5000,
    pool_maxsize=50000,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Header Cache (CPU Tasarrufu)
HEADERS_MEM = {}

def get_headers(target_url):
    """
    Dinamik Header Üreticisi:
    İstek atılan URL'in domainini analiz eder ve ona uygun
    Referer/Origin başlıklarını üretir. Vavoo korumasını bu aşar.
    """
    try:
        parsed = urlparse(target_url)
        # Örn: https://cdn5.huhu.to
        origin = f"{parsed.scheme}://{parsed.netloc}"
        
        if origin not in HEADERS_MEM:
            HEADERS_MEM[origin] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": f"{origin}/",
                "Origin": origin,
                "Connection": "keep-alive",
                "Accept-Encoding": "gzip"
            }
        return HEADERS_MEM[origin]
    except:
        # Fallback
        return {
            "User-Agent": "Mozilla/5.0",
            "Connection": "keep-alive"
        }

# ------------------------------------------------------------------------------
# 3. OMEGA BRAIN (MERKEZİ YÖNETİM)
# ------------------------------------------------------------------------------
class OmegaBrain:
    def __init__(self):
        # Kaynak Sağlık Puanları (100 = Mükemmel)
        self.health = {src: 100.0 for src in SOURCES}
        
        # Kanal Bilgisi Önbelleği (Playlist URL, Token vb.)
        self.channel_map = {} 
        
        self.lock = lock.RLock()
        
        # Arka plan iyileştiricisi
        spawn(self._auto_healer)

    def _auto_healer(self):
        """Zamanla kaynakların puanını geri yükler (Affetme Mekanizması)."""
        while True:
            sleep(10)
            with self.lock:
                for src in self.health:
                    if self.health[src] < 100: self.health[src] += 5

    def punish(self, source, amount=20):
        """Hata yapan kaynağı cezalandır."""
        with self.lock:
            self.health[source] -= amount

    def get_best_sources(self):
        """En sağlıklı kaynakları sıralı döndürür."""
        with self.lock:
            return sorted(SOURCES, key=lambda s: self.health[s], reverse=True)

    def resolve_stream(self, cid):
        """
        Kanal ID'sini (CID) alır, tüm kaynakları tarar ve 
        token'lı, yönlendirilmiş (Redirected) son URL'i bulur.
        """
        now = time.time()
        
        # Cache Kontrolü
        if cid in self.channel_map:
            entry = self.channel_map[cid]
            if now < entry['expires']: return entry

        candidates = self.get_best_sources()
        
        for src in candidates:
            try:
                # 1. İstek: Ana sunucuya git
                initial_url = f"{src}/play/{cid}/index.m3u8"
                h = get_headers(initial_url)
                
                # allow_redirects=True: Bizi CDN'e götürür
                r = session.get(initial_url, headers=h, verify=False, timeout=4, allow_redirects=True)
                
                if r.status_code == 200:
                    # İçerik Kontrolü: Gerçekten M3U8 mi?
                    if b"#EXTM3U" in r.content:
                        final_url = r.url # Tokenlı, CDN'li son adres
                        result = {
                            'final_url': final_url,
                            'source_root': src,
                            'content': r.content,
                            'expires': now + 300 # 5 dk geçerli
                        }
                        self.channel_map[cid] = result
                        return result
                    else:
                        self.punish(src, 10) # İçerik bozuk
            except: 
                self.punish(src, 5) # Bağlantı hatası
        
        return None

omega = OmegaBrain()

# ------------------------------------------------------------------------------
# 4. RAID-1 DOWNLOAD ENGINE (HIZ & GÜVENLİK)
# ------------------------------------------------------------------------------
def raid_downloader(target_filename, cid):
    """
    RAID-1 Mantığı:
    Dosyayı en iyi 2 kaynaktan AYNI ANDA ister.
    Kim önce ve SAĞLAM (dolu) veri gönderirse onu kullanıcıya verir.
    Diğerini iptal eder.
    """
    
    # En iyi 2 kaynak
    sources = omega.get_best_sources()[:2]
    
    # Sonuç Kuyruğu
    result_queue = queue.Queue()
    # Bitiş Bayrağı
    stop_event = event.Event()
    
    workers = []

    def worker(src):
        try:
            # URL Tahmini: {src}/play/{cid}/{filename}
            # Bu yapı %99 Vavoo klonlarında standarttır.
            real_url = f"{src}/play/{cid}/{target_filename}"
            h = get_headers(real_url)
            
            # Bağlan
            with session.get(real_url, headers=h, verify=False, stream=True, timeout=(2, 6)) as r:
                if r.status_code == 200:
                    # 0-Byte Dedektörü
                    first_chunk = next(r.iter_content(chunk_size=4096), None)
                    
                    if first_chunk and len(first_chunk) > 0:
                        # Kazandık!
                        if not stop_event.is_set():
                            # İlk parçayı ve stream objesini kuyruğa at
                            result_queue.put((first_chunk, r))
                            stop_event.set() # Diğerlerini durdur
                    else:
                        # Boş dosya -> Zombi Sunucu
                        omega.punish(src, 50)
                else:
                    omega.punish(src, 10)
        except:
            omega.punish(src, 10)

    # İşçileri Ateşle
    for s in sources:
        workers.append(spawn(worker, s))

    # Sonucu Bekle
    try:
        # 6 saniye içinde veri gelmezse Fallback'e git
        first_chunk, r_stream = result_queue.get(timeout=6)
        
        # Diğer işçileri temizle (Memory Leak önlemi)
        killall(workers, block=False)
        
        # Veriyi Akıt
        yield first_chunk
        # Geri kalanı akıt
        try:
            for chunk in r_stream.iter_content(chunk_size=65536):
                if chunk: yield chunk
        except: pass
        
    except queue.Empty:
        # HİÇBİR KAYNAK CEVAP VERMEDİ -> FALLBACK MODE
        killall(workers, block=False)
        
        # Son Çare: Cache'i sil ve orijinal imzalı URL'i bulmaya çalış
        if cid in omega.channel_map: del omega.channel_map[cid]
        info = omega.resolve_stream(cid)
        
        if info:
            # Base URL + Filename
            base = info['final_url'].rsplit('/', 1)[0]
            fallback_url = f"{base}/{target_filename}"
            try:
                h = get_headers(fallback_url)
                with session.get(fallback_url, headers=h, verify=False, stream=True, timeout=8) as r:
                    if r.status_code == 200:
                        for chunk in r.iter_content(chunk_size=65536):
                            yield chunk
            except: pass

# ------------------------------------------------------------------------------
# 5. ENDPOINTS (API)
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # En iyi kaynaktan listeyi çek
    best = omega.get_best_sources()[0]
    data = None
    try:
        r = session.get(f"{best}/live2/index", verify=False, timeout=3)
        if r.status_code == 200: data = r.json()
    except: pass
    
    # Eğer en iyi kaynak çökmüşse diğerlerini dene
    if not data:
        for s in SOURCES:
            if s == best: continue
            try:
                r = session.get(f"{s}/live2/index", verify=False, timeout=2)
                if r.status_code == 200: data = r.json(); break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # Sağlam ID Ayıklama (Regex'siz, hızlı string işlemi)
                if '/play/' in u:
                    # .../play/12345/index.m3u8 veya .../play/12345.m3u8
                    part = u.split('/play/')[-1]
                    
                    if '/' in part: cid = part.split('/')[0]
                    else: cid = part.replace('.m3u8', '')
                    
                    # Nokta vs temizle
                    cid = cid.split('.')[0]
                    
                    if cid.isdigit():
                        name = item['name'].replace(',', ' ')
                        out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                        out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    # Çift uzantı koruması
    clean_cid = cid.split('.')[0]
    
    info = omega.resolve_stream(clean_cid)
    if not info: return Response("Not Found", 404)

    host_b = request.host_url.rstrip('/').encode()
    cid_b = clean_cid.encode()
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    # Playlist'i satır satır işle
    for line in info['content'].split(b'\n'):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue # Şifre varsa atla (Vavoo şifresizdir)
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            # Bu bir TS linkidir
            line_str = line.decode()
            
            # Sadece dosya ismini al (örn: seg-50.ts veya 6964.ts)
            # URL'in geri kalanını atıyoruz çünkü RAID motoru
            # en hızlı sunucuyu kendisi seçecek.
            if line_str.startswith('http'):
                filename = line_str.split('/')[-1]
            else:
                filename = line_str
                
            # Query string (token) varsa temizle
            filename = filename.split('?')[0]
            
            safe_target = quote(filename).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    # Parametreler: url=dosya_ismi, cid=kanal_id
    filename_enc = request.args.get('url')
    cid = request.args.get('cid')
    
    if not filename_enc or not cid: return "Bad", 400
    
    filename = unquote(filename_enc)
    
    # RAID motorunu çalıştır
    return Response(stream_with_context(raid_downloader(filename, cid)), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO SINGULARITY: OMEGA")
    print(f" ► ARCHITECTURE: RAID-1 MIRRORING")
    print(f" ► PROTECTION: ZOMBIE SERVER DETECTION")
    print(f" ► LISTENING: 8080")
    
    # Gevent WSGI Sunucusu
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
