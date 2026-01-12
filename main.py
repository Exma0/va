from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
from gevent import pool, spawn
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ---------------------------------------------------------
# AYARLAR VE SABİTLER
# ---------------------------------------------------------
# Vavoo altyapısı bu User-Agent ile daha stabil çalışır
USER_AGENT = "VAVOO/2.6"
SOURCES = [
    "https://vavoo.to"
]

# Çöp toplama mekanizmasını rahatlat (Mikro takılmaları önler)
gc.set_threshold(1000, 20, 20)

# SSL Uyarılarını kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# Logları sustur (Performans için)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

# ---------------------------------------------------------
# BAĞLANTI HAVUZU (Connection Pool)
# ---------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=100,
    pool_maxsize=200,
    max_retries=1, # Tekrar denemeyi kod içinde manuel yapacağız
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate", # Sıkıştırmayı kabul et, sonra biz açacağız
    "Connection": "keep-alive"
})

# ---------------------------------------------------------
# YARDIMCI FONKSİYONLAR
# ---------------------------------------------------------

def get_best_live_data():
    """
    Kanal listesini çekmek için sırayla kaynakları dener.
    İlk çalışan kaynağın verisini döndürür.
    """
    for src in SOURCES:
        try:
            url = f"{src}/live2/index"
            r = session.get(url, verify=False, timeout=5)
            if r.status_code == 200:
                return r.json(), src
        except:
            continue
    return None, None

def fetch_playlist_content(cid):
    """
    M3U8 dosyasını çeker. Hata alırsan diğer kaynakları dener.
    """
    cid_clean = cid.replace('.m3u8', '')
    
    for src in SOURCES:
        try:
            url = f"{src}/play/{cid_clean}/index.m3u8"
            r = session.get(url, verify=False, timeout=3)
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
        return Response("Kaynaklara erisilemiyor (Vavoo Servers Down)", 503)

    host_b = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    
    # JSON verisini işle ve M3U formatına çevir
    for item in data:
        # Sadece Turkey grubu (Bunu silebilirsin tüm kanallar için)
        if item.get("group") == "Turkey":
            try:
                name = item['name'].replace(',', ' ')
                u = item['url']
                # URL'den ID'yi temizle
                cid = u.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                
                out.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode())
                out.append(host_b + b'/live/' + cid.encode() + b'.m3u8')
            except: pass

    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    content, base_url, used_src = fetch_playlist_content(cid)
    
    if not content:
        return Response("Stream Bulunamadi", 404)

    host_b = request.host_url.rstrip('/').encode()
    base_b = base_url.encode()
    cid_b = cid.replace('.m3u8', '').encode()
    
    out = []
    lines = content.split(b'\n')
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            out.append(line)
        else:
            # TS dosyasının tam adresi
            if line.startswith(b'http'):
                target = line
            else:
                target = base_b + b'/' + line
            
            # TS proxy adresimiz
            safe_target = quote(target).encode()
            out.append(host_b + b'/ts?url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    """
    TS dosyalarını indirir. FAILOVER mantığı buradadır.
    Eğer ana link çalışmazsa, linki manipüle edip diğer sunucudan ister.
    """
    url_enc = request.args.get('url')
    if not url_enc: return "Bad Request", 400
    
    original_target = unquote(url_enc)
    
    # Hedef URL'nin hangi domainden geldiğini bul
    target_domain = None
    path_part = ""
    
    for src in SOURCES:
        if src in original_target:
            target_domain = src
            # URL'nin domainden sonraki kısmını al (/8546/154.ts gibi)
            path_part = original_target.split(src, 1)[1]
            break
            
    # Eğer bilinen bir kaynak değilse direkt dene
    if not target_domain:
        return proxy_stream(original_target)

    # ÖNCE ORİJİNAL KAYNAĞI DENE
    # Eğer hata alırsan döngüye girip diğerlerini dene
    
    # Kaynak listesini karıştır ki yük dağılsın, ama orijinali en başa koy
    # (Burada basitlik adına sırayla deniyoruz)
    
    # 1. Deneme: Orijinal URL
    try:
        r = session.get(original_target, stream=True, verify=False, timeout=4)
        if r.status_code == 200:
            return Response(stream_with_context(r.iter_content(chunk_size=32768)), 
                          content_type="video/mp2t")
        r.close()
    except:
        pass
        
    # 2. Deneme: Failover (Diğer kaynaklar)
    # Vavoo yapısında dosya yolları genelde standarttır, sadece domain değişir.
    for src in SOURCES:
        if src == target_domain: continue # Zaten denedik
        
        new_target = src + path_part
        try:
            r = session.get(new_target, stream=True, verify=False, timeout=3)
            if r.status_code == 200:
                # Kurtardık! Yayına devam.
                return Response(stream_with_context(r.iter_content(chunk_size=32768)), 
                              content_type="video/mp2t")
            r.close()
        except:
            continue

    return Response("Source Error", 502)

def proxy_stream(url):
    # Harici kaynaklar için basit proxy
    try:
        r = session.get(url, stream=True, verify=False, timeout=5)
        return Response(stream_with_context(r.iter_content(chunk_size=32768)), 
                        content_type="video/mp2t")
    except:
        return Response("Error", 502)

if __name__ == "__main__":
    print("---------------------------------------")
    print(" ► VAVOO PROXY - FAILOVER EDITION")
    print(" ► USER-AGENT: VAVOO/2.6")
    print(" ► PORT: 8080")
    print("---------------------------------------")
    
    # Backlog çok yüksek tutuldu, istek düşmesi olmasın
    server = WSGIServer(('0.0.0.0', 8080), app, backlog=65535)
    server.serve_forever()
