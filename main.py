from gevent import monkey; monkey.patch_all()

import requests, urllib3, logging, re, unicodedata, difflib
from flask import Flask, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from gevent.pywsgi import WSGIServer

# ================= CONFIG (AYARLAR) =================
PORT = 8080

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# EPG Kaynağı
EPG_URL = "https://epgshare01.online/epgshare01/epg_ripper_TR1.xml.gz"

# Logo Ayarları (GitHub API)
LOGO_API_URL = "https://api.github.com/repos/tv-logo/tv-logos/contents/countries/turkey"
LOGO_RAW_BASE = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/turkey/"

# Kaynak Referansları
REF_ANDRO = 'https://taraftarium.is/'
REF_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/'
REF_VAVOO = 'https://vavoo.to/'

SOURCE_VAVOO_API = "https://vavoo.to/live2/index"
URL_ANDRO = 'https://andro.adece12.sbs/checklist/{}.m3u8'
URL_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/{}.m3u8'

# Vavoo Sabit URL Şablonu (Senin İstediğin Format)
URL_VAVOO_TEMPLATE = "https://vavoo.to/play/{}/index.m3u8"

urllib3.disable_warnings()
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Global Logo Havuzu
AVAILABLE_LOGOS = []

# ================= SESSION =================
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Connection": "keep-alive"})

retry = Retry(
    total=3,
    backoff_factor=0.1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"]
)

adapter = HTTPAdapter(
    pool_connections=200,
    pool_maxsize=200,
    max_retries=retry,
    pool_block=False
)

session.mount("http://", adapter)
session.mount("https://", adapter)

# ================= LOGO VE İSİM İŞLEME MOTORU =================

def fetch_available_logos():
    """
    Sunucu başladığında GitHub API'den mevcut logo dosya isimlerini çeker.
    """
    global AVAILABLE_LOGOS
    print("Logolar GitHub'dan çekiliyor...")
    try:
        r = requests.get(LOGO_API_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            AVAILABLE_LOGOS = [item['name'] for item in data if item['name'].endswith('.png')]
            print(f"Başarılı! {len(AVAILABLE_LOGOS)} adet logo hafızaya alındı.")
        else:
            print(f"Logo listesi çekilemedi. Hata Kodu: {r.status_code}")
    except Exception as e:
        print(f"Logo API Hatası: {e}")

def simplify_text(text):
    """Metni karşılaştırma için en sade haline getirir."""
    text = str(text).lower()
    if text.endswith(".png"): text = text[:-4]
    if text.endswith("-tr"): text = text[:-3]
    
    replacements = {'ı': 'i', 'ğ': 'g', 'ü': 'u', 'ş': 's', 'ö': 'o', 'ç': 'c'}
    for src, dest in replacements.items():
        text = text.replace(src, dest)
    
    return re.sub(r'[^a-z0-9]', '', text)

def clean_channel_name(name):
    """(1), (7), (Canlı) vb. temizler."""
    if not name: return ""
    clean = re.sub(r'\s*\([^)]*\)$', '', name)
    return clean.strip()

def find_best_logo_url(channel_name):
    """Kanal ismine en çok benzeyen logoyu bulur."""
    if not AVAILABLE_LOGOS: return ""
        
    target = simplify_text(channel_name)
    best_match = None
    best_ratio = 0.0
    
    for filename in AVAILABLE_LOGOS:
        simple_filename = simplify_text(filename)
        
        if target == simple_filename:
            return LOGO_RAW_BASE + filename
            
        ratio = difflib.SequenceMatcher(None, target, simple_filename).ratio()
        if target in simple_filename or simple_filename in target:
            ratio += 0.2
            
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = filename
            
    if best_ratio > 0.6:
        return LOGO_RAW_BASE + best_match
    
    return ""

# ================= KANAL LİSTELERİ =================
ANDRO_LIST = [
    {'name':'BeIN Sports 1','id':'receptestt'},
    {'name':'BeIN Sports 2','id':'androstreamlivebs2'},
    {'name':'BeIN Sports 3','id':'androstreamlivebs3'},
    {'name':'BeIN Sports 4','id':'androstreamlivebs4'},
    {'name':'BeIN Sports 5','id':'androstreamlivebs5'},
    {'name':'BeIN Sports Max 1','id':'androstreamlivebsm1'},
    {'name':'BeIN Sports Max 2','id':'androstreamlivebsm2'},
    {'name':'S Sport','id':'androstreamlivess1'},
    {'name':'S Sport 2','id':'androstreamlivess2'},
    {'name':'S Sport Plus','id':'androstreamlivessplus1'},
    {'name':'Tivibu Spor','id':'androstreamlivets'},
    {'name':'Tivibu Spor 1','id':'androstreamlivets1'},
    {'name':'Tivibu Spor 2','id':'androstreamlivets2'},
    {'name':'Tivibu Spor 3','id':'androstreamlivets3'},
    {'name':'Tivibu Spor 4','id':'androstreamlivets4'},
    {'name':'Smart Spor 1','id':'androstreamlivesm1'},
    {'name':'Smart Spor 2','id':'androstreamlivesm2'},
    {'name':'Eurosport 1','id':'androstreamlivees1'},
    {'name':'Eurosport 2','id':'androstreamlivees2'},
    {'name':'İDMAN TV','id':'androstreamliveidm'},
    {'name':'TRT 1','id':'androstreamlivetrt1'},
    {'name':'TRT Spor','id':'androstreamlivetrts'},
    {'name':'TRT Spor Yıldız','id':'androstreamlivetrtsy'},
    {'name':'ATV','id':'androstreamliveatv'},
    {'name':'A Spor','id':'androstreamliveas'},
    {'name':'A2','id':'androstreamlivea2'},
    {'name':'TV8','id':'androstreamlivetv8'},
    {'name':'TV8.5','id':'androstreamlivetv85'},
    {'name':'FB TV','id':'androstreamlivefb'},
    {'name':'GS TV','id':'androstreamlivegs'},
    {'name':'Exxen TV','id':'androstreamliveexn'},
    {'name':'Exxen Sports 1','id':'androstreamliveexn1'},
    {'name':'Exxen Sports 2','id':'androstreamliveexn2'},
    {'name':'Exxen Sports 3','id':'androstreamliveexn3'},
    {'name':'Exxen Sports 4','id':'androstreamliveexn4'},
    {'name':'Exxen Sports 5','id':'androstreamliveexn5'},
    {'name':'Exxen Sports 6','id':'androstreamliveexn6'},
]

HTML_LIST = [
    {'name':'BeIN Sports 1 (Alt)','id':'yayininat'},
    {'name':'BeIN Sports 2 (Alt)','id':'yayinb2'},
    {'name':'BeIN Sports 3 (Alt)','id':'yayinb3'},
    {'name':'BeIN Sports 4 (Alt)','id':'yayinb4'},
    {'name':'BeIN Sports 5 (Alt)','id':'yayinb5'},
    {'name':'S Sport (Alt)','id':'yayinss'},
    {'name':'S Sport 2 (Alt)','id':'yayinss2'},
    {'name':'Tivibu 1 (Alt)','id':'yayint1'},
    {'name':'Tivibu 2 (Alt)','id':'yayint2'},
    {'name':'Tivibu 3 (Alt)','id':'yayint3'},
    {'name':'Smartspor (Alt)','id':'yayinsmarts'},
    {'name':'Smartspor 2 (Alt)','id':'yayinsms2'},
    {'name':'TRT Spor (Alt)','id':'yayintrtspor'},
    {'name':'TRT 1 (Alt)','id':'yayintrt1'},
    {'name':'A Spor (Alt)','id':'yayinas'},
    {'name':'ATV (Alt)','id':'yayinatv'},
    {'name':'TV 8 (Alt)','id':'yayintv8'},
    {'name':'TV 8,5 (Alt)','id':'yayintv85'},
]

# ================= ROOT (M3U) =================
@app.route('/')
def root():
    out = [f'#EXTM3U x-tvg-url="{EPG_URL}"']

    def add_channel(group, raw_name, real_url, ref):
        # 1. İsmi Temizle
        name = clean_channel_name(raw_name)
        # 2. Logo Bul
        logo_url = find_best_logo_url(name)
        
        # 3. Satırları Ekle
        out.append(f'#EXTINF:-1 group-title="{group}" tvg-name="{name}" tvg-logo="{logo_url}",{name}')
        out.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        out.append(f'#EXTVLCOPT:http-referrer={ref}')
        out.append(f'#EXTHTTP:{{"User-Agent":"{USER_AGENT}","Referer":"{ref}"}}')
        out.append(real_url)

    # ANDRO
    for c in ANDRO_LIST:
        add_channel("Andro", c["name"], URL_ANDRO.format(c["id"]), REF_ANDRO)

    # HTML
    for c in HTML_LIST:
        add_channel("HTML", c["name"], URL_HTML.format(c["id"]), REF_HTML)

    # VAVOO (SABİT FORMAT YAPISI)
    try:
        r = session.get(SOURCE_VAVOO_API, timeout=6, verify=False)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for i in data:
                    group = i.get("group")
                    source_url = i.get("url")
                    raw_name = i.get("name")
                    
                    if group == "Turkey" and source_url and raw_name:
                        # 1. URL'den ID'yi çek (Regex ile rakamları al)
                        # Örn: .../play3/123456.m3u8 -> 123456
                        match = re.search(r'([0-9]+)\.m3u8', source_url)
                        
                        if match:
                            vavoo_id = match.group(1)
                            # 2. İstenilen SABİT formata çevir
                            fixed_url = URL_VAVOO_TEMPLATE.format(vavoo_id)
                            
                            add_channel("Vavoo", raw_name, fixed_url, REF_VAVOO)
                        
    except Exception as e:
        print(f"Vavoo Fetch Hatası: {e}")
        pass

    return Response("\n".join(out), content_type="application/x-mpegURL")

# ================= START =================
if __name__ == "__main__":
    fetch_available_logos()
    print(f"Server is running on port {PORT}")
    print("Vavoo Format: Sabit (/play/{id}/index.m3u8)")
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
