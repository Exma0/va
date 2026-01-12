from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import sys

# Hızlı JSON ayrıştırıcı kontrolü
try:
    import ujson as json
except ImportError:
    import json

from gevent import pool
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ---------------------------------------------------------
# AYARLAR VE SABİTLER
# ---------------------------------------------------------
USER_AGENT = "VAVOO/2.6"
SOURCES = [
    "https://vavoo.to"
]

# Çöp toplamayı biraz daha agresif yap (RAM şişmesini engeller)
# Streaming sunucularında nesneler hızlı oluşup ölür.
gc.set_threshold(700, 10, 10)

# SSL Uyarılarını kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# Logları tamamen kapat (Disk I/O tasarrufu)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

# ---------------------------------------------------------
# BAĞLANTI HAVUZU (Connection Pool)
# ---------------------------------------------------------
# Pool size'ı artırdık çünkü video segmentleri çok fazla bağlantı açar.
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=200,   # Aynı anda açık tutulacak host sayısı
    pool_maxsize=500,       # Havuzdaki maksimum bağlantı sayısı
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({
    "User-Agent": USER_AGENT,
    "Connection": "keep-alive"
})

# Video akışı için daha büyük buffer (64KB) - CPU kullanımını düşürür
CHUNK_SIZE = 64 * 1024 

# ---------------------------------------------------------
# YARDIMCI FONKSİYONLAR
# ---------------------------------------------------------

def get_best_live_data():
    """Kanal listesini çeker. Timeout düşürüldü."""
    for src in SOURCES:
        try:
            # Timeout 3sn'ye çekildi, cevap vermiyorsa hızlıca pas geçsin
            url = f"{src}/live2/index"
            r = session.get(url, verify=False, timeout=3)
            if r.status_code == 200:
                return r.json(), src
        except:
            continue
    return None, None

def fetch_playlist_content(cid):
    """M3U8 dosyasını çeker."""
    cid_clean = cid.replace('.m3u8', '')
    for src in SOURCES:
        try:
            url = f"{src}/play/{cid_clean}/index.m3u8"
            r = session.get(url, verify=False, timeout=2.5) # Hızlı failover için timeout düştü
            if r.status_code == 200:
                return r.content, r.url.rsplit('/', 1)[0], src
        except:
            continue
    return None, None, None

# ---------------------------------------------------------
# ROUTE HANDLERS
# ---------------------------------------------------------

@app.route('/')
def root():
    data, working_src = get_best_live_data()
    
    if not data:
        return Response("Kaynaklara erisilemiyor", 503)

    # Host URL'yi bir kez hesapla
    host_b = request.host_url.rstrip('/').encode()
    
    # List comprehension ve önceden tanımlı byte stringler ile hızlandırma
    # String birleştirme işlemi döngü içinde maliyetlidir.
    out_lines = [b"#EXTM3U"]
    
    # Bu döngü CPU bound'dur, optimize edildi.
    for item in data:
        if item.get("group") == "Turkey":
            try:
                # String manipülasyonunu minimize et
                name = item['name'].replace(',', ' ')
                u = item['url']
                # URL parsing işlemini basitleştir
                cid = u.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                
                # F-String yerine encode/bytes birleştirme bazen daha hafiftir ama
                # okunabilirlik için encode edilmiş f-string kullanıyoruz.
                out_lines.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode('utf-8'))
                out_lines.append(host_b + b'/live/' + cid.encode('utf-8') + b'.m3u8')
            except: 
                pass

    return Response(b"\n".join(out_lines), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    content, base_url, used_src = fetch_playlist_content(cid)
    
    if not content:
        return Response("Stream Bulunamadi", 404)

    host_b = request.host_url.rstrip('/').encode()
    base_b = base_url.encode()
    
    out = []
    # splitlines() genellikle split('\n')'den daha güvenlidir ama byte ile çalışıyoruz
    lines = content.split(b'\n')
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            out.append(line)
        else:
            # TS dosyasını yönlendir
            if line.startswith(b'http'):
                target = line
            else:
                target = base_b + b'/' + line
            
            # quote işlemi maliyetlidir, sadece gerekli karakterleri encode edelim
            # safe parametresi ile işlem hızlanır
            safe_target = quote(target, safe='/:?=&').encode()
            out.append(host_b + b'/ts?url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    if not url_enc: return "Bad Request", 400
    
    # unquote işlemi
    original_target = unquote(url_enc)
    
    # Hedef domain tespiti (String işlemi)
    path_part = None
    target_domain = None

    # Hızlı kontrol: Vavoo kaynaklarından biri mi?
    for src in SOURCES:
        if src in original_target:
            target_domain = src
            # Split işlemi CPU harcar, sadece 1 kere yap
            try:
                path_part = original_target.split(src, 1)[1]
            except IndexError:
                pass
            break
            
    # Bilinmeyen kaynaksa proxy'le geç
    if not target_domain:
        return proxy_stream(original_target)

    # 1. Deneme: Orijinal
    try:
        r = session.get(original_target, stream=True, verify=False, timeout=3)
        if r.status_code == 200:
            return Response(stream_with_context(r.iter_content(chunk_size=CHUNK_SIZE)), 
                          content_type="video/mp2t")
        r.close()
    except:
        pass
        
    # 2. Deneme: Failover
    # path_part varsa diğer sunucuları dene
    if path_part:
        for src in SOURCES:
            if src == target_domain: continue
            
            new_target = src + path_part
            try:
                r = session.get(new_target, stream=True, verify=False, timeout=2)
                if r.status_code == 200:
                    return Response(stream_with_context(r.iter_content(chunk_size=CHUNK_SIZE)), 
                                  content_type="video/mp2t")
                r.close()
            except:
                continue

    return Response("Source Error", 502)

def proxy_stream(url):
    try:
        r = session.get(url, stream=True, verify=False, timeout=5)
        return Response(stream_with_context(r.iter_content(chunk_size=CHUNK_SIZE)), 
                        content_type="video/mp2t")
    except:
        return Response("Error", 502)

if __name__ == "__main__":
    print("---------------------------------------")
    print(" ► VAVOO PROXY - TURBO EDITION")
    print(" ► OPTIMIZASYON: UJSON + 64KB CHUNK")
    print(" ► PORT: 8080")
    print("---------------------------------------")
    
    # Spawn pool ile thread limitini kontrol altına alıyoruz.
    # Bu, CPU %100 olduğunda sunucunun kilitlenmesini engeller.
    worker_pool = pool.Pool(1000)
    
    server = WSGIServer(('0.0.0.0', 8080), app, spawn=worker_pool, log=None)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
