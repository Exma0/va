# ==============================================================================
# VAVOO PROXY - SINGULARITY V3 (ANTI-FREEZE EDITION)
# Fix: 0-Byte Segment Detection | Dynamic Source Ban | Stalled Stream Killer
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

# ------------------------------------------------------------------------------
# 1. AYARLAR & MEMORY
# ------------------------------------------------------------------------------
gc.set_threshold(70000, 10, 10)

SOURCES = [
    "https://huhu.to",
    "https://vavoo.to",
    "https://oha.to",
    "https://kool.to"
]

B_NEWLINE = b"\n"
B_EXTM3U = b"#EXTM3U"
MIN_SEGMENT_SIZE = 1024 # 1KB'dan küçük TS dosyası hatalıdır

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
import logging
logging.getLogger('werkzeug').disabled = True
app.logger.disabled = True

# ------------------------------------------------------------------------------
# 2. NETWORK KATMANI
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=1000,
    pool_maxsize=10000,
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
# 3. ZEKİ BEYİN (TOXIC DETECTION)
# ------------------------------------------------------------------------------
class AntiFreezeBrain:
    def __init__(self):
        self.cache = {}         
        self.prefetch = {}      
        self.lock = lock.RLock()
        # Kaynak Puanları (Düşük = İyi)
        self.scores = {src: 10.0 for src in SOURCES}
        # Hatalı Sunucular (Kara Liste)
        self.toxic_sources = {} 
        
        spawn(self._cleaner)

    def _cleaner(self):
        while True:
            sleep(5)
            now = time.time()
            with self.lock:
                # Prefetch temizliği
                expired = [k for k, v in self.prefetch.items() if now - v['ts'] > 15]
                for k in expired: del self.prefetch[k]
                
                # Kara listeden af (30 saniye sonra affet)
                for src in list(self.toxic_sources.keys()):
                    if now - self.toxic_sources[src] > 30:
                        del self.toxic_sources[src]
                        self.scores[src] = 50.0 # Cezalı başlangıç puanı

    def report_toxic(self, source):
        """Sunucuyu zehirli ilan et ve puanını yok et"""
        with self.lock:
            self.toxic_sources[source] = time.time()
            self.scores[source] += 99999.0 # Sonsuz ceza

    def get_best_sources(self):
        """Sadece sağlıklı kaynakları döndür"""
        valid = [s for s in SOURCES if s not in self.toxic_sources]
        if not valid: # Hepsi ölüyse mecburen hepsini aç
            self.toxic_sources.clear()
            valid = SOURCES
        return sorted(valid, key=lambda s: self.scores[s])

    def _speculative_loader(self, ts_url, headers, source):
        """Ön-İndirme (0-Byte kontrolü ile)"""
        try:
            with session.get(ts_url, headers=headers, verify=False, stream=True, timeout=5) as r:
                if r.status_code == 200:
                    data = r.content
                    if len(data) > MIN_SEGMENT_SIZE:
                        with self.lock:
                            self.prefetch[ts_url] = {'data': data, 'ts': time.time()}
                    else:
                        # Boş dosya gönderdi -> BAN
                        self.report_toxic(source)
        except: pass

    def _worker(self, source, cid, result_box):
        try:
            # Zehirli kaynaksa uğraşma
            if source in self.toxic_sources: return

            url = f"{source}/play/{cid}/index.m3u8"
            h = get_headers(source)
            t0 = time.time()
            
            with session.get(url, headers=h, verify=False, timeout=(1.0, 3.0)) as r:
                if r.status_code == 200 and len(r.content) > 100:
                    dt = (time.time() - t0) * 1000
                    self.scores[source] = (self.scores[source] * 0.8) + (dt * 0.2)
                    
                    if not result_box.ready():
                        result_box.set({
                            'source': source,
                            'content': r.content, 
                            'base': r.url.rsplit('/', 1)[0],
                            'headers': h
                        })
                else:
                    self.report_toxic(source)
        except:
            self.report_toxic(source)

    def resolve_playlist(self, cid):
        now = time.time()
        cid = cid.replace('.m3u8', '')

        # Cache valid ise dön
        if cid in self.cache:
            entry = self.cache[cid]
            if now < entry['expires']: return entry['data']

        candidates = self.get_best_sources()[:3] # En iyi 3 kaynağı dene
        
        result_box = event.AsyncResult()
        pool_ = pool.Pool(3)
        for src in candidates:
            pool_.spawn(self._worker, src, cid, result_box)
        
        try:
            winner = result_box.get(timeout=3.5)
            pool_.kill(block=False)
            
            if winner:
                self.cache[cid] = {'expires': now + 300, 'data': winner}
                # TACHYON PRE-FETCH
                try:
                    lines = winner['content'].split(B_NEWLINE)
                    first_ts = None
                    for line in lines:
                        if line and not line.startswith(b'#'):
                            if line.startswith(b'http'): first_ts = line.decode()
                            else: first_ts = f"{winner['base']}/{line.decode()}"
                            break
                    if first_ts:
                        # Kaynak bilgisiyle birlikte gönder ki hata olursa banlayalım
                        spawn(self._speculative_loader, first_ts, winner['headers'], winner['source'])
                except: pass
                return winner
        except:
            pool_.kill(block=False)
        return None

brain = AntiFreezeBrain()

# ------------------------------------------------------------------------------
# 4. ENDPOINTS
# ------------------------------------------------------------------------------

@app.route('/')
def root():
    # En iyi kaynaktan liste al
    best_src = brain.get_best_sources()[0]
    data = None
    try:
        r = session.get(f"{best_src}/live2/index", verify=False, timeout=3)
        if r.status_code == 200: data = r.json()
    except: pass
    
    if not data:
        for src in SOURCES:
            if src == best_src: continue
            try:
                r = session.get(f"{src}/live2/index", verify=False, timeout=3)
                if r.status_code == 200: 
                    data = r.json()
                    break
            except: continue

    if not data: return Response("Service Unavailable", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [B_EXTM3U]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                u = item['url']
                # Parsing Fix
                part = u.split('/play/')[-1]
                if '/' in part: cid = part.split('/')[0]
                else: cid = part.replace('.m3u8', '')
                if '.' in cid: cid = cid.split('.')[0]
                
                if cid:
                    name = item['name'].replace(',', ' ')
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                    out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    clean_cid = cid.replace('.m3u8', '')
    info = brain.resolve_playlist(clean_cid)
    if not info: return Response("Not Found", 404)

    base_b = info['base'].encode()
    host_b = request.host_url.rstrip('/').encode()
    cid_b = clean_cid.encode()
    
    out = [B_EXTM3U, b"#EXT-X-VERSION:3", b"#EXT-X-TARGETDURATION:10"]
    
    for line in info['content'].split(B_NEWLINE):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            if b"EXT-X-KEY" in line: continue
            if not line.startswith(B_EXTM3U) and not line.startswith(b"#EXT-X-TARGET"):
                out.append(line)
        else:
            if line.startswith(b'http'): target = line
            else: target = base_b + b'/' + line
            
            # Kaynak bilgisini (source) URL'e gömüyoruz ki TS handler hangi sunucudan geldiğini bilsin
            # Bu sayede o sunucu hata verirse banlayabiliriz.
            # Ancak URL'i çok uzatmamak için Brain cache'den bulacağız.
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?cid=' + cid_b + b'&url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    cid = request.args.get('cid')
    if not url_enc: return "Bad", 400
    
    target = unquote(url_enc)
    
    # 1. RAM HIT (Tachyon)
    with brain.lock:
        if target in brain.prefetch:
            data = brain.prefetch.pop(target)['data']
            return Response(data, content_type="video/mp2t")

    # Domain bul
    try:
        slash3 = target.find('/', 8)
        origin = target[:slash3]
    except: origin = "https://vavoo.to"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"{origin}/",
        "Origin": origin,
        "Connection": "keep-alive"
    }

    # Hangi kaynağa ait olduğunu bul (Domain eşleştirme)
    # Bu, o kaynağı banlamak için gerekli
    current_source = None
    for s in SOURCES:
        if s in origin:
            current_source = s
            break

    def stream_checked():
        total_bytes = 0
        try:
            # Timeout artırıldı ama read timeout eklendi
            with session.get(target, headers=headers, verify=False, stream=True, timeout=(2, 5)) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            total_bytes += len(chunk)
                            yield chunk
                    
                    # YAYIN SONU KONTROLÜ
                    # Eğer tüm işlem bittiğinde elimizde 1KB'dan az veri varsa -> FAKE SUCCESS
                    if total_bytes < MIN_SEGMENT_SIZE and current_source:
                        brain.report_toxic(current_source)
                else:
                    if current_source: brain.report_toxic(current_source)
        except:
            if current_source: brain.report_toxic(current_source)
            # Hata durumunda Fallback (Yedek Sunucuya Geçiş)
            if cid:
                clean_cid = cid.replace('.m3u8', '')
                # Cache sil ki yeni sunucu bulsun
                if clean_cid in brain.cache: del brain.cache[clean_cid]
                
                # Yeni sunucu bul
                new_info = brain.resolve_playlist(clean_cid)
                if new_info:
                    fname = target.rsplit('/', 1)[-1].split('?')[0]
                    new_target = f"{new_info['base']}/{fname}"
                    # Tekrar dene
                    try:
                        with session.get(new_target, headers=new_info['headers'], verify=False, stream=True, timeout=5) as r2:
                            if r2.status_code == 200:
                                for chunk in r2.iter_content(chunk_size=65536):
                                    yield chunk
                    except: pass

    return Response(stream_with_context(stream_checked()), content_type="video/mp2t")

if __name__ == "__main__":
    print(f" ► VAVOO ANTI-FREEZE V3")
    print(f" ► FEATURE: 0-BYTE SEGMENT BAN SYSTEM")
    print(f" ► LISTENING: 8080")
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535, log=None)
    server.serve_forever()
