from flask import Flask, Response, request, redirect
from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import concurrent.futures
import time
import threading
import binascii

app = Flask(__name__)

# --- AYARLAR ---
SITE_URL = "https://dizipal1219.com" # Güncel adresi kontrol et
PORT = 5000
MAX_SAYFA = 3      
CACHE_SURESI = 3600

# --- RAM BELLEK ---
M3U_CACHE = None
LAST_UPDATE_TIME = 0
IS_UPDATING = False

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

def resolve_video(dizipal_url):
    print(f"\n[CANLI İSTEK] {dizipal_url}")
    session = get_session()
    try:
        resp = session.get(dizipal_url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Dizi Kontrolü
        episode_links = soup.select("div.episode-item a")
        if episode_links:
            first_ep = episode_links[0]['href']
            if not first_ep.startswith("http"): first_ep = SITE_URL + first_ep
            if first_ep != dizipal_url:
                print(f"  -> Dizi yönlendirmesi...")
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

        # Regex
        session.headers.update({"Referer": SITE_URL})
        html = session.get(src, timeout=8).text
        
        match = re.search(r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', html)
        if match: return match.group(1)
        
        match2 = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', html)
        if match2: return match2.group(1)
        
        return None
    except Exception as e:
        print(f"Hata: {e}")
        return None

def fetch_category_content(kategori):
    session = get_session()
    parsed_items = []
    
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
    global M3U_CACHE, LAST_UPDATE_TIME, IS_UPDATING
    
    if IS_UPDATING: return
    IS_UPDATING = True
    
    print("\n>>> RAM GÜNCELLENİYOR... (VOD MODU)")
    
    temp_list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_category_content, k) for k in KAYNAKLAR]
        for f in concurrent.futures.as_completed(futures):
            temp_list.extend(f.result())
            
    m3u_lines = ["#EXTM3U"]
    
    for item in temp_list:
        # URL'yi HEX formatına çevirip sonuna .mp4 ekliyoruz
        # Bu sayede IPTV oynatıcı bunun bir VİDEO DOSYASI olduğunu sanıyor
        url_bytes = item['link'].encode('utf-8')
        hex_url = binascii.hexlify(url_bytes).decode('utf-8')
        
        # Link Yapısı: http://ip:5000/stream/HEXKODU.mp4
        proxy_link = f"{base_host}stream/{hex_url}.mp4"
        
        # Smarters Pro'nun VOD olarak tanıması için type="vod" ekliyoruz (bazı versiyonlar için)
        # Ancak en önemlisi linkin .mp4 ile bitmesidir.
        line = f'#EXTINF:-1 tvg-logo="{item["img"]}" group-title="{item["group"]}",{item["title"]}\n{proxy_link}'
        m3u_lines.append(line)
        
    M3U_CACHE = "\n".join(m3u_lines)
    LAST_UPDATE_TIME = time.time()
    IS_UPDATING = False
    print(">>> GÜNCELLEME BİTTİ (VOD UYUMLU)!")

# --- ROTALAR ---

@app.route('/')
def playlist():
    global M3U_CACHE
    base_host = request.host_url
    
    if M3U_CACHE is None:
        update_ram_cache(base_host)
    elif (time.time() - LAST_UPDATE_TIME) > CACHE_SURESI:
        threading.Thread(target=update_ram_cache, args=(base_host,)).start()
        
    return Response(M3U_CACHE, mimetype='audio/x-mpegurl')

# --- YENİ ROTA: .mp4 Uzantılı Sahte Video Linki ---
@app.route('/stream/<hex_url>.mp4')
def stream_video(hex_url):
    try:
        # Hex kodunu tekrar normal URL'ye çevir
        original_url = binascii.unhexlify(hex_url).decode('utf-8')
        
        # Videoyu çöz
        real_url = resolve_video(original_url)
        
        if real_url:
            return redirect(real_url)
        else:
            return "Video Bulunamadı", 404
    except Exception as e:
        print(f"Hata: {e}")
        return "Hatali Link", 400

@app.route('/refresh')
def force_refresh():
    base_host = request.host_url
    threading.Thread(target=update_ram_cache, args=(base_host,)).start()
    return "Guncelleniyor..."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
