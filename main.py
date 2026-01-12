# ==============================================================================
# VAVOO PROXY - TITAN V2 (NEURAL EDITION)
# Tech: Reinforcement Learning | Real-Time Flow Analysis | Auto-Optimization
# Status: SELF-AWARE (Kendi Kendini Yöneten)
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import math
import random
from gevent import pool, event, spawn, sleep, lock
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ------------------------------------------------------------------------------
# 1. SİSTEM AYARLARI & BELLEK YÖNETİMİ
# ------------------------------------------------------------------------------
gc.set_threshold(100000, 50, 50)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# Donma Tespiti İçin Eşik Değeri (Byte/Saniye)
# 300KB/s altı = Yüksek Bitrate yayında donma riski
MIN_FREEZE_THRESHOLD = 300 * 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Logları sustur
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK KATMANI (SESSION POOL)
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=2000,
    pool_maxsize=20000,
    max_retries=0,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

HEADERS_MEM = {}
def get_headers(base_url):
    if base_url not in HEADERS_MEM:
        HEADERS_MEM[base_url] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{base_url}/",
            "Origin": base_url,
            "Connection": "keep-alive"
        }
    return HEADERS_MEM[base_url]

# ------------------------------------------------------------------------------
# 3. NEURAL BRAIN (ÖĞRENEN BEYİN)
# ------------------------------------------------------------------------------
class NeuralBrain:
    def __init__(self):
        # Nöral Ağırlıklar (Başlangıçta hepsi eşit: 1.0)
        self.weights = {src: 1.0 for src in SOURCES}
        
        # Stabilite Skoru (Ceza puanı, 0 = Mükemmel)
        self.instability = {src: 0.0 for src in SOURCES}
        
        self.cache = {} 
        self.lock = lock.RLock()
        
        # Arka planda unutma faktörü (Eski hataları zamanla affet)
        spawn(self._memory_decay)

    def _memory_decay(self):
        """Zamanla eski verilerin etkisini azaltır (Adaptasyon)."""
        while True:
            sleep(10)
            with self.lock:
                for src in SOURCES:
                    # Ağırlıkları merkeze (1.0) çek
                    if self.weights[src] > 1.0: self.weights[src] *= 0.98
                    if self.weights[src] < 1.0: self.weights[src] *= 1.02
                    # Cezaları azalt
                    self.instability[src] *= 0.9

    def train(self, source, speed_bps, success=True):
        """
        Reinforcement Learning (Ödül/Ceza Sistemi)
        """
        with self.lock:
            if not success:
                # Ağır Ceza
                self.weights[source] *= 0.5 
                self.instability[source] += 10.0
            else:
                # Hıza göre Ödül
                # 1MB/s üstü = Büyük ödül, Altı = Küçük ödül
                reward = 1.1 if speed_bps > 1000000 else 1.01
                self.weights[source] *= reward
                # Stabiliteyi artır
                self.instability[source] = max(0, self.instability[source] - 0.5)

            # Sınırlandırma (Aşırı uç değerleri engelle)
            self.weights[source] = max(0.1, min(10.0, self.weights[source]))

    def predict_best_source(self):
        """
        Mevcut verilere göre en iyi kaynağı seçer.
        Sadece en yüksek puanlıyı değil, puanı yüksek olanlar arasından
        olasılıksal seçim yapar (Exploration vs Exploitation).
        """
        total_weight = sum(self.weights.values())
        if total_weight == 0: return SOURCES[0]
        
        # Roulette Wheel Selection
        pick = random.uniform(0, total_weight)
        current = 0
        for src, weight in self.weights.items():
            current += weight
            if current > pick:
                return src
        return SOURCES[0]

    def resolve_playlist(self, cid):
        """Playlist bulur ve önbellekler."""
        now = time.time()
        cid = cid.replace('.m3u8', '')
        
        if cid in self.cache:
            entry = self.cache[cid]
            if now < entry['expires']: return entry['data']

        # Neural Tahmin ile Kaynak Seç
        primary = self.predict_best_source()
        # Yedek olarak en yüksek 2. puanlıyı al
        backup = sorted(SOURCES, key=lambda s: self.weights[s], reverse=True)[1]
        
        candidates = [primary, backup] if primary != backup else [primary]
        
        result_box = event.AsyncResult()
        
        def worker(src):
            try:
                url = f"{src}/play/{cid}/index.m3u8"
                h = get_headers(src)
                t0 = time.time()
                with session.get(url, headers=h, verify=False, timeout=2.5) as r:
                    if r.status_code == 200:
                        elapsed = time.time() - t0
                        # Basit bir hız tahmini (Playlist küçük olduğu için)
                        bps = len(r.content) / elapsed
                        self.train(src, bps, True)
                        
                        if not result_box.ready():
                            result_box.set({
                                'content': r.content,
                                'base': r.url.rsplit('/', 1)[0],
                                'headers': h,
                                'source': src
                            })
                    else:
                        self.train(src, 0, False)
            except:
                self.train(src, 0, False)

        pool_ = pool.Pool(len(candidates))
        for src in candidates:
            pool_.spawn(worker, src)
        
        try:
            winner = result_box.get(timeout=3.0)
            pool_.kill(block=False)
            if winner:
                self.cache[cid] = {'expires': now + 300, 'data': winner}
                return winner
        except:
            pool_.kill(block=False)
        return None

brain = NeuralBrain()

# ------------------------------------------------------------------------------
# 4. STREAM HEALTH MONITOR (AKIL YÜRÜTEN AKIŞ KONTROLCÜSÜ)
# ------------------------------------------------------------------------------
class StreamHealthMonitor:
    def __init__(self, source):
        self.source = source
        self.start_time = time.time()
        self.bytes_transferred = 0
        self.last_check = time.time()
        self.last_bytes = 0

    def update(self, chunk_len):
        self.bytes_transferred += chunk_len
        
    def check_health(self):
        """
        Yayının donup donmadığını tespit eder.
        True dönerse her şey yolunda, False dönerse DONMA VAR.
        """
        now = time.time()
        delta = now - self.last_check
        
        # Her 1 saniyede bir kontrol et
        if delta >= 1.0:
            bytes_diff = self.bytes_transferred - self.last_bytes
            speed_bps = bytes_diff / delta
            
            # İstatistikleri güncelle
            self.last_check = now
            self.last_bytes = self.bytes_transferred
            
            # Beyni eğit
            brain.train(self.source, speed_bps, True)
            
            # Donma Kontrolü
            if speed_bps < MIN_FREEZE_THRESHOLD:
                # Ceza ver
                brain.train(self.source, speed_bps, False)
                return False # Dondu!
                
        return True

# ------------------------------------------------------------------------------
# 5. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # En yüksek puanlı kaynaktan listeyi al
    best_src = sorted(SOURCES, key=lambda s: brain.weights[s], reverse=True)[0]
    data = None
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=3)
        if r.status_code == 200: data = r.json()
    except: pass
    
    if not data:
        # Fallback
        for src in SOURCES:
            if src == best_src: continue
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=2)
                if r.status_code == 200: 
                    data = r.json()
                    break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # Güvenli ID Parsing
                part = u.split('/play/')[-1]
                cid = part.split('/')[0].replace('.m3u8', '').split('.')[0]
                
                if cid:
                    name = item['name'].replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    info = brain.resolve_playlist(cid)
    if not info: return Response("Not Found", 404)

    base_b = info['base'].encode()
    host_b = request.host_url.rstrip('/').encode()
    cid_b = cid.replace('.m3u8', '').encode()
    
    out = [b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    for line in info['content'].split(b'\n'):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(b"#EXTM3U") and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            if line.startswith(b'http'): target = line
            else: target = base_b + b'/' + line
            
            safe_target = quote(target).encode()
            # Kaynak bilgisini de URL'e şifreliyoruz (Opsiyonel, şimdilik Brain hallediyor)
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    cid = request.args.get('cid')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    # URL'den domain'i bulup hangi kaynağa ait olduğunu tespit et
    # Bu, nöral ağı eğitmek için gerekli
    origin = "https://vavoo.to" # Varsayılan
    current_source = "https://vavoo.to"
    try:
        temp = target.split('/', 3)
        origin = f"{temp[0]}//{temp[2]}"
        for s in SOURCES:
            if s in origin:
                current_source = s
                break
    except: pass
    
    h = get_headers(origin)

    def smart_stream():
        # Sağlık monitörünü başlat
        monitor = StreamHealthMonitor(current_source)
        
        try:
            # Bağlantı isteği
            with session.get(target, headers=h, verify=False, stream=True, timeout=(2, 6)) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            try:
                                yield chunk
                                # Monitöre veri geldiğini bildir
                                monitor.update(len(chunk))
                                
                                # AKIL YÜRÜTME: Yayın donuyor mu?
                                if not monitor.check_health():
                                    # Yayın yavaşladı! Döngüyü kır ve Fallback'e git
                                    # Bu bir "GeneratorExit" değil, bizim kararımız.
                                    raise Exception("Slow Stream Detected")
                                    
                            except (OSError, IOError):
                                return # İstemci kapattı, normal çıkış.
                else:
                    raise Exception("Bad Status Code")
                    
        except Exception as e:
            # Hata veya Yavaşlık durumunda Fallback (Kurtarma Modu)
            # Eğer CID varsa, başka bir kaynaktan aynı dosyayı bulmaya çalış
            if cid and str(e) != "GeneratorExit":
                # Beyni eğit: Bu kaynak başarısız oldu
                brain.train(current_source, 0, False)
                
                # Cache sil ve yeniden en iyi kaynağı bul
                if cid in brain.cache: del brain.cache[cid]
                new_info = brain.resolve_playlist(cid)
                
                if new_info and new_info['source'] != current_source:
                    # Yeni kaynaktan aynı dosyayı iste
                    fname = target.rsplit('/', 1)[-1].split('?')[0]
                    new_target = f"{new_info['base']}/{fname}"
                    try:
                        h2 = get_headers(new_info['source'])
                        with session.get(new_target, headers=h2, verify=False, stream=True, timeout=5) as r2:
                            if r2.status_code == 200:
                                for chunk in r2.iter_content(chunk_size=65536):
                                    yield chunk
                    except: pass

    return Response(stream_with_context(smart_stream()), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► TITAN V2 - NEURAL EDITION")
    print(f" ► AI: Reinforcement Learning Active")
    print(f" ► PROTECTION: Anti-Freeze Monitor Active")
    # Log: None (Maksimum performans)
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
