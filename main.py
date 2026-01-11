from gevent import monkey
monkey.patch_all()

import json
import re
import requests
import time
import sys
import urllib3
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin, quote, unquote, urlparse
from threading import Lock, RLock
from gevent.pywsgi import WSGIServer

app = Flask(__name__)

# =====================================================
# AYARLAR
# =====================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}

# SSL Uyarılarını Kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Bağlantı Havuzu (Performans için optimize edildi)
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=2)
session.mount('http://', adapter)
session.mount('https://', adapter)

# =====================================================
# THE BRAIN (Yayın Çözümleme Merkezi)
# =====================================================
class StreamBrain:
    def __init__(self):
        # { 'cid': {'final_url': '...', 'updated_at': 123} }
        self.channels = {}
        self.locks = {}
        self.global_lock = RLock()

    def get_lock(self, cid):
        with self.global_lock:
            if cid not in self.locks:
                self.locks[cid] = Lock()
            return self.locks[cid]

    def resolve_stream_url(self, cid, force_refresh=False):
        """
        Kanalın en son çalışan 'index.m3u8' adresini (Redirectler çözülmüş halde) bulur.
        """
        # Cache Kontrolü (5 Dakika)
        if not force_refresh and cid in self.channels:
            if time.time() - self.channels[cid]['updated_at'] < 300:
                return self.channels[cid]['final_url']

        lock = self.get_lock(cid)
        with lock:
            # Double Check
            if not force_refresh and cid in self.channels:
                if time.time() - self.channels[cid]['updated_at'] < 300:
                    return self.channels[cid]['final_url']
            
            try:
                # 1. Vavoo API İsteği
                initial_url = f"https://vavoo.to/play/{cid}/index.m3u8"
                r = session.get(initial_url, headers=HEADERS, verify=False, timeout=8, allow_redirects=True)
                if r.status_code != 200: return None
                
                # 2. Redirect ve Master Playlist Çözümleme
                current_url = r.url
                content = r.text
                
                # Eğer Master Playlist ise (Kalite seçenekleri varsa)
                if "#EXT-X-STREAM-INF" in content:
                    lines = content.splitlines()
                    # Genelde en yüksek kalite en sondadır
                    for line in reversed(lines):
                        if line and not line.startswith("#"):
                            current_url = urljoin(current_url, line)
                            
                            # O linkin çalıştığını doğrula
                            try:
                                r2 = session.get(current_url, headers=HEADERS, timeout=5)
                                if r2.status_code == 200:
                                    current_url = r2.url
                            except: pass
                            break
                
                # 3. Sonuçları Kaydet
                self.channels[cid] = {
                    'final_url': current_url,
                    'updated_at': time.time()
                }
                return current_url

            except Exception as e:
                # print(f"Brain Error: {e}", file=sys.stderr)
                return None

brain = StreamBrain()

# =====================================================
# ROTALAR
# =====================================================

@app.route('/')
def root():
    # Regex yerine JSON parse kullanıyoruz (Daha güvenli)
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, verify=False, timeout=10)
        data = r.json()
    except:
        return "Liste Çekilemedi", 502

    base_app_url = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # JSON verisini işle
    for item in data:
        # Sadece Türkiye grubu (İsteğe bağlı değiştirilebilir)
        if item.get("group") == "Turkey":
            name = item.get("name", "Unknown").replace(',', '')
            url = item.get("url", "")
            
            # URL içinden ID'yi al
            match = re.search(r'/play/(\d+)', url)
            if match:
                cid = match.group(1)
                logo = item.get("logo", "")
                out.append(f'#EXTINF:-1 group-title="Turkey" tvg-logo="{logo}",{name}\n{base_app_url}/live/{cid}.m3u8')

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    final_url = brain.resolve_stream_url(cid)
    if not final_url: return Response("Yayin Yok", status=404)

    try:
        r = session.get(final_url, headers=HEADERS, verify=False, timeout=6)
        
        # Token süresi dolmuşsa yenile
        if r.status_code != 200:
            final_url = brain.resolve_stream_url(cid, force_refresh=True)
            if not final_url: return Response("Yayin Kirik", status=503)
            r = session.get(final_url, headers=HEADERS, verify=False, timeout=6)

        content = r.text
        new_lines = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith("#"):
                new_lines.append(line)
            else:
                # TS dosyası linkini tam URL'ye çevir
                # r.url kullanıyoruz ki redirect sonrası doğru path bulunsun
                ts_full_url = urljoin(r.url, line)
                
                # URL'yi güvenli hale getir (quote)
                safe_target = quote(ts_full_url)
                
                # Proxy linkini oluştur
                new_lines.append(f"{request.host_url.rstrip('/')}/seg?cid={cid}&target={safe_target}")

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception:
        return Response("Server Error", status=500)

@app.route('/seg')
def segment_handler():
    cid = request.args.get('cid')
    target_url_encoded = request.args.get('target')
    
    if not cid or not target_url_encoded: return "Bad Request", 400
    
    current_target_url = unquote(target_url_encoded)
    final_response = None
    
    # 3 Deneme Hakkı (Retry Logic)
    for attempt in range(3):
        try:
            # İlk deneme başarısızsa ve URL yenileme gerekiyorsa:
            if attempt > 0:
                new_base_m3u8 = brain.resolve_stream_url(cid, force_refresh=True)
                if new_base_m3u8:
                    # ESKİ KOD HATASI DÜZELTİLDİ:
                    # Eski URL'deki token karmaşasını atıp sadece dosya ismini alıyoruz.
                    parsed_old_url = urlparse(current_target_url)
                    file_name = parsed_old_url.path.split('/')[-1]
                    
                    # Yeni temiz URL oluştur
                    current_target_url = urljoin(new_base_m3u8, file_name)

            upstream = session.get(current_target_url, headers=HEADERS, verify=False, stream=True, timeout=10)
            
            if upstream.status_code == 200:
                final_response = upstream
                break
            elif upstream.status_code in [403, 410, 404]:
                # Token hatası veya bulunamadı -> Döngü başa döner, URL yenilenir
                upstream.close()
                continue
            else:
                upstream.close()
                continue

        except Exception:
            time.sleep(0.5)
            continue

    if not final_response:
        return Response("Segment Unavailable", status=503)

    def generate(upstream_resp):
        try:
            # Chunk boyutu video için ideal seviyeye çekildi (128KB)
            for chunk in upstream_resp.iter_content(chunk_size=131072):
                if chunk: yield chunk
        except:
            pass
        finally:
            upstream_resp.close()

    return Response(stream_with_context(generate(final_response)), content_type="video/mp2t")

# =====================================================
# MAIN (Gevent WSGI Server)
# =====================================================
if __name__ == "__main__":
    # Flask'ın kendi run() metodu yerine Gevent WSGIServer kullanıyoruz.
    # Bu, monkey.patch_all() ile tam uyumlu çalışmasını sağlar.
    port = 8080
    print(f"Sunucu baslatiliyor: http://0.0.0.0:{port}")
    try:
        http_server = WSGIServer(('0.0.0.0', port), app)
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("Kapatiliyor...")
