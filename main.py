from gevent import monkey; monkey.patch_all()
from flask import Flask, Response, request, stream_with_context, redirect
from gevent.pywsgi import WSGIServer
from gevent import sleep
from curl_cffi import requests as crequests # Cloudflare'i geçmek için
import requests # Standart requests (Stream için)
from bs4 import BeautifulSoup
import yt_dlp
import re
import threading
import time
import base64
from urllib.parse import quote, unquote

# --- AYARLAR ---
PORT = 8080
CHUNK_SIZE = 16384
SITE_URL = "https://dizipal1219.com" # Güncel adresi buraya yaz
MAX_WORKERS = 5 # Tarama hızı

# --- VERİ HAVUZU ---
# İçerikleri burada tutacağız
CONTENT_CACHE = []
CACHE_LOCK = threading.Lock()

app = Flask(__name__)

# --- YARDIMCI FONKSİYONLAR ---

def base64_encode(s):
    return base64.urlsafe_b64encode(s.encode()).decode()

def base64_decode(s):
    return base64.urlsafe_b64decode(s.encode()).decode()

class DiziPalResolver:
    """Siteye gidip M3U8 linkini o an çözen sınıf"""
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"{SITE_URL}/"
        }

    def get_real_m3u8(self, page_url):
        """Sayfa linkinden gerçek video linkini bulur"""
        print(f" [RESOLVER] Link çözülüyor: {page_url}")
        try:
            # curl_cffi kullanarak siteye istek at (Cloudflare bypass)
            session = crequests.Session(impersonate="chrome120")
            session.headers.update(self.headers)
            resp = session.get(page_url, timeout=10)
            
            if resp.status_code != 200:
                print("Siteye erişilemedi.")
                return None
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # iframe ara
            iframe = soup.select_one(".series-player-container iframe") or \
                     soup.select_one("div#vast_new iframe") or \
                     soup.select_one("iframe")
                     
            if not iframe:
                print("Iframe bulunamadı.")
                return None
            
            iframe_src = iframe.get('src')
            if iframe_src.startswith("//"): iframe_src = "https:" + iframe_src
            
            # 1. Regex ile dene
            html = session.get(iframe_src, headers={"Referer": SITE_URL}, timeout=5).text
            match = re.search(r'file:\s*"([^"]+)"', html)
            if match: 
                return match.group(1)
            
            # 2. yt-dlp ile dene
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(iframe_src, download=False)
                return info.get('url')
                
        except Exception as e:
            print(f"Çözme hatası: {e}")
            return None

class DiziPalScanner:
    """Arka planda siteyi tarayıp listeyi güncelleyen sınıf"""
    def __init__(self):
        self.resolver = DiziPalResolver()
        self.kategoriler = {
            "Filmler": f"{SITE_URL}/filmler",
            "Diziler": f"{SITE_URL}/diziler",
            "Netflix": f"{SITE_URL}/koleksiyon/netflix"
        }

    def scan(self):
        print("--- TARAMA BAŞLADI ---")
        temp_list = []
        
        # Sadece ilk 2 sayfayı tarar (Test amaçlı, artırabilirsin)
        for cat, url in self.kategoriler.items():
            for page in range(1, 3): 
                target = url if page == 1 else f"{url}/page/{page}"
                try:
                    session = crequests.Session(impersonate="chrome120")
                    resp = session.get(target, timeout=10)
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    items = soup.select("article.type2 ul li") or soup.select("div.movie-item")
                    for item in items:
                        a = item.select_one("a")
                        if not a: continue
                        
                        link = a['href']
                        if not link.startswith("http"): link = SITE_URL + link
                        
                        title = item.select_one(".title").text.strip() if item.select_one(".title") else "Bilinmeyen"
                        img = item.select_one("img")
                        poster = img.get('src') if img else ""
                        if poster and not poster.startswith("http"): poster = SITE_URL + poster

                        temp_list.append({
                            "group": cat,
                            "title": title,
                            "url": link, # Bu sayfa linki, video linki değil!
                            "poster": poster
                        })
                except Exception as e:
                    print(f"Tarama hatası ({cat}): {e}")
        
        # Listeyi güncelle
        global CONTENT_CACHE
        with CACHE_LOCK:
            CONTENT_CACHE = temp_list
        print(f"--- TARAMA BİTTİ: {len(CONTENT_CACHE)} içerik bulundu ---")

# --- FLASK ROTLARI ---

@app.route('/')
def playlist():
    """Ana M3U Listesini oluşturur"""
    host = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    with CACHE_LOCK:
        for item in CONTENT_CACHE:
            # Linki güvenli hale getirip url parametresi olarak ekliyoruz
            safe_url = base64_encode(item['url'])
            
            # M3U satırı
            out.append(f'#EXTINF:-1 group-title="{item["group"]}" tvg-logo="{item["poster"]}", {item["title"]}')
            # Bu link tıklandığında /resolve endpointine gidecek
            out.append(f'{host}/resolve?u={safe_url}')
            
    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/resolve')
def resolve_stream():
    """Tıklanan içeriğin gerçek M3U8 linkini bulur ve proxy'ye yönlendirir"""
    u_enc = request.args.get('u')
    if not u_enc: return "No URL", 400
    
    page_url = base64_decode(u_enc)
    
    resolver = DiziPalResolver()
    real_m3u8 = resolver.get_real_m3u8(page_url)
    
    if real_m3u8:
        # Bulunan linki proxy_m3u8 endpointine yönlendir
        host = request.host_url.rstrip('/')
        return redirect(f"{host}/api/m3u8?u={quote(real_m3u8)}")
    else:
        return "Video Bulunamadı veya Çözülemedi", 404

@app.route('/api/m3u8')
def proxy_m3u8():
    """Gerçek M3U8 dosyasını indirir ve içindeki linkleri yerel sunucuya çevirir"""
    u = request.args.get('u')
    if not u: return "No URL", 400
    
    try:
        # İstekleri requests ile atıyoruz (Gevent patchli)
        r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, verify=False, timeout=10)
        
        base_url = u.rsplit('/', 1)[0]
        host = request.host_url.rstrip('/')
        new_lines = []
        
        for line in r.text.splitlines():
            if line.strip().startswith('#'):
                new_lines.append(line)
            elif line.strip():
                # TS veya alt M3U8 linki
                full_url = line if line.startswith('http') else f"{base_url}/{line}"
                
                # Eğer başka bir m3u8 ise yine bu fonksiyona, ts ise ts fonksiyonuna
                if ".m3u8" in full_url:
                    new_url = f"{host}/api/m3u8?u={quote(full_url)}"
                else:
                    new_url = f"{host}/api/ts?u={quote(full_url)}"
                new_lines.append(new_url)
                
        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")
    except Exception as e:
        return f"M3U8 Proxy Hatası: {e}", 502

@app.route('/api/ts')
def proxy_ts():
    """Video parçalarını (TS) indirip istemciye yayınlar"""
    u = request.args.get('u')
    if not u: return "No URL", 400
    
    try:
        # Stream isteği
        req = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, stream=True, verify=False, timeout=10)
        
        def generate():
            for chunk in req.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    yield chunk
                    sleep(0) # Gevent için context switch
                    
        return Response(stream_with_context(generate()), content_type="video/mp2t")
    except Exception as e:
        return f"TS Error: {e}", 500

# --- BAŞLATMA ---

def start_scanner_loop():
    scanner = DiziPalScanner()
    while True:
        scanner.scan()
        # Her 30 dakikada bir listeyi yenile
        time.sleep(1800)

if __name__ == "__main__":
    # 1. Arka planda tarayıcıyı başlat
    t = threading.Thread(target=start_scanner_loop)
    t.daemon = True
    t.start()
    
    # 2. Web sunucusunu başlat
    print(f"Sunucu çalışıyor: http://localhost:{PORT}")
    print("M3U Linkiniz: http://localhost:8080/")
    
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
