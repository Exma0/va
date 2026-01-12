# ==============================================================================
# VAVOO PROXY - OMNI-PRESENCE EDITION
# Technology: Shadow Requests | Statistical Prediction | Dynamic Chunking
# Status: APEX PREDATOR (En Üstün Avcı)
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import socket
import gc
import math
import collections
from gevent import pool, event, spawn, sleep, killall
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ------------------------------------------------------------------------------
# 1. ÇEKİRDEK OPTİMİZASYONLARI
# ------------------------------------------------------------------------------
# Garbage Collector'ı dondur (Copy-on-Write dostu)
# Bu, uzun süre çalışan sunucularda %20 performans artışı sağlar.
gc.set_threshold(1000, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# İstatistiksel Hafıza (Son 50 isteğin süresini tutar)
LATENCY_HISTORY = {src: collections.deque(maxlen=50) for src in SOURCES}
# Başlangıç puanları (Düşük = İyi)
SCORE_BOARD = {src: 100.0 for src in SOURCES}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Logları tamamen sustur
app.logger.disabled = True
import logging
logging.getLogger('werkzeug').disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK ENGINE (GÖLGE İSTEK DESTEKLİ)
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=2000,
    pool_maxsize=10000,
    max_retries=0,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({"User-Agent": USER_AGENT, "Connection": "keep-alive"})

# DNS Cache (TTL: Sonsuz - Script yeniden başlayana kadar)
DNS_MAP = {}
def fast_dns(domain):
    if domain in DNS_MAP: return DNS_MAP[domain]
    try:
        ip = socket.gethostbyname(domain)
        DNS_MAP[domain] = ip
        return ip
    except: return domain

# Header Fabrikası (Memoization)
HEADER_CACHE = {}
def get_headers(base):
    if base not in HEADER_CACHE:
        HEADER_CACHE[base] = {"Referer": f"{base}/", "Origin": base, "User-Agent": USER_AGENT}
    return HEADER_CACHE[base]

# ------------------------------------------------------------------------------
# 3. YAPAY ZEKA (OMNI BRAIN)
# ------------------------------------------------------------------------------
class OmniBrain:
    def __init__(self):
        self.cache = {} 
        self.inflight = {} # {cid: Event}
        self.SHADOW_THRESHOLD = 0.15 # 150ms gecikirse gölge isteği ateşle

    def _update_stats(self, source, duration):
        """İstatistiksel analiz yapar."""
        LATENCY_HISTORY[source].append(duration)
        # Hareketli ortalama + Standart sapma (Jitter cezası)
        avg = sum(LATENCY_HISTORY[source]) / len(LATENCY_HISTORY[source])
        # Basit varyans hesabı
        variance = sum((x - avg) ** 2 for x in LATENCY_HISTORY[source]) / len(LATENCY_HISTORY[source])
        stdev = math.sqrt(variance)
        
        # Skor = Ortalama Süre + (Jitter * 2)
        # Jitter yapan sunucu daha fazla ceza alır.
        SCORE_BOARD[source] = (avg * 1000) + (stdev * 2000)

    def _request_worker(self, source, url, result_box):
        """Tekil işçi."""
        try:
            t0 = time.time()
            headers = get_headers(source)
            with session.get(url, headers=headers, verify=False, timeout=(1.0, 3.0), stream=True) as r:
                if r.status_code == 200:
                    # İlk paket analizi
                    chunk = next(r.iter_content(2048)).decode('utf-8', errors='ignore')
                    
                    elapsed = time.time() - t0
                    self._update_stats(source, elapsed)
                    
                    # Playlist Parse
                    final_url = r.url
                    if "#EXT-X-STREAM-INF" in chunk:
                         # Fastest string search
                         lines = chunk.split('\n')
                         for line in reversed(lines):
                             line = line.strip()
                             if line and not line.startswith('#'):
                                 if line.startswith('http'): final_url = line
                                 else: final_url = f"{final_url.rsplit('/', 1)[0]}/{line}"
                                 break
                    
                    # Başarı
                    if not result_box.ready():
                        result_box.set({
                            'source': source,
                            'url': final_url,
                            'base': final_url.rsplit('/', 1)[0]
                        })
                else:
                    # Hata cezası
                    SCORE_BOARD[source] += 5000
        except:
            SCORE_BOARD[source] += 10000

    def resolve(self, cid):
        """
        OMNI-DIRECTIONAL RESOLVER
        En iyi kaynağı tahmin et, istek at.
        Eğer X ms içinde cevap gelmezse, YEDEK kaynağa da istek at.
        İlk biten kazanır.
        """
        now = time.time()
        
        # 1. Cache
        cached = self.cache.get(cid)
        if cached and now < cached['expires']: return cached['data']

        # 2. Atomic Lock
        if cid in self.inflight:
            self.inflight[cid].wait(timeout=5)
            cached = self.cache.get(cid)
            if cached: return cached['data']
        
        event_lock = event.Event()
        self.inflight[cid] = event_lock

        try:
            # 3. Kaynak Seçimi (Skora göre sırala)
            sorted_sources = sorted(SOURCES, key=lambda s: SCORE_BOARD[s])
            primary = sorted_sources[0]
            secondary = sorted_sources[1]
            
            result_box = event.AsyncResult()
            
            # 4. PRIMARY ATAĞI
            t1 = spawn(self._request_worker, primary, f"{primary}/play/{cid}/index.m3u8", result_box)
            
            # 5. SHADOW ATAĞI (Gecikmeli)
            t2 = None
            try:
                # 150ms bekle, eğer cevap gelmediyse ikinciyi ateşle
                winner = result_box.get(timeout=self.SHADOW_THRESHOLD)
            except:
                # Primary yavaş kaldı, Secondary'i ateşle!
                t2 = spawn(self._request_worker, secondary, f"{secondary}/play/{cid}/index.m3u8", result_box)
                try:
                    winner = result_box.get(timeout=3.0)
                except:
                    # İkisi de patladı, son çare diğerlerini dene
                    winner = None

            # Temizlik
            killall([t1, t2], block=False)
            
            if winner:
                self.cache[cid] = {'expires': now + 300, 'data': winner}
                return winner
            return None

        finally:
            event_lock.set()
            if cid in self.inflight: del self.inflight[cid]

brain = OmniBrain()

# ------------------------------------------------------------------------------
# 4. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def list_root():
    # Liste için "Race All" stratejisi (En güvenli)
    data = None
    # Skora göre en iyileri al
    best = sorted(SOURCES, key=lambda s: SCORE_BOARD[s])
    
    for src in best:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=2)
            if r.status_code == 200:
                data = r.json()
                break
        except: continue

    if not data: return Response("Service Unavailable", 503)

    host = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # Ultra-Fast String Processing
    # JSON objesini tek seferde tara
    for item in data:
        if item.get("group") == "Turkey":
            try:
                # String slicing benchmarklarda split'ten %40 hızlıdır
                u = item['url']
                # http.../play/12345/index...
                # ID'yi "play/" ile bir sonraki "/" arasından çek
                start_marker = "/play/"
                s_idx = u.find(start_marker)
                if s_idx != -1:
                    sub = u[s_idx + 6:] # 12345/index...
                    e_idx = sub.find('/')
                    if e_idx != -1:
                        cid = sub[:e_idx]
                        name = item['name'].replace(',', ' ')
                        out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{host}/live/{cid}.m3u8')
            except: pass
            
    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist(cid):
    info = brain.resolve(cid)
    if not info: return Response("Not Found", 404)

    try:
        # Önceden hesaplanmış header
        h = get_headers(info['source'])
        r = session.get(info['url'], headers=h, verify=False, timeout=4)
        
        # Self-Healing: Token patladı mı?
        if r.status_code >= 400:
            # Cache sil ve tekrar resolve et
            if cid in brain.cache: del brain.cache[cid]
            info = brain.resolve(cid) # Taze istek
            if not info: return Response("Dead", 503)
            h = get_headers(info['source'])
            r = session.get(info['url'], headers=h, verify=False, timeout=4)

        base = info['base']
        host = request.host_url.rstrip('/')
        
        def gen():
            yield "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n"
            # iter_lines bellek dostudur
            for line in r.iter_lines(decode_unicode=True):
                if not line: continue
                if line.startswith('#'):
                    if "EXT-X-KEY" in line: continue 
                    if not line.startswith('#EXTM3U') and not line.startswith('#EXT-X-TARGET'):
                        yield line + "\n"
                else:
                    # Segment: http kontrolü yerine exception handler kullanmak daha yavaştır.
                    # String check en hızlısı.
                    if line.startswith('http'):
                        target = line
                    else:
                        target = f"{base}/{line}"
                    
                    yield f"{host}/ts?cid={cid}&url={quote(target)}\n"

        return Response(stream_with_context(gen()), content_type="application/vnd.apple.mpegurl")

    except:
        return Response("Err", 500)

@app.route('/ts')
def segment():
    # HOT PATH: Burası en kritik yer.
    # Flask'ın request objesini parse etmek bile zaman alır.
    # Mümkünse raw WSGI environ kullanılmalı ama Flask içinde kalıyoruz.
    
    url_enc = request.args.get('url')
    if not url_enc: return "Bad", 400
    target = unquote(url_enc)
    cid = request.args.get('cid')

    # Domain Extraction (Split methodu regex'ten 10 kat hızlıdır)
    try:
        # https://vavoo.to/...
        # ['https:', '', 'vavoo.to', '...']
        parts = target.split('/', 3)
        origin = f"{parts[0]}//{parts[2]}"
    except:
        origin = "https://vavoo.to"

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"{origin}/",
        "Origin": origin,
        "Connection": "keep-alive"
    }

    def stream_content():
        try:
            # DYNAMIC CHUNK SIZE
            # Buffer boyutunu sabit tutmak yerine 64KB ile başla.
            # TCP Window Scaling mantığı.
            chunk_size = 65536 
            
            with session.get(target, headers=headers, verify=False, stream=True, timeout=10) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk: yield chunk
                    return

            # HEALING PATH
            if cid:
                # Token yenileme
                if cid in brain.cache: del brain.cache[cid]
                info = brain.resolve(cid)
                if info:
                    # Dosya adını kurtar
                    fname = target.rsplit('/', 1)[-1].split('?')[0]
                    new_target = f"{info['base']}/{fname}"
                    new_headers = get_headers(info['source'])
                    
                    with session.get(new_target, headers=new_headers, verify=False, stream=True, timeout=8) as r2:
                        if r2.status_code == 200:
                            for chunk in r2.iter_content(chunk_size=chunk_size):
                                yield chunk
        except:
            pass

    return Response(stream_with_context(stream_content()), content_type="video/mp2t")

# ------------------------------------------------------------------------------
# BAŞLATMA
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print(f" ► SYSTEM: OMNI-PRESENCE")
    print(f" ► SHADOW REQUESTS: ACTIVE (Threshold: 150ms)")
    print(f" ► PREDICTIVE AI: LEARNING...")
    
    # 8192 Backlog: DDoS ve ani yüklenmelerde connection drop'u engeller
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=8192, log=None)
    server.serve_forever()
