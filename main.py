# ==============================================================================
# VAVOO PROXY - TITAN V3 (PREDATOR EDITION)
# Tech: Reinforcement Learning | Real-Time Flow Analysis | Proactive Caching
# Status: PRE-COGNITIVE (Kullanıcıdan Önce Düşünen Sistem)
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
MIN_FREEZE_THRESHOLD = 300 * 1024 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
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
        self.weights = {src: 1.0 for src in SOURCES}
        self.instability = {src: 0.0 for src in SOURCES}
        self.cache = {} 
        self.lock = lock.RLock()
        spawn(self._memory_decay)

    def _memory_decay(self):
        while True:
            sleep(10)
            with self.lock:
                for src in SOURCES:
                    if self.weights[src] > 1.0: self.weights[src] *= 0.98
                    if self.weights[src] < 1.0: self.weights[src] *= 1.02
                    self.instability[src] *= 0.9

    def train(self, source, speed_bps, success=True):
        with self.lock:
            if not success:
                self.weights[source] *= 0.5 
                self.instability[source] += 10.0
            else:
                reward = 1.1 if speed_bps > 1000000 else 1.01
                self.weights[source] *= reward
                self.instability[source] = max(0, self.instability[source] - 0.5)
            self.weights[source] = max(0.1, min(10.0, self.weights[source]))

    def predict_best_source(self):
        total_weight = sum(self.weights.values())
        if total_weight == 0: return SOURCES[0]
        pick = random.uniform(0, total_weight)
        current = 0
        for src, weight in self.weights.items():
            current += weight
            if current > pick:
                return src
        return SOURCES[0]

    def resolve_playlist(self, cid, force_fresh=False):
        """Playlist bulur ve önbellekler."""
        now = time.time()
        cid = cid.replace('.m3u8', '')
        
        # Cache kontrolü (force_fresh False ise)
        if not force_fresh and cid in self.cache:
            entry = self.cache[cid]
            if now < entry['expires']: return entry['data']

        # Neural Tahmin ile Kaynak Seç (Yarış modunda en iyi 2 kaynağı seçer)
        primary = self.predict_best_source()
        # İkinci en iyi kaynağı bul
        backup = sorted(SOURCES, key=lambda s: self.weights[s], reverse=True)[1]
        
        # Eğer force_fresh (Arkaplan taraması) ise, DAHA FAZLA kaynak dene (Max 3)
        if force_fresh:
            candidates = [primary, backup, SOURCES[random.randint(0, len(SOURCES)-1)]]
            candidates = list(set(candidates)) # Tekrar edenleri sil
        else:
            candidates = [primary, backup] if primary != backup else [primary]
        
        result_box = event.AsyncResult()
        
        def worker(src):
            try:
                url = f"{src}/play/{cid}/index.m3u8"
                h = get_headers(src)
                t0 = time.time()
                # Timeout'u kısa tut ki hızlı olan kazansın
                with session.get(url, headers=h, verify=False, timeout=2.0) as r:
                    if r.status_code == 200:
                        elapsed = time.time() - t0
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
            # İlk gelen cevabı al (Yarışın kazananı)
            winner = result_box.get(timeout=2.5)
            pool_.kill(block=False)
            if winner:
                # Cache süresini 5 dakika yap
                self.cache[cid] = {'expires': now + 300, 'data': winner}
                return winner
        except:
            pool_.kill(block=False)
        return None

brain = NeuralBrain()

# ------------------------------------------------------------------------------
# 4. BACKGROUND OPTIMIZER (YENİ ÖZELLİK)
# ------------------------------------------------------------------------------
class BackgroundOptimizer:
    """Sistem boştayken kanalları tarar ve en hızlı CDN'i cache'e atar."""
    def __init__(self):
        self.scanning = True
        spawn(self._run_loop)

    def _get_channel_list(self):
        # Kanal listesini almak için en iyi kaynağı dener
        for src in SOURCES:
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=3)
                if r.status_code == 200: return r.json()
            except: continue
        return []

    def _run_loop(self):
        print(" ► BRAIN: Background Optimizer Engine Started [IDLE MODE]")
        while self.scanning:
            try:
                data = self._get_channel_list()
                if not data:
                    sleep(10)
                    continue

                # Sadece Turkey grubu (Performans için)
                turkey_channels = [
                    item['url'].split('/play/')[-1].split('/')[0].replace('.m3u8', '') 
                    for item in data if item.get("group") == "Turkey"
                ]

                total = len(turkey_channels)
                print(f" ► BRAIN: Analyzing {total} channels for optimal routes...")

                # 5'li gruplar halinde tara (Sunucuyu boğmamak için)
                p = pool.Pool(5) 
                
                for i, cid in enumerate(turkey_channels):
                    # Zaten cache'de varsa ve yeniyse atla
                    if cid in brain.cache:
                        if time.time() < brain.cache[cid]['expires'] - 60:
                            continue

                    p.spawn(brain.resolve_playlist, cid, True)
                    
                    # Her 10 kanalda bir kısa mola ver (CPU'yu rahatlat)
                    if i % 10 == 0: sleep(0.1)
                
                p.join()
                print(" ► BRAIN: Optimization cycle finished. Cache hot & ready.")
                
            except Exception as e:
                print(f" ► BRAIN ERROR: {e}")
            
            # Bir sonraki tam tarama döngüsü için bekle (örn: 3 dakika)
            sleep(180)

# Optimizer'ı başlat
optimizer = BackgroundOptimizer()

# ------------------------------------------------------------------------------
# 5. STREAM HEALTH MONITOR
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
        now = time.time()
        delta = now - self.last_check
        
        if delta >= 1.0:
            bytes_diff = self.bytes_transferred - self.last_bytes
            speed_bps = bytes_diff / delta
            
            self.last_check = now
            self.last_bytes = self.bytes_transferred
            
            brain.train(self.source, speed_bps, True)
            
            if speed_bps < MIN_FREEZE_THRESHOLD:
                brain.train(self.source, speed_bps, False)
                return False 
                
        return True

# ------------------------------------------------------------------------------
# 6. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # Cache'den veya en hızlı kaynaktan listeyi al
    best_src = sorted(SOURCES, key=lambda s: brain.weights[s], reverse=True)[0]
    data = None
    
    # Hızlıca en iyiyi dene
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=2)
        if r.status_code == 200: data = r.json()
    except: pass
    
    # Olmazsa diğerlerini dene
    if not data:
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
    # force_fresh=False -> Normal kullanıcı isteği, önce cache'e bakar
    info = brain.resolve_playlist(cid, force_fresh=False)
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
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    cid = request.args.get('cid')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    origin = "https://vavoo.to"
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
        monitor = StreamHealthMonitor(current_source)
        try:
            with session.get(target, headers=h, verify=False, stream=True, timeout=(2, 6)) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            try:
                                yield chunk
                                monitor.update(len(chunk))
                                if not monitor.check_health():
                                    raise Exception("Slow Stream Detected")
                            except (OSError, IOError):
                                return
                else:
                    raise Exception("Bad Status Code")
                    
        except Exception as e:
            if cid and str(e) != "GeneratorExit":
                brain.train(current_source, 0, False)
                # Cache sil ki bir sonraki istekte en iyi kaynak tekrar aransın
                if cid in brain.cache: del brain.cache[cid]
                
                # FALLBACK MEKANİZMASI (Anlık Kurtarma)
                new_info = brain.resolve_playlist(cid, force_fresh=True)
                if new_info and new_info['source'] != current_source:
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
    print(f" ► TITAN V3 - PREDATOR EDITION")
    print(f" ► AI: Active | PRE-COGNITIVE CACHE: Active")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
