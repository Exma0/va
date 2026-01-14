from flask import Flask, Response, request, redirect
from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import yt_dlp
import concurrent.futures
import time

app = Flask(__name__)

# --- AYARLAR ---
SITE_URL = "https://dizipal1219.com"
PORT = 5000

KAYNAKLAR = [
    {"ad": "Yeni Filmler", "url": f"{SITE_URL}/filmler", "tur": "Film"},
    {"ad": "Yeni Diziler", "url": f"{SITE_URL}/diziler", "tur": "Dizi"},
    {"ad": "Netflix", "url": f"{SITE_URL}/koleksiyon/netflix", "tur": "Platform"},
    # Diğerlerini buraya ekleyebilirsin...
]

def get_session():
    """Gerçek bir tarayıcı gibi davranan oturum açar"""
    session = requests.Session(impersonate="chrome120")
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{SITE_URL}/",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    return session

def resolve_video(dizipal_url):
    """
    GÜÇLENDİRİLMİŞ ÇÖZÜCÜ:
    Sayfadaki tüm potansiyel oynatıcıları dener.
    """
    print(f"\n--- VİDEO ANALİZİ BAŞLADI: {dizipal_url} ---")
    session = get_session()
    
    try:
        # 1. Sayfaya Git
        resp = session.get(dizipal_url, timeout=15)
        if resp.status_code != 200:
            print(f"[HATA] Sayfa açılamadı: {resp.status_code}")
            return None
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 2. Sayfadaki TÜM Iframe'leri bul (Sınırlama yapmıyoruz)
        iframes = soup.find_all('iframe')
        print(f"[BİLGİ] Sayfada {len(iframes)} adet iframe bulundu.")
        
        valid_src = None
        
        # 3. Doğru Iframe'i bulmak için döngü
        for iframe in iframes:
            src = iframe.get('src') or iframe.get('data-src')
            if not src: continue
            
            # Reklamları ele
            if "google" in src or "youtube" in src or "facebook" in src:
                continue
                
            # Link düzeltme
            if src.startswith("//"): src = "https:" + src
            if src.startswith("/"): src = SITE_URL + src
            
            print(f"[DENENİYOR] Potansiyel Kaynak: {src}")
            
            # Bu link muhtemelen video oynatıcıdır, yt-dlp ile deneyelim
            try:
                ydl_opts = {
                    'quiet': True, 
                    'no_warnings': True,
                    'format': 'best',
                    # Referer header'ı bazı siteler için şarttır
                    'http_headers': {'Referer': SITE_URL} 
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # extract_info ağırdır ama en garantisidir
                    info = ydl.extract_info(src, download=False)
                    
                    if 'url' in info:
                        print(f"[BAŞARILI] Video Linki Çözüldü: {info['url'][:50]}...")
                        return info['url']
                    elif 'entries' in info:
                        # Bazen playlist döner, ilkini al
                        return info['entries'][0]['url']
                        
            except Exception as e:
                print(f"[BAŞARISIZ] yt-dlp bu kaynağı çözemedi: {e}")
                continue

        print("[KRİTİK] Hiçbir iframe çözülemedi.")
        return None

    except Exception as e:
        print(f"[GENEL HATA] {e}")
        return None

def fetch_category(kategori):
    session = get_session()
    print(f"Kategori Taranıyor: {kategori['ad']}...")
    try:
        resp = session.get(kategori["url"], timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        items = soup.select("article.type2 ul li, div.movie-item, div.episode-item")
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
    except Exception as e:
        print(f"Hata ({kategori['ad']}): {e}")
        return []

@app.route('/hepsi.m3u')
def all_in_one():
    base_host = request.host_url.rstrip('/')
    m3u = "#EXTM3U\n"
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_category, k) for k in KAYNAKLAR]
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
    
    # URL Decode işlemi (Önemli! Bazen %2F gibi karakterler sorun çıkarır)
    target_url = urllib.parse.unquote(target_url)
    
    real_url = resolve_video(target_url)
    
    if real_url:
        return redirect(real_url)
    else:
        return "Video Bulunamadı (Terminaldeki Loglara Bakın)", 404

if __name__ == '__main__':
    # Debug modu açık, hataları ekrana basar
    app.run(host='0.0.0.0', port=PORT, debug=True)
