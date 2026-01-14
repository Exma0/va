from flask import Flask, Response, request, redirect
from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import concurrent.futures

app = Flask(__name__)

# --- AYARLAR ---
SITE_URL = "https://dizipal1219.com"
PORT = 5000

# Kaynaklar
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
    """Senin çalışan kodundaki Session ayarları"""
    session = requests.Session(impersonate="chrome120")
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{SITE_URL}/",
        "Origin": SITE_URL
    }
    return session

def resolve_video_logic(iframe_url):
    """
    SENİN KODUNDAKİ 'm3u8_coz' FONKSİYONUNUN BİREBİR AYNISI
    """
    if not iframe_url: return None
    if iframe_url.startswith("//"): iframe_url = "https:" + iframe_url
    if iframe_url.startswith("/"): iframe_url = SITE_URL + iframe_url

    session = get_session()
    # ÖNEMLİ: Iframe'e giderken Referer ana site olmalı
    session.headers.update({"Referer": SITE_URL})

    print(f"[ÇÖZÜCÜ] Iframe deneniyor: {iframe_url}")

    # 1. Yöntem: Regex (Senin kodundaki hızlı yöntem)
    try:
        html = session.get(iframe_url, timeout=5).text
        
        # Standart file yapısı
        match = re.search(r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', html)
        if match: return match.group(1)
        
        # JS içindeki gizli yapı
        match2 = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', html)
        if match2: return match2.group(1)
    except Exception as e:
        print(f"[REGEX HATA] {e}")

    # 2. Yöntem: yt-dlp (Sadece regex başarısız olursa)
    # Not: Senin loglarda yt-dlp patladığı için burayı pasif bırakıp sadece Regex'e güvenmek daha stabil olabilir
    # Ama yedek olarak dursun.
    try:
        import yt_dlp
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(iframe_url, download=False)
            return info.get('url')
    except:
        return None

def find_video_on_page(url):
    """Sayfaya girip iframe'i bulur ve çözer"""
    print(f"\n--- İSTEK: {url} ---")
    session = get_session()
    
    try:
        resp = session.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # A) DİZİ KONTROLÜ (Senin kodunda 'for b in bolumler' mantığı)
        # Eğer bu bir dizi ana sayfasıysa, video yoktur. İlk bölüme gitmemiz lazım.
        episode_links = soup.select("div.episode-item a")
        if episode_links:
            first_ep = episode_links[0]['href']
            if not first_ep.startswith("http"): first_ep = SITE_URL + first_ep
            
            # Eğer şu anki URL zaten bölüm URL'si değilse yönlendir
            if first_ep != url:
                print(f"[YÖNLENDİRME] Dizi tespit edildi. İlk bölüme gidiliyor: {first_ep}")
                return find_video_on_page(first_ep)

        # B) IFRAME BULMA (Senin kodundaki 'soup.select_one' mantığı)
        iframe = soup.select_one(".series-player-container iframe") or \
                 soup.select_one("div#vast_new iframe") or \
                 soup.select_one("iframe[src*='vidmoly']") or \
                 soup.select_one("iframe")
                 
        if not iframe:
            print("[HATA] Iframe bulunamadı.")
            return None
            
        src = iframe.get('src') or iframe.get('data-src')
        
        # Reklam kontrolü
        if "google" in src or "youtube" in src:
            return None
            
        return resolve_video_logic(src)

    except Exception as e:
        print(f"[GENEL HATA] {e}")
        return None

def fetch_category_items(kategori):
    """Kategoriyi tarar (Senin kodundaki 'linkleri_topla' mantığı)"""
    session = get_session()
    try:
        resp = session.get(kategori["url"], timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Senin kodundaki seçici
        items = soup.select("article.type2 ul li, div.movie-item")
        parsed = []
        
        for item in items:
            a = item.select_one("a")
            if not a: continue
            
            link = a['href']
            if not link.startswith("http"): link = SITE_URL + link
            
            title = item.select_one(".title, .name").text.strip() if item.select_one(".title, .name") else "Bilinmeyen"
            img = item.select_one("img")
            img_url = img['src'] if img else ""
            
            parsed.append({
                "title": title, "link": link, "img": img_url, "group": kategori["ad"]
            })
        return parsed
    except:
        return []

# --- ROTALAR ---

@app.route('/')
def index():
    base_host = request.host_url.rstrip('/')
    m3u = "#EXTM3U\n"
    
    # Hızlı olması için Parallel Threading (Senin kodundaki ThreadPoolExecutor)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_category_items, k) for k in KAYNAKLAR]
        for f in concurrent.futures.as_completed(futures):
            for item in f.result():
                enc_link = urllib.parse.quote(item['link'])
                proxy = f"{base_host}/watch?url={enc_link}"
                m3u += f'#EXTINF:-1 tvg-logo="{item["img"]}" group-title="{item["group"]}",{item["title"]}\n{proxy}\n'
        
    return Response(m3u, mimetype='audio/x-mpegurl')

@app.route('/watch')
def watch():
    target_url = request.args.get('url')
    if not target_url: return "URL Yok", 400
    target_url = urllib.parse.unquote(target_url)
    
    real_url = find_video_on_page(target_url)
    
    if real_url:
        return redirect(real_url)
    else:
        return "Video Cozulemedi", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
