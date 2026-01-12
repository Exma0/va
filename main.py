from gevent import monkey
monkey.patch_all()

import requests
import urllib3
import gc
from gevent import pool
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote
from collections import OrderedDict # RAM Cache yönetimi için eklendi

try:
    import ujson as json
except ImportError:
    import json

SOURCES = [
    "https://vavoo.to"
]

USER_AGENT = "VAVOO/3.1.20"
PORT = 8080

# --- RAM AYARLARI ---
# Hafızada kaç adet .ts dosyası tutulacak? 
# Ortalama 1 ts dosyası 1-2 MB'dır. 1000 dosya yaklaşık 1GB - 2GB RAM yer.
MAX_CACHE_ITEMS = 500 
TS_CACHE = OrderedDict()

gc.set_threshold(700, 10, 10)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=200,
    pool_maxsize=500,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({
    "User-Agent": USER_AGENT,
    "Connection": "keep-alive"
})

def get_best_live_data():
    for src in SOURCES:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=4)
            if r.status_code == 200:
                return r.json(), src
        except:
            continue
    return None, None

def fetch_playlist_content(cid):
    cid_clean = cid.replace('.m3u8', '')
    for src in SOURCES:
        try:
            url = f"{src}/play/{cid_clean}/index.m3u8"
            r = session.get(url, verify=False, timeout=4)
            if r.status_code == 200:
                return r.content, r.url.rsplit('/', 1)[0], src
        except:
            continue
    return None, None, None

# Hem anlık gönderen hem de RAM'e yazan fonksiyon
def stream_and_cache_generator(r, cache_key):
    data_buffer = bytearray()
    try:
        # Chunk boyutu 8KB yapıldı, hızlı aktarım için
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                data_buffer.extend(chunk) # Hafızaya ekle
                yield chunk # Kullanıcıya gönder
        
        # Akış başarıyla biterse Cache'e kaydet
        if len(TS_CACHE) >= MAX_CACHE_ITEMS:
            TS_CACHE.popitem(last=False) # En eskiyi sil
        
        TS_CACHE[cache_key] = bytes(data_buffer) # Byte'a çevirip sakla
        
    except Exception as e:
        # Hata olursa cache'e yarım dosya kaydetme
        pass
    finally:
        r.close()

def proxy_stream(url, timeout_settings):
    # Önce RAM kontrolü
    if url in TS_CACHE:
        return Response(TS_CACHE[url], content_type="video/mp2t")

    try:
        r = session.get(url, stream=True, verify=False, timeout=timeout_settings)
        if r.status_code == 200:
            return Response(stream_with_context(stream_and_cache_generator(r, url)), 
                          content_type="video/mp2t")
        r.close()
    except:
        pass
    return Response("Error", 502)

@app.route('/')
def root():
    data, working_src = get_best_live_data()
    
    if not data:
        return Response("Servers Down", 503)

    host_b = request.host_url.rstrip('/').encode()
    out_lines = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                name = item['name'].replace(',', ' ')
                u = item['url']
                cid = u.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                
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
    
    for line in content.split(b'\n'):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            out.append(line)
        else:
            if line.startswith(b'http'): target = line
            else: target = base_b + b'/' + line
            
            safe_target = quote(target, safe='/:?=&').encode()
            out.append(host_b + b'/ts?url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    if not url_enc: return "Bad Request", 400
    
    original_target = unquote(url_enc)
    
    # 1. ADIM: RAM KONTROLÜ
    # Eğer bu dosya daha önce indirilmişse RAM'den ver ve çık.
    if original_target in TS_CACHE:
        # Cache hit - direkt hafızadan gönder
        return Response(TS_CACHE[original_target], content_type="video/mp2t")

    TIMEOUT_SETTINGS = (3, 10) # Connect timeout 3, Read timeout 10

    path_part = None
    target_domain = None
    
    for src in SOURCES:
        if src in original_target:
            target_domain = src
            try: path_part = original_target.split(src, 1)[1]
            except: pass
            break
            
    if not target_domain:
        return proxy_stream(original_target, TIMEOUT_SETTINGS)

    # 2. ADIM: İLK DENEME (Kaynak Site)
    try:
        r = session.get(original_target, stream=True, verify=False, timeout=TIMEOUT_SETTINGS)
        if r.status_code == 200:
            # Hem stream et hem cache'e yaz
            return Response(stream_with_context(stream_and_cache_generator(r, original_target)), 
                          content_type="video/mp2t")
        r.close()
    except:
        pass 
        
    # 3. ADIM: YEDEK KAYNAKLAR (Failover)
    if path_part:
        for src in SOURCES:
            if src == target_domain: continue
            
            new_target = src + path_part
            # Yedek kaynak için de cache kontrolü yapalım mı? 
            # Genelde URL farklı olduğu için gerekmez ama new_target ile kontrol edilebilir.
            
            try:
                r = session.get(new_target, stream=True, verify=False, timeout=TIMEOUT_SETTINGS)
                if r.status_code == 200:
                    # Başarılı kaynağı stream et ve cache'e (orijinal url anahtarıyla değil yeni url ile) yaz
                    return Response(stream_with_context(stream_and_cache_generator(r, original_target)), 
                                  content_type="video/mp2t")
                r.close()
            except:
                continue

    return Response("Source Error", 502)

if __name__ == "__main__":
    # Worker sayısını RAM kullanımına göre dikkatli ayarla
    worker_pool = pool.Pool(1000)
    server = WSGIServer(('0.0.0.0', PORT), app, spawn=worker_pool, log=None)
    try:
        print(f"Server baslatildi: Port {PORT}")
        print(f"RAM Cache limiti: {MAX_CACHE_ITEMS} segment")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
