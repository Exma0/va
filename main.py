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

# Kaynaklar Listesi
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
    """Bot korumasını aşan tarayıcı taklidi"""
    session = requests.Session(impersonate="chrome120")
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"{SITE_URL}/",
        "Origin": SITE_URL,
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    return session

def resolve_video(dizipal_url):
    """
    Hem Dizi hem Film için akıllı link çözücü.
    yt-dlp yerine doğrudan curl_cffi ve Regex kullanır (Daha hızlı ve engellenmez).
    """
    print(f"\n--- ANALİZ BAŞLADI: {dizipal_url} ---")
    session = get_session()
    
    try:
        # 1. Sayfaya Git
        resp = session.get(dizipal_url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # --- DİZİ KONTROLÜ (DÜZELTME BURADA) ---
        # Eğer sayfada video yoksa ama bölüm listesi varsa, bu bir dizi ana sayfasıdır.
        # İlk bölüme yönlendirmemiz lazım.
        episode_list = soup.select("div.episode-item a")
        if episode_list:
            first_ep_link = episode_list[0]['href']
            if not first_ep_link.startswith("http"): first_ep_link = SITE_URL + first_ep_link
            print(f"[YÖNLENDİRME] Bu bir dizi sayfası. İlk bölüme gidiliyor: {first_ep_link}")
            
            # Kendini tekrar çağır (Recursive) ama bu sefer bölüm linkiyle
            # Sonsuz döngüye girmesin diye kontrol
            if first_ep_link != dizipal_url:
                return resolve_video(first_ep_link)

        # --- OYNATICI (IFRAME) BULMA ---
        iframes = soup.find_all('iframe')
        target_iframe = None
        
        for iframe in iframes:
            src = iframe.get('src') or iframe.get('data-src')
            if not src: continue
            # Reklamları atla
            if "google" in src or "youtube" in src or "facebook" in src: continue
            
            # Vidmoly vb. genellikle bu domainlerde olur
            # Loglardaki 'ag2m4.cfd' domainini yakalamak için
            target_iframe = src
            break # İlk geçerliyi al
            
        if not target_iframe:
            print("[HATA] Iframe bulunamadı.")
            return None

        # Link düzeltmeleri
        if target_iframe.startswith("//"): target_iframe = "https:" + target_iframe
        if target_iframe.startswith("/"): target_iframe = SITE_URL + target_iframe
        
        print(f"[KAYNAK BULUNDU] Iframe: {target_iframe}")

        # --- OYNATICIYI ÇÖZME (MANUEL REGEX) ---
        # yt-dlp timeout yiyor, bu yüzden curl_cffi ile biz giriyoruz.
        # Referer olarak site adresini göstermek zorundayız yoksa açılmaz.
        session.headers.update({"Referer": SITE_URL})
        
        player_html = session.get(target_iframe, timeout=10).text
        
        # 1. Yöntem: Standart 'file: "..."' yapısı
        match = re.search(r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', player_html)
        if match:
            m3u8 = match.group(1)
            print(f"[BAŞARILI] Link Çözüldü: {m3u8}")
            return m3u8
        
        # 2. Yöntem: JavaScript içine gizlenmiş linkler (Vidmoly Packing)
        # Genellikle 'sources: [{file:"..."}]' şeklindedir
        match2 = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', player_html)
        if match2:
            m3u8 = match2.group(1)
            print(f"[BAŞARILI] (JS) Link Çözüldü: {m3u8}")
            return m3u8

        print("[BAŞARISIZ] Regex linki bulamadı. Site yapısı değişmiş olabilir.")
        # Burada son çare olarak yt-dlp denenebilir ama senin loglarda yt-dlp patladığı için buraya koymadım.
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
    target_url = urllib.parse.unquote(target_url)
    
    real_url = resolve_video(target_url)
    
    if real_url:
        return redirect(real_url)
    else:
        return "Video Bulunamadı (Server Loguna Bakın)", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
