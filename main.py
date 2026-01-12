# ==============================================================================
# VAVOO SINGULARITY: FINAL RELEASE (FULL STABLE)
# ==============================================================================
# KURULUM: pip install flask gevent requests
# CALISTIRMA: python vavoo.py
# ==============================================================================

# 1. GEVENT PATCH (MUTLAKA EN BASTA OLMALI)
from gevent import monkey
monkey.patch_all()

import sys
import re
import time
import json
import requests
import urllib3
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote, urljoin, urlparse

# ------------------------------------------------------------------------------
# AYARLAR & SABITLER
# ------------------------------------------------------------------------------
app = Flask(__name__)

# SSL Hata mesajlarini gizle (Konsolu temiz tutar)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Kaynak Sunucular (Yedekli)
SOURCES = [
    "https://vavoo.to",
    "https://huhu.to",
    "https://oha.to",
    "https://kool.to"
]

# Vavoo icin kritik header bilgileri
HEADERS = {
    "User-Agent": "Vavoo/2.6",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive"
}

# Buffer boyutu (64KB idealdir)
CHUNK_SIZE = 64 * 1024

# ------------------------------------------------------------------------------
# NETWORK KATMANI (SESSION POOL)
# ------------------------------------------------------------------------------
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=100,
    pool_maxsize=100,
    max_retries=2,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update(HEADERS)

# ------------------------------------------------------------------------------
# YARDIMCI FONKSIYONLAR
# ------------------------------------------------------------------------------

def find_working_stream(cid):
    """
    Verilen kanal ID (cid) icin calisan sunucuyu bulur ve
    gerekli imza (token) bilgilerini alir.
    """
    for src in SOURCES:
        try:
            # Vavoo Play API istegi
            url = f"{src}/play/{cid}/index.m3u8"
            
            # Redirectlere izin ver (Cunku Vavoo baska sunucuya yonlendirebilir)
            r = session.get(url, verify=False, timeout=4, allow_redirects=True)
            
            if r.status_code == 200:
                # Icerik kontrolu: Gercekten M3U8 mi dondu?
                if b"#EXTM3U" in r.content:
                    return {
                        "base_url": r.url.rsplit('/', 1)[0], # Link birlestirme icin kok adres
                        "final_url": r.url,
                        "content": r.content,
                        "cookies": r.cookies # Cookie gerekirse tasi
                    }
        except Exception:
            continue
            
    return None

def stream_proxy(url):
    """
    Veriyi indirmeden (RAM sisirmeden) dogrudan istemciye akitir.
    """
    try:
        # stream=True ile baglantiyi acik tut
        with session.get(url, stream=True, verify=False, timeout=15) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    yield chunk
    except Exception:
        # Baglanti koparsa sessizce bitir
        pass

# ------------------------------------------------------------------------------
# ENDPOINTLER (WEB SERVISI)
# ------------------------------------------------------------------------------

@app.route('/')
def index():
    """
    Ana Liste: Tum sunuculari tarar, Turkey grubunu suzer ve M3U listesi olusturur.
    """
    host = request.host_url.rstrip('/')
    channels = []
    
    # 1. Kanal Listesini Cek
    for src in SOURCES:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=5)
            if r.status_code == 200:
                try:
                    data = r.json()
                    if data:
                        channels = data
                        break # Veriyi aldik, donguden cik
                except:
                    continue
        except:
            continue

    if not channels:
        return Response("Sunuculara erisilemiyor veya liste bos.", 503)

    # 2. M3U Dosyasini Olustur
    m3u_lines = ["#EXTM3U"]
    
    for item in channels:
        # Sadece Turkey grubu (Istege bagli bu if kaldirilabilir)
        if item.get("group") == "Turkey":
            name = item.get("name", "Unknown Channel").replace(",", " ")
            raw_url = item.get("url", "")
            
            # URL'den ID ayiklama (Ornek: .../play/123456.m3u8 -> 123456)
            match = re.search(r'/play/([\w\.]+)', raw_url)
            if match:
                cid = match.group(1).replace(".m3u8", "")
                
                # Logo varsa ekle
                logo = item.get("logo", "")
                tvg_id = item.get("id", "")
                
                meta = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="Turkey",{name}'
                link = f"{host}/live/{cid}.m3u8"
                
                m3u_lines.append(meta)
                m3u_lines.append(link)

    return Response("\n".join(m3u_lines), content_type="application/vnd.apple.mpegurl")

@app.route('/live/<cid>.m3u8')
def playlist_wrapper(cid):
    """
    Kanal M3U8 dosyasini isler, TS ve KEY linklerini bizim proxy'ye yonlendirir.
    """
    info = find_working_stream(cid)
    
    if not info:
        return Response("Stream Offline", 404)
    
    base_url = info['base_url']
    host = request.host_url.rstrip('/')
    
    # Icerigi satir satir işle
    content = info['content'].decode('utf-8', errors='ignore')
    new_lines = []
    
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
            
        if line.startswith("#"):
            # Sifreleme Anahtari (KEY) varsa yakala
            if "EXT-X-KEY" in line:
                # URI="..." kismini regex ile bul
                def key_replacer(match):
                    original_key = match.group(1)
                    # Absolute URL yap
                    full_key_url = urljoin(base_url + "/", original_key)
                    # Proxy URL'e cevir
                    return f'URI="{host}/proxy?url={quote(full_key_url)}"'
                
                line = re.sub(r'URI="([^"]+)"', key_replacer, line)
            new_lines.append(line)
        else:
            # TS Dosyasi (Video Segmenti)
            # URL'i tam hale getir
            full_ts_url = urljoin(base_url + "/", line)
            # Proxy URL'e cevir
            new_lines.append(f"{host}/proxy?url={quote(full_ts_url)}")
            
    return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

@app.route('/proxy')
def unified_proxy():
    """
    Tek Merkezli Proxy: TS ve KEY dosyalarini indirir.
    """
    target = request.args.get('url')
    if not target:
        return Response("Missing URL", 400)
    
    real_url = unquote(target)
    
    # Icerik tipini tahmin et (ts icin video, key icin octet)
    c_type = "video/mp2t" if ".ts" in real_url else "application/octet-stream"
    
    return Response(
        stream_with_context(stream_proxy(real_url)),
        content_type=c_type
    )

@app.route('/status')
def status_check():
    """Sunucu durumunu kontrol etmek icin basit sayfa"""
    return "Vavoo Proxy is Running! OK."

# ------------------------------------------------------------------------------
# BASLATMA (MAIN)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n" + "="*60)
    print(" ► VAVOO PROXY TAM SURUM (FINAL)")
    print(" ► PORT: 8080")
    print(" ► URL: http://localhost:8080")
    print(" ► DURDURMAK ICIN: CTRL+C")
    print("="*60 + "\n")
    
    # WSGI Server: Coklu baglanti destegi icin Gevent kullaniyoruz
    http_server = WSGIServer(('0.0.0.0', 8080), app, log=None)
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatiliyor...")
        sys.exit(0)
