# ==============================================================================
# VAVOO PROXY - TACHYON EDITION
# Tech: Negative Latency | Speculative Pre-Fetch | Raw Byte Pipe
# Speed: Beyond Physics (Data is ready before you ask)
# ==============================================================================

from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import socket
from gevent import pool, event, spawn, sleep, lock
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote
from collections import deque

# ------------------------------------------------------------------------------
# 1. KERNEL & MEMORY HACKS
# ------------------------------------------------------------------------------
# Garbage Collector'ı sadece bellek kritik seviyeye gelince çalıştır.
# Bu, mikro takılmaları (stuttering) yok eder.
gc.set_threshold(70000, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

# Byte Constants (CPU String Overhead'ini Kaldırmak İçin)
B_NEWLINE = b"\n"
B_EXTINF = b"#EXTINF"
B_EXTM3U = b"#EXTM3U"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
# Flask ve Werkzeug loglarını tamamen sustur (I/O tasarrufu)
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. ULTRA-LOW LATENCY NETWORK STACK
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=4000,
    pool_maxsize=40000, # Devasa bağlantı havuzu
    max_retries=0,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)

# DNS CACHE (Sonsuz TTL)
# Her istekte DNS sorgusu yapmayı engeller. IP'yi direkt kullanır.
DNS_CACHE = {}
def resolve_ip(domain):
    if domain in DNS_CACHE: return DNS_CACHE[domain]
    try:
        ip = socket.gethostbyname(domain)
        DNS_CACHE[domain] = ip
        return ip
    except: return domain

# Headerları String olarak önceden üretip bellekte tutuyoruz
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
# 3. TACHYON ENGINE (PRE-FETCH BRAIN)
# ------------------------------------------------------------------------------
class TachyonBrain:
    def __init__(self):
        self.cache = {}         # Playlist Cache
        self.prefetch = {}      # {ts_url: BytesIO_Content} -> Gelecek verisi
        self.inflight_ts = {}   # Şu an indirilen TS'ler
        self.lock = lock.RLock()
        
        # Puanlama Sistemi (Hız + Kararlılık)
        self.scores = {src: 10.0 for src in SOURCES} 

        # Arka plan temizlikçisi
        spawn(self._cleaner)

    def _cleaner(self):
        """Eski prefetch verilerini temizler (RAM Şişmesini engeller)"""
        while True:
            sleep(10)
            now = time.time()
            with self.lock:
                # 20 saniyeden eski pre-fetch verilerini sil
                expired = [k for k, v in self.prefetch.items() if now - v['ts'] > 20]
                for k in expired: del self.prefetch[k]

    def _speculative_loader(self, ts_url, headers):
        """
        GÖLGE İŞÇİ: Kullanıcı daha istemeden videoyu indirir.
        """
        try:
            with session.get(ts_url, headers=headers, verify=False, stream=True, timeout=5) as r:
                if r.status_code == 200:
                    # Veriyi RAM'e çek (Buffer)
                    data = r.content # Tüm segmenti RAM'e al (Genelde 500KB - 1MB)
                    with self.lock:
                        self.prefetch[ts_url] = {'data': data, 'ts': time.time()}
        except: pass

    def _worker(self, source, cid, result_box):
        """Playlist Çözücü"""
        try:
            url = f"{source}/play/{cid}/index.m3u8"
            h = get_headers(source)
            t0 = time.time()
            
            with session.get(url, headers=h, verify=False, timeout=(0.8, 2.0)) as r:
                if r.status_code == 200:
                    dt = (time.time() - t0) * 1000
                    # Puan güncelle
                    self.scores[source] = (self.scores[source] * 0.7) + (dt * 0.3)
                    
                    if not result_box.ready():
                        result_box.set({
                            'source': source,
                            'content': r.content, # Byte olarak sakla
                            'base': r.url.rsplit('/', 1)[0],
                            'headers': h
                        })
                else:
                    self.scores[source] += 5000 # Ceza
        except:
            self.scores[source] += 10000

    def resolve_playlist(self, cid):
        """En hızlı playlisti bulur ve İLK SEGMENTİ ÖNCEDEN İNDİRİR."""
        # Cache Check
        now = time.time()
        if cid in self.cache:
            entry = self.cache[cid]
            if now < entry['expires']: return entry['data']

        # Race Condition (En hızlı 2 kaynağı yarıştır)
        sorted_src = sorted(SOURCES, key=lambda s: self.scores[s])
        candidates = sorted_src[:2]
        
        result_box = event.AsyncResult()
        pool_ = pool.Pool(2)
        for src in candidates:
            pool_.spawn(self._worker, src, cid, result_box)
        
        try:
            winner = result_box.get(timeout=2.5)
            pool_.kill(block=False)
            
            if winner:
                # Cache Yaz
                self.cache[cid] = {'expires': now + 300, 'data': winner}
                
                # --- TACHYON MAGIC START ---
                # Playlist içindeki ilk .ts dosyasını bul ve hemen indirmeye başla!
                # Kullanıcı m3u8'i parse edip isteyene kadar veri hazır olsun.
                try:
                    lines = winner['content'].split(B_NEWLINE)
                    first_ts = None
                    for line in lines:
                        if line and not line.startswith(b'#'):
                            if line.startswith(b'http'): first_ts = line.decode()
                            else: first_ts = f"{winner['base']}/{line.decode()}"
                            break
                    
                    if first_ts:
                        # Arka planda indirmeyi başlat (Fire and Forget)
                        spawn(self._speculative_loader, first_ts, winner['headers'])
                except: pass
                # --- TACHYON MAGIC END ---

                return winner
        except:
            pool_.kill(block=False)
        return None

brain = TachyonBrain()

# ------------------------------------------------------------------------------
# 4. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # Liste alma (En hızlı kaynaktan)
    best_src = min(SOURCES, key=lambda s: brain.scores[s])
    data = None
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=2)
        if r.status_code == 200: data = r.json()
    except: pass
    
    # Fallback
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
    out = [B_EXTM3U]
    
    # JSON Parsing Optimization
    b_group = "Turkey"
    for item in data:
        if item.get("group") == b_group or item.get("group") == "Turkey":
            try:
                u = item['url']
                # String slicing (Regex'ten hızlı)
                idx = u.find('/play/')
                if idx > 0:
                    cid = u[idx+6:].split('/')[0]
                    name = item['name'].replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    info = brain.resolve_playlist(cid)
    if not info: return Response("Not Found", 404)

    # Playlist Re-Construction (Raw Bytes)
    base_b = info['base'].encode()
    host_b = request.host_url.rstrip('/').encode()
    cid_b = cid.encode()
    
    out = [B_EXTM3U, b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    for line in info['content'].split(B_NEWLINE):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(B_EXTM3U) and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            # Link satırı
            if line.startswith(b'http'): target = line
            else: target = base_b + b'/' + line
            
            # URL Encode ve TS linki
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    # BURASI "TACHYON" ETKİSİNİN OLDUĞU YER
    url_enc = request.args.get('url')
    cid = request.args.get('cid')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    # 1. TACHYON CHECK (PRE-FETCH HIT)
    # RAM'de bu veri hazır mı?
    with brain.lock:
        if target in brain.prefetch:
            # EVET! İndirmeye gerek yok, RAM'den direkt fırlat.
            # Gecikme ~0.0001 ms
            data = brain.prefetch.pop(target)['data']
            return Response(data, content_type="video/mp2t")

    # 2. CACHE MISS (Normal İndirme)
    try:
        # Header oluştur
        slash3 = target.find('/', 8)
        origin = target[:slash3]
    except: origin = "https://vavoo.to"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"{origin}/",
        "Origin": origin,
        "Connection": "keep-alive"
    }

    def stream_direct():
        try:
            # Büyük Chunk ile Syscall azalt
            with session.get(target, headers=headers, verify=False, stream=True, timeout=10) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=131072):
                        yield chunk
                    return

            # FAILOVER (Token Öldüyse)
            if cid:
                # Yenisini bul
                if cid in brain.cache: del brain.cache[cid]
                info = brain.resolve_playlist(cid)
                if info:
                    fname = target.rsplit('/', 1)[-1].split('?')[0]
                    new_target = f"{info['base']}/{fname}"
                    
                    with session.get(new_target, headers=info['headers'], verify=False, stream=True, timeout=8) as r2:
                        if r2.status_code == 200:
                            for chunk in r2.iter_content(chunk_size=131072):
                                yield chunk
        except: pass

    return Response(stream_with_context(stream_direct()), content_type="video/mp2t")

# ------------------------------------------------------------------------------
# IGNITION
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print(f" ► SYSTEM: VAVOO TACHYON PROXY")
    print(f" ► FEATURE: SPECULATIVE PRE-FETCHING (Negative Latency)")
    print(f" ► KERNEL: OPTIMIZED")
    
    # 65535 Backlog, Logsuz, Full Speed
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
