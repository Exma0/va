from flask import Flask, Response, request, redirect, jsonify
from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import concurrent.futures
import time
import threading
import uuid

app = Flask(__name__)

# --- AYARLAR ---
SITE_URL = "https://dizipal1219.com"
PORT = 5000
MAX_SAYFA = 3      
CACHE_SURESI = 3600

# --- BELLEK VE ID HARİTASI ---
# XC API'de her videonun sayısal bir ID'si olması gerekir.
# Linkleri ID'lerle eşleştireceğiz.
STREAM_MAP = {}       # { 1001: "https://dizipal...", 1002: "..." }
CATEGORY_MAP = {}     # { "1": "Yeni Filmler", "2": "Netflix" ... }
ALL_STREAMS = []      # XC Formatındaki tüm videolar
LAST_UPDATE_TIME = 0
IS_UPDATING = False

# Kategorileri ID ile tanımlayalım
KAYNAKLAR = [
    {"id": "1", "ad": "Yeni Filmler", "url": f"{SITE_URL}/filmler", "tur": "Film"},
    {"id": "2", "ad": "Yeni Diziler", "url": f"{SITE_URL}/diziler", "tur": "Dizi"},
    {"id": "3", "ad": "Netflix", "url": f"{SITE_URL}/koleksiyon/netflix", "tur": "Platform"},
    {"id": "4", "ad": "Exxen", "url": f"{SITE_URL}/koleksiyon/exxen", "tur": "Platform"},
    {"id": "5", "ad": "BluTV", "url": f"{SITE_URL}/koleksiyon/blutv", "tur": "Platform"},
    {"id": "6", "ad": "Disney+", "url": f"{SITE_URL}/koleksiyon/disney", "tur": "Platform"},
    {"id": "7", "ad": "Amazon Prime", "url": f"{SITE_URL}/koleksiyon/amazon-prime", "tur": "Platform"},
]

# --- SCRAPER MODÜLLERİ ---
def get_session():
    session = requests.Session(impersonate="chrome120")
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{SITE_URL}/",
        "Origin": SITE_URL
    }
    return session

def resolve_video(dizipal_url):
    print(f"\n[OYNATILIYOR] {dizipal_url}")
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
                return resolve_video(first_ep)

        iframe = soup.select_one(".series-player-container iframe") or \
                 soup.select_one("div#vast_new iframe") or \
                 soup.select_one("iframe[src*='vidmoly']")
                 
        if not iframe: return None
        src = iframe.get('src')
        if not src: return None
        
        if "google" in src or "youtube" in src: return None
        if src.startswith("//"): src = "https:" + src
        if src.startswith("/"): src = SITE_URL + src

        session.headers.update({"Referer": SITE_URL})
        html = session.get(src, timeout=8).text
        
        match = re.search(r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', html)
        if match: return match.group(1)
        
        match2 = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', html)
        if match2: return match2.group(1)
        
        return None
    except: return None

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
                    "title": title, "link": link, "img": img_url, "cat_id": kategori["id"]
                })
        except: break
    return parsed_items

def update_xc_cache():
    global ALL_STREAMS, STREAM_MAP, LAST_UPDATE_TIME, IS_UPDATING
    if IS_UPDATING: return
    IS_UPDATING = True
    print("\n>>> XC VERİTABANI GÜNCELLENİYOR...")
    
    temp_streams = []
    temp_map = {}
    stream_id_counter = 10000 
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_category_content, k) for k in KAYNAKLAR]
        for f in concurrent.futures.as_completed(futures):
            items = f.result()
            for item in items:
                stream_id_counter += 1
                s_id = stream_id_counter
                
                # XC Formatında JSON Objesi
                stream_obj = {
                    "num": s_id,
                    "name": item['title'],
                    "stream_type": "movie", # CANLI TV OLMAMASI İÇİN ÖNEMLİ
                    "stream_id": s_id,
                    "stream_icon": item['img'],
                    "rating": "5",
                    "added": "123456789",
                    "category_id": item['cat_id'],
                    "container_extension": "mp4" # Oynatıcıyı VOD moduna zorlar
                }
                
                temp_streams.append(stream_obj)
                temp_map[s_id] = item['link']
    
    ALL_STREAMS = temp_streams
    STREAM_MAP = temp_map
    LAST_UPDATE_TIME = time.time()
    IS_UPDATING = False
    print(f">>> GÜNCELLEME BİTTİ! Toplam {len(ALL_STREAMS)} içerik.")

# --- FLASK XTREAM CODES API ROTALARI ---

@app.route('/player_api.php')
def xc_api():
    """IPTV Smarters'ın Konuştuğu Ana API"""
    global ALL_STREAMS
    
    username = request.args.get('username')
    password = request.args.get('password')
    action = request.args.get('action')
    
    # 1. GİRİŞ İŞLEMİ (Login)
    if not action:
        return jsonify({
            "user_info": {
                "username": username,
                "password": password,
                "status": "Active",
                "is_trial": "0",
                "active_cons": "1",
                "created_at": "1690000000",
                "exp_date": "1990000000", # Sınırsız üyelik
                "allowed_output_formats": ["m3u8", "ts", "mp4"]
            },
            "server_info": {
                "url": request.host_url,
                "port": PORT,
                "https_port": PORT,
                "server_protocol": "http",
                "rtmp_port": "8880",
                "timezone": "Europe/Istanbul",
                "timestamp_now": int(time.time()),
                "time_now": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            }
        })

    # Güncelleme Kontrolü
    if not ALL_STREAMS or (time.time() - LAST_UPDATE_TIME > CACHE_SURESI):
        if not IS_UPDATING:
            threading.Thread(target=update_xc_cache).start()
            if not ALL_STREAMS: time.sleep(5) # İlk açılışta biraz bekle

    # 2. VOD KATEGORİLERİ (Movies Categories)
    if action == "get_vod_categories":
        cats = [{"category_id": k["id"], "category_name": k["ad"], "parent_id": 0} for k in KAYNAKLAR]
        return jsonify(cats)
    
    # 3. VOD LİSTESİ (Movies List)
    if action == "get_vod_streams":
        # Kategori filtresi var mı?
        cat_id = request.args.get('category_id')
        if cat_id:
            filtered = [s for s in ALL_STREAMS if s['category_id'] == cat_id]
            return jsonify(filtered)
        return jsonify(ALL_STREAMS)

    # Dizi kategorileri sorarsa boş dön (Hepsini filme attık ki kolay açılsın)
    if action == "get_series_categories":
        return jsonify([])

    return jsonify([])

# --- VİDEO OYNATMA ROTASI (XC Formatı) ---
# Format: /movie/{username}/{password}/{stream_id}.{ext}
@app.route('/movie/<user>/<pwd>/<int:stream_id>.mp4')
def play_movie(user, pwd, stream_id):
    target_url = STREAM_MAP.get(stream_id)
    
    if not target_url:
        return "Video Bulunamadi", 404
        
    real_url = resolve_video(target_url)
    
    if real_url:
        return redirect(real_url)
    else:
        return "Video Cozulemedi", 404

if __name__ == '__main__':
    # Başlangıçta veriyi çek
    threading.Thread(target=update_xc_cache).start()
    print("Sunucu Başlatıldı. IPTV Smarters'a 'Xtream Codes' ile giriş yapın.")
    app.run(host='0.0.0.0', port=PORT)
