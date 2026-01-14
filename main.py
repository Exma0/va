from flask import Flask, Response, request, redirect
from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import concurrent.futures
import time
import threading
import binascii
import socket

app = Flask(__name__)

# --- AYARLAR ---
SITE_URL = "https://dizipal1219.com"
PORT = 5000
MAX_SAYFA = 3       # Hız için her kategoriden 3 sayfa
CACHE_SURESI = 3600 # 1 Saatte bir yenile

# Bellek Değişkenleri
M3U_CACHE = None
LAST_UPDATE = 0
IS_UPDATING = False

KAYNAKLAR = [
    {"ad": "Yeni Filmler", "url": f"{SITE_URL}/filmler"},
    {"ad": "Yeni Diziler", "url": f"{SITE_URL}/diziler"},
    {"ad": "Netflix", "url": f"{SITE_URL}/koleksiyon/netflix"},
    {"ad": "Exxen", "url": f"{SITE_URL}/koleksiyon/exxen"},
    {"ad": "BluTV", "url": f"{SITE_URL}/koleksiyon/blutv"},
    {"ad": "Disney+", "url": f"{SITE_URL}/koleksiyon/disney"},
    {"ad": "Amazon Prime", "url": f"{SITE_URL}/koleksiyon/amazon-prime"},
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
    print(f"\n[İSTEK] {dizipal_url}")
    session = get_session()
    try:
        resp = session.get(dizipal_url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Dizi Kontrolü (Bölüm Listesi Varsa İlkine Git)
        episode_links = soup.select("div.episode-item a")
        if episode_links:
            first_ep = episode_links[0]['href']
            if not first_ep.startswith("http"): first_ep = SITE_URL + first_ep
            if first_ep != dizipal_url:
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

        # Link Çözme (Regex)
        session.headers.update({"Referer": SITE_URL})
        html = session.get(src, timeout=8).text
        
        match = re.search(r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', html)
        if match: return match.group(1)
        
        match2 = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', html)
        if match2: return match2.group(1)
        
        return None
    except: return None

def fetch_content(kategori):
    session = get_session()
    parsed = []
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
                
                parsed.append({"title": title, "link": link, "img": img_url, "group": kategori["ad"]})
        except: break
    return parsed

def update_cache(host_url):
    global M3U_CACHE, LAST_UPDATE, IS_UPDATING
    if IS_UPDATING: return
    IS_UPDATING = True
    print("\n>>> LİSTE ARKA PLANDA HAZIRLANIYOR...")
    
    temp = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_content, k) for k in KAYNAKLAR]
        for f in concurrent.futures.as_completed(futures):
            temp.extend(f.result())
            
    lines = ["#EXTM3U"]
    for item in temp:
        # Linki şifrele ve .mp4 ekle (VOD gibi görünsün diye)
        hex_url = binascii.hexlify(item['link'].encode()).decode()
        proxy = f"{host_url}stream/{hex_url}.mp4"
        lines.append(f'#EXTINF:-1 tvg-logo="{item["img"]}" group-title="{item["group"]}",{item["title"]}\n{proxy}')
        
    M3U_CACHE = "\n".join(lines)
    LAST_UPDATE = time.time()
    IS_UPDATING = False
    print(f">>> LİSTE HAZIR! ({len(temp)} içerik)")

# --- ROTALAR ---

@app.route('/playlist.m3u')
def get_playlist():
    global M3U_CACHE
    base = request.host_url
    if M3U_CACHE is None:
        update_cache(base)
    elif (time.time() - LAST_UPDATE) > CACHE_SURESI:
        threading.Thread(target=update_cache, args=(base,)).start()
    return Response(M3U_CACHE, mimetype='audio/x-mpegurl')

@app.route('/stream/<hex_url>.mp4')
def stream_video(hex_url):
    try:
        url = binascii.unhexlify(hex_url).decode()
        real = resolve_video(url)
        if real: return redirect(real)
        return "Video Bulunamadi", 404
    except: return "Hata", 400

if __name__ == '__main__':
    # IP Adresini Otomatik Bulma
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        IP = s.getsockname()[0]
    except: IP = '127.0.0.1'
    finally: s.close()

    print("\n" + "="*50)
    print(" SUNUCU ÇALIŞIYOR! IPTV SMARTERS'A GİRİLECEK LİNK:")
    print(f"\n http://{IP}:{PORT}/playlist.m3u \n")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=PORT)
