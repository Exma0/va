from gevent import monkey
monkey.patch_all()

import time
import requests
import urllib3
import gc
import sys
from gevent import pool
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

# ---------------------------------------------------------------------------
# PERFORMANS AYARLARI
# ---------------------------------------------------------------------------

# Hızlı JSON kütüphanesi kontrolü (Varsa kullanır, yoksa standart json)
try:
    import ujson as json
except ImportError:
    import json

# Vavoo kaynakları (Biri çalışmazsa diğeri denenir)
SOURCES = [
    "https://vavoo.to",
    "https://huhu.to" 
]

USER_AGENT = "VAVOO/2.6"
PORT = 8080

# Video akışı için Buffer Boyutu (64KB - CPU dostu)
CHUNK_SIZE = 64 * 1024 

# Çöp toplama ayarları (RAM şişmesini engeller)
gc.set_threshold(700, 10, 10)

# SSL Uyarılarını kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Flask Uygulaması
app = Flask(__name__)

# Logları sustur (Konsol kirliliğini ve Disk I/O'yu önler)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

# ---------------------------------------------------------------------------
# BAĞLANTI HAVUZU (Connection Pool)
# ---------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=200,    # Aynı anda bağlanılacak farklı host sayısı
    pool_maxsize=500,        # Havuzdaki toplam bağlantı sayısı
    max_retries=1,           # İstek başarısız olursa 1 kez daha dene
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({
    "User-Agent": USER_AGENT,
    "Connection": "keep-alive" # Bağlantıyı sürekli açık tut
})

# ---------------------------------------------------------------------------
# YARDIMCI FONKSİYONLAR
# ---------------------------------------------------------------------------

def get_best_live_data():
    """
    Kanal listesini çeker. 
    Burası video değil liste olduğu için timeout (4 sn) olmalıdır.
    Yoksa liste yüklenirken arayüz sonsuza kadar donabilir.
    """
    for src in SOURCES:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=4)
            if r.status_code == 200:
                return r.json(), src
        except:
            continue
    return None, None

def fetch_playlist_content(cid):
    """
    M3U8 dosyasını çeker.
    Yayın başlamadan önceki son adım.
    """
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

def proxy_stream(url, timeout_settings):
    """Harici kaynaklar için proxy fonksiyonu"""
    try:
        r = session.get(url, stream=True, verify=False, timeout=timeout_settings)
        return Response(stream_with_context(r.iter_content(chunk_size=CHUNK_SIZE)), 
                        content_type="video/mp2t")
    except:
        return Response("Error", 502)

# ---------------------------------------------------------------------------
# ROUTE (YÖNLENDİRME) İŞLEMLERİ
# ---------------------------------------------------------------------------

@app.route('/')
def root():
    """Ana M3U listesini oluşturur"""
    data, working_src = get_best_live_data()
    
    if not data:
        return Response("Kaynaklara erisilemiyor (Servers Down)", 503)

    host_b = request.host_url.rstrip('/').encode()
    out_lines = [b"#EXTM3U"]
    
    # JSON listesini işle
    for item in data:
        if item.get("group") == "Turkey":
            try:
                # String işlemlerini minimize et
                name = item['name'].replace(',', ' ')
                u = item['url']
                cid = u.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                
                # Listeye ekle
                out_lines.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode('utf-8'))
                out_lines.append(host_b + b'/live/' + cid.encode('utf-8') + b'.m3u8')
            except: 
                pass

    return Response(b"\n".join(out_lines), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    """Kanalın yayın akış dosyasını (m3u8) çeker ve TS linklerini proxy'ye yönlendirir"""
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
            # TS dosya adresi
            if line.startswith(b'http'):
                target = line
            else:
                target = base_b + b'/' + line
            
            # URL'yi güvenli şekilde kodla ve bizim proxy'ye yönlendir
            safe_target = quote(target, safe='/:?=&').encode()
            out.append(host_b + b'/ts?url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    """
    Video parçalarını (TS) çeken ana fonksiyon.
    Sonsuz Okuma Döngüsü (Infinite Read Timeout) buradadır.
    """
    url_enc = request.args.get('url')
    if not url_enc: return "Bad Request", 400
    
    original_target = unquote(url_enc)
    
    # ----------------------------------------------------------
    # KRİTİK AYAR: (Connect Timeout, Read Timeout)
    # Connect (5): Sunucuya bağlanmak için en fazla 5 saniye bekle.
    # Read (None): Bağlandıktan sonra veri gelmese bile ASLA koparma.
    # ----------------------------------------------------------
    TIMEOUT_SETTINGS = (5, None)

    # Hedefin hangi domainde olduğunu bul (Failover için)
    path_part = None
    target_domain = None
    
    for src in SOURCES:
        if src in original_target:
            target_domain = src
            try: 
                path_part = original_target.split(src, 1)[1]
            except: 
                pass
            break
            
    # Eğer Vavoo dışı bir link ise direkt proxy yap
    if not target_domain:
        return proxy_stream(original_target, TIMEOUT_SETTINGS)

    # 1. DENEME: Orijinal Link
    try:
        r = session.get(original_target, stream=True, verify=False, timeout=TIMEOUT_SETTINGS)
        if r.status_code == 200:
            return Response(stream_with_context(r.iter_content(chunk_size=CHUNK_SIZE)), 
                          content_type="video/mp2t")
        r.close()
    except:
        pass # Hata alırsan sessizce 2. denemeye geç
        
    # 2. DENEME: Failover (Alternatif Sunucular)
    if path_part:
        for src in SOURCES:
            if src == target_domain: continue # Zaten denediğimiz sunucuyu geç
            
            new_target = src + path_part
            try:
                # Burada da sonsuz okuma süresi geçerli
                r = session.get(new_target, stream=True, verify=False, timeout=TIMEOUT_SETTINGS)
                if r.status_code == 200:
                    return Response(stream_with_context(r.iter_content(chunk_size=CHUNK_SIZE)), 
                                  content_type="video/mp2t")
                r.close()
            except:
                continue

    return Response("Source Error", 502)

if __name__ == "__main__":
    print("---------------------------------------")
    print(f" ► VAVOO PROXY BAŞLATILDI")
    print(f" ► MOD: INFINITE STREAM (Asla Kopmaz)")
    print(f" ► BUFFER: {CHUNK_SIZE // 1024} KB")
    print(f" ► PORT: {PORT}")
    print("---------------------------------------")
    
    # Sunucu yük altında kilitlenmesin diye Worker Pool kullanıyoruz
    # 1000 eşzamanlı izleyiciye kadar destekler
    worker_pool = pool.Pool(1000)
    
    server = WSGIServer(('0.0.0.0', PORT), app, spawn=worker_pool, log=None)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Kapatiliyor...")
