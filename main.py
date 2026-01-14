from flask import Flask, Response, request, redirect
from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import concurrent.futures
import time
import threading

app = Flask(__name__)

# --- AYARLAR ---
SITE_URL = "https://dizipal1219.com" # Güncel adres
PORT = 5000
MAX_SAYFA = 3      # Her kategoriden kaç sayfa taransın?
CACHE_SURESI = 3600 # Liste kaç saniyede bir güncellensin? (1 Saat)

# --- RAM BELLEK DEĞİŞKENLERİ ---
# Veriler dosya yerine bu değişkenlerde tutulacak
M3U_CACHE = None       # Hazır listenin tutulduğu değişken
LAST_UPDATE_TIME = 0   # Son güncellenme zamanı
IS_UPDATING = False    # Şu an güncelleme yapılıyor mu?

KAYNAKLAR = [
    {"ad": "Yeni Filmler", "url": f"{SITE_URL}/filmler", "tur": "Film"},
    {"ad": "Yeni Diziler", "url": f"{SITE_URL}/diziler", "tur": "Dizi"},
    {"ad": "Netflix", "url": f"{SITE_URL}/koleksiyon/netflix", "tur": "Platform"},
    {"ad": "Exxen", "url": f"{SITE_URL}/koleksiyon/exxen", "tur": "Platform"},
    {"ad": "BluTV", "url": f"{SITE_URL}/koleksiyon/blutv", "tur": "Platform"},
    {"ad": "Disney+", "url": f"{SITE_URL}/koleksiyon/disney", "tur": "Platform"},
    {"ad": "Amazon Prime", "url": f"{SITE_URL}/koleksiyon/amazon-prime", "tur": "Platform"},
]

def get_session():
    session = requests.Session(impersonate="chrome120")
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{SITE_URL}/",
        "Origin": SITE_URL
    }
    return session

# --- 1. VİDEO ÇÖZÜCÜ ---
def resolve_video(dizipal_url):
    print(f"\n[CANLI İSTEK] {dizipal_url}")
    session = get_session()
    try:
        resp = session.get(dizipal_url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Dizi Kontrolü: Video yoksa ilk bölüme git
        episode_links = soup.select("div.episode-item a")
        if episode_links:
            first_ep = episode_links[0]['href']
            if not first_ep.startswith("http"): first_ep = SITE_URL + first_ep
            if first_ep != dizipal_url:
                print(f"  -> Dizi sayfası, ilk bölüme yönlendiriliyor...")
                return resolve_video(first_ep)

        # Iframe Bulma
        iframe = soup.select_one(".series-player-container iframe") or \
                 soup.select_one("div#vast_new iframe") or \
                 soup.select_one("iframe[src*='vidmoly']")
                 
        if not iframe: return None
        src = iframe.get('src')
        if not src: return None
        
        if "google" in src or "youtube" in src: return None
        
        if src.startswith("//"): src = "https:" + src
        if src.startswith("/"): src = SITE_URL + src

        # Regex ile Link Çıkarma
        session.headers.update({"Referer": SITE_URL})
        html = session.get(src, timeout=8).text
        
        match = re.search(r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', html)
        if match: return match.group(1)
        
        match2 = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', html)
        if match2: return match2.group(1)
        
        return None
    except Exception as e:
        print(f"Çözme Hatası: {e}")
        return None

# --- 2. TARAMA İŞLEMİ ---
def fetch_category_content(kategori):
    session = get_session()
    parsed_items = []
    
    # Hız için her kategoriden sadece belirli sayıda sayfa çek
    for sayfa in range(1, MAX_SAYFA + 1):
        target = f"{kategori['url']}/page/{sayfa}" if sayfa > 1 else kategori['url']
        try:
            resp = session.get(target, timeout=8)
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = soup.select("article.type2 ul li, div.movie-item")
            
            if not items: break
            
            for item in items:
                a = item.select_one("a")
                if not a: continue
                link = a['href']
                if not link.startswith("http"): link = SITE_URL + link
                title = item.select_one(".title, .name").text.strip() if item.select_one(".title, .name") else "Bilinmeyen"
                img = item.select_one("img")
                img_url = img['src'] if img else ""
                
                parsed_items.append({
                    "title": title, "link": link, "img": img_url, "group": kategori["ad"]
                })
        except:
            break
    return parsed_items

def update_ram_cache(base_host):
    """Listeyi tarar ve RAM değişkenine kaydeder"""
    global M3U_CACHE, LAST_UPDATE_TIME, IS_UPDATING
    
    if IS_UPDATING: return
    IS_UPDATING = True
    
    print("\n>>> RAM ÖNBELLEK GÜNCELLENİYOR... (Arka Planda)")
    start_time = time.time()
    
    temp_list = []
    # Paralel tarama (Multi-thread)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_category_content, k) for k in KAYNAKLAR]
        for f in concurrent.futures.as_completed(futures):
            temp_list.extend(f.result())
            
    # M3U String Oluşturma
    # Bellekte string birleştirme (String Builder mantığı)
    m3u_lines = ["#EXTM3U"]
    
    for item in temp_list:
        enc_link = urllib.parse.quote(item['link'])
        proxy_link = f"{base_host}watch?url={enc_link}"
        line = f'#EXTINF:-1 tvg-logo="{item["img"]}" group-title="{item["group"]}",{item["title"]}\n{proxy_link}'
        m3u_lines.append(line)
        
    # Global değişkeni güncelle
    M3U_CACHE = "\n".join(m3u_lines)
    LAST_UPDATE_TIME = time.time()
    IS_UPDATING = False
    
    print(f">>> GÜNCELLEME BİTTİ! {len(temp_list)} içerik belleğe alındı ({round(time.time()-start_time, 2)} sn).")

# --- 3. FLASK ROTALARI ---

@app.route('/')
def playlist():
    global M3U_CACHE
    base_host = request.host_url
    
    current_time = time.time()
    
    # 1. Durum: Hiç veri yok (İlk açılış) -> Mecbur bekletip yükleyeceğiz.
    if M3U_CACHE is None:
        print("İlk açılış: Liste hazırlanıyor, lütfen bekleyin...")
        update_ram_cache(base_host)
        
    # 2. Durum: Veri var ama eski -> Eskiyi göster, arkada yenisini hazırla.
    elif (current_time - LAST_UPDATE_TIME) > CACHE_SURESI:
        print("Liste eski: Arka planda güncelleme başlatıldı.")
        threading.Thread(target=update_ram_cache, args=(base_host,)).start()
        
    # Bellekteki veriyi sun
    return Response(M3U_CACHE, mimetype='audio/x-mpegurl')

@app.route('/watch')
def watch():
    target_url = request.args.get('url')
    if not target_url: return "URL Yok", 400
    target_url = urllib.parse.unquote(target_url)
    
    real_url = resolve_video(target_url)
    
    if real_url:
        return redirect(real_url)
    else:
        return "Video Bulunamadı", 404

@app.route('/refresh')
def force_refresh():
    base_host = request.host_url
    threading.Thread(target=update_ram_cache, args=(base_host,)).start()
    return "Manuel güncelleme tetiklendi."

if __name__ == '__main__':
    print("Sunucu Başlatıldı. İlk istekte liste belleğe alınacak.")
    app.run(host='0.0.0.0', port=PORT)
