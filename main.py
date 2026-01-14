from flask import Flask, Response, request, redirect
from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import yt_dlp
import concurrent.futures

app = Flask(__name__)

# --- AYARLAR ---
SITE_URL = "https://dizipal1219.com"
PORT = 5000

# Birleştirilecek Kategoriler
# Sunucu bu linklerin hepsini gezip tek liste yapacak
KAYNAKLAR = [
    {"ad": "Yeni Filmler", "url": f"{SITE_URL}/filmler", "tur": "Film"},
    {"ad": "Yeni Diziler", "url": f"{SITE_URL}/diziler", "tur": "Dizi"},
    {"ad": "Netflix", "url": f"{SITE_URL}/koleksiyon/netflix", "tur": "Platform"},
    {"ad": "Exxen", "url": f"{SITE_URL}/koleksiyon/exxen", "tur": "Platform"},
    {"ad": "BluTV", "url": f"{SITE_URL}/koleksiyon/blutv", "tur": "Platform"},
    {"ad": "Disney+", "url": f"{SITE_URL}/koleksiyon/disney", "tur": "Platform"},
    {"ad": "Amazon Prime", "url": f"{SITE_URL}/koleksiyon/amazon-prime", "tur": "Platform"},
    {"ad": "Gain", "url": f"{SITE_URL}/koleksiyon/gain", "tur": "Platform"}
]

def get_session():
    session = requests.Session(impersonate="chrome120")
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{SITE_URL}/"
    }
    return session

def fetch_category(kategori):
    """Tek bir kategoriyi tarayıp içerikleri döndürür"""
    session = get_session()
    try:
        resp = session.get(kategori["url"], timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        items = soup.select("article.type2 ul li, div.movie-item, div.episode-item")
        parsed_items = []
        
        for item in items:
            a = item.select_one("a")
            if not a: continue
            
            link = a['href']
            if not link.startswith("http"): link = SITE_URL + link
            
            title = item.select_one(".title, .name").text.strip() if item.select_one(".title, .name") else "Bilinmeyen"
            img = item.select_one("img")
            img_url = img['src'] if img else ""
            
            # Grup ismini belirle (Örn: Filmler, Diziler, Netflix)
            grup = kategori["ad"]
            
            parsed_items.append({
                "title": title,
                "link": link,
                "img": img_url,
                "group": grup
            })
        return parsed_items
    except Exception as e:
        print(f"Hata ({kategori['ad']}): {e}")
        return []

def resolve_video(dizipal_url):
    """Videoyu oynat denince çalışır"""
    session = get_session()
    try:
        session.headers.update({"Referer": SITE_URL})
        resp = session.get(dizipal_url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        iframe = soup.select_one(".series-player-container iframe, #vast_new iframe")
        if not iframe: return None
        
        src = iframe.get('src')
        if src.startswith("//"): src = "https:" + src
        
        # 1. Regex Hızlı Çözüm
        iframe_html = session.get(src, headers={"Referer": SITE_URL}).text
        match = re.search(r'file:\s*"([^"]+)"', iframe_html)
        if match: return match.group(1)
        
        # 2. yt-dlp Yedek Çözüm
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(src, download=False)
            return info.get('url')
    except:
        return None

# --- TEK LİNK ROTA ---
@app.route('/hepsi.m3u')
def all_in_one():
    base_host = request.host_url.rstrip('/')
    m3u_content = "#EXTM3U\n"
    
    # Hız için tüm kategorileri aynı anda (Paralel) çekiyoruz
    all_results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_cat = {executor.submit(fetch_category, kat): kat for kat in KAYNAKLAR}
        for future in concurrent.futures.as_completed(future_to_cat):
            items = future.result()
            all_results.extend(items)
    
    # M3U Dosyasını Oluştur
    for item in all_results:
        encoded_link = urllib.parse.quote(item['link'])
        proxy_link = f"{base_host}/watch?url={encoded_link}"
        
        # IPTV Formatı
        m3u_content += f'#EXTINF:-1 tvg-logo="{item["img"]}" group-title="{item["group"]}",{item["title"]}\n{proxy_link}\n'
        
    return Response(m3u_content, mimetype='audio/x-mpegurl')

@app.route('/watch')
def watch():
    target_url = request.args.get('url')
    if not target_url: return "URL Yok", 400
    
    real_url = resolve_video(target_url)
    if real_url:
        return redirect(real_url)
    return "Video Bulunamadı", 404

@app.route('/')
def index():
    return "Sunucu Aktif. Linkiniz: /hepsi.m3u"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
