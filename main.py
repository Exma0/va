from gevent import monkey; monkey.patch_all()

import requests, urllib3, logging, re, unicodedata
from flask import Flask, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from gevent.pywsgi import WSGIServer

# ================= CONFIG =================
PORT = 8080

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# --- YENİ EPG VE LOGO AYARLARI ---
# EPG Kaynağı (Genel dosya veya senin verdiğin dizin)
EPG_URL = "https://epgshare01.online/epgshare01/epg_ripper_TR1.xml.gz" 
# Logo Kaynağı (GitHub Raw adresi)
LOGO_BASE_URL = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/turkey/"

# --- REFERANSLAR ---
REF_ANDRO = 'https://taraftarium.is/'
REF_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/'
REF_VAVOO = 'https://vavoo.to/'

SOURCE_VAVOO_API = "https://vavoo.to/live2/index"

URL_ANDRO = 'https://andro.adece12.sbs/checklist/{}.m3u8'
URL_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/{}.m3u8'
# Vavoo için sabit URL şablonu KALDIRILDI, artık dinamik alınıyor.

urllib3.disable_warnings()
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

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

# ================= HELPER FUNCTIONS (YARDIMCI) =================

def slugify(text):
    """
    Kanal ismini GitHub dosya ismine uygun hale getirir.
    Örn: "BeIN Sports 1" -> "bein-sports-1"
    """
    text = text.lower()
    # Türkçe karakter değişimi
    replacements = {
        'ı': 'i', 'ğ': 'g', 'ü': 'u', 'ş': 's', 'ö': 'o', 'ç': 'c',
        'İ': 'i', 'Ğ': 'g', 'Ü': 'u', 'Ş': 's', 'Ö': 'o', 'Ç': 'c'
    }
    for src, dest in replacements.items():
        text = text.replace(src, dest)
    
    # ASCII olmayanları temizle (unicode normalize)
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    # Harf ve sayı dışındakileri tire yap
    text = re.sub(r'[^a-z0-9]+', '-', text)
    # Baştaki ve sondaki tireleri sil
    return text.strip('-')

def get_logo_url(channel_name):
    """GitHub üzerinden logo URL'si oluşturur."""
    slug = slugify(channel_name)
    return f"{LOGO_BASE_URL}{slug}.png"

# ================= CHANNEL LISTS =================

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
    {'name':'TJK TV','id':'androstreamlivetjk'},
    {'name':'HT Spor','id':'androstreamliveht'},
    {'name':'NBA TV','id':'androstreamlivenba'},
    {'name':'TV8','id':'androstreamlivetv8'},
    {'name':'TV8.5','id':'androstreamlivetv85'},
    {'name':'Tabii Spor','id':'androstreamlivetb'},
    {'name':'Tabii Spor 1','id':'androstreamlivetb1'},
    {'name':'Tabii Spor 2','id':'androstreamlivetb2'},
    {'name':'Tabii Spor 3','id':'androstreamlivetb3'},
    {'name':'Tabii Spor 4','id':'androstreamlivetb4'},
    {'name':'Tabii Spor 5','id':'androstreamlivetb5'},
    {'name':'Tabii Spor 6','id':'androstreamlivetb6'},
    {'name':'Tabii Spor 7','id':'androstreamlivetb7'},
    {'name':'Tabii Spor 8','id':'androstreamlivetb8'},
    {'name':'FB TV','id':'androstreamlivefb'},
    {'name':'CBC Sport','id':'androstreamlivecbcs'},
    {'name':'GS TV','id':'androstreamlivegs'},
    {'name':'Sports TV','id':'androstreamlivesptstv'},
    {'name':'Exxen TV','id':'androstreamliveexn'},
    {'name':'Exxen Sports 1','id':'androstreamliveexn1'},
    {'name':'Exxen Sports 2','id':'androstreamliveexn2'},
    {'name':'Exxen Sports 3','id':'androstreamliveexn3'},
    {'name':'Exxen Sports 4','id':'androstreamliveexn4'},
    {'name':'Exxen Sports 5','id':'androstreamliveexn5'},
    {'name':'Exxen Sports 6','id':'androstreamliveexn6'},
    {'name':'Exxen Sports 7','id':'androstreamliveexn7'},
    {'name':'Exxen Sports 8','id':'androstreamliveexn8'},
]

HTML_LIST = [
    {'name':'BeIN Sports 1 (Alt)','id':'yayininat'},
    {'name':'BeIN Sports 2 (Alt)','id':'yayinb2'},
    {'name':'BeIN Sports 3 (Alt)','id':'yayinb3'},
    {'name':'BeIN Sports 4 (Alt)','id':'yayinb4'},
    {'name':'BeIN Sports 5 (Alt)','id':'yayinb5'},
    {'name':'BeIN Max 1 (Alt)','id':'yayinbm1'},
    {'name':'BeIN Max 2 (Alt)','id':'yayinbm2'},
    {'name':'S Sport (Alt)','id':'yayinss'},
    {'name':'S Sport 2 (Alt)','id':'yayinss2'},
    {'name':'Tivibu 1 (Alt)','id':'yayint1'},
    {'name':'Tivibu 2 (Alt)','id':'yayint2'},
    {'name':'Tivibu 3 (Alt)','id':'yayint3'},
    {'name':'Tivibu 4 (Alt)','id':'yayint4'},
    {'name':'Smartspor (Alt)','id':'yayinsmarts'},
    {'name':'Smartspor 2 (Alt)','id':'yayinsms2'},
    {'name':'TRT Spor (Alt)','id':'yayintrtspor'},
    {'name':'TRT Spor 2 (Alt)','id':'yayintrtspor2'},
    {'name':'TRT 1 (Alt)','id':'yayintrt1'},
    {'name':'A Spor (Alt)','id':'yayinas'},
    {'name':'ATV (Alt)','id':'yayinatv'},
    {'name':'TV 8 (Alt)','id':'yayintv8'},
    {'name':'TV 8,5 (Alt)','id':'yayintv85'},
    {'name':'NBA TV (Alt)','id':'yayinnbatv'},
    {'name':'Euro Sport 1 (Alt)','id':'yayineu1'},
    {'name':'Euro Sport 2 (Alt)','id':'yayineu2'},
]

# ================= ROOT (M3U) =================
@app.route('/')
def root():
    # M3U Header ve EPG Linki
    out = [f'#EXTM3U x-tvg-url="{EPG_URL}"']

    def add_channel(group, name, real_url, ref):
        # Kanal logosu oluştur
        clean_name = re.sub(r'\s*\(.*?\)', '', name).strip() # Parantez içini temizle (Logo bulmak için)
        logo_url = get_logo_url(clean_name)
        
        # M3U Satırı (EPG ID ve Logo ile)
        # tvg-name: EPG eşleşmesi için kanalın temiz adı
        # tvg-logo: GitHub'dan oluşturulan logo linki
        out.append(f'#EXTINF:-1 group-title="{group}" tvg-name="{clean_name}" tvg-logo="{logo_url}",{name}')
        
        # Headerlar
        out.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        out.append(f'#EXTVLCOPT:http-referrer={ref}')
        out.append(f'#EXTHTTP:{{"User-Agent":"{USER_AGENT}","Referer":"{ref}"}}')
        
        # URL
        out.append(real_url)

    # 1. ANDRO Kaynakları
    for c in ANDRO_LIST:
        add_channel("Andro", c["name"], URL_ANDRO.format(c["id"]), REF_ANDRO)

    # 2. HTML Kaynakları
    for c in HTML_LIST:
        name_clean = re.sub(r'\s*\(.*?\)', '', c["name"])
        add_channel("HTML", name_clean, URL_HTML.format(c["id"]), REF_HTML)

    # 3. VAVOO Kaynakları (Otomatik & Dinamik Yapı)
    try:
        r = session.get(SOURCE_VAVOO_API, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json()
            
            # Veri listesi mi kontrol et (Bazı durumlarda yapı değişebilir)
            if isinstance(data, list):
                for i in data:
                    group = i.get("group")
                    url = i.get("url")
                    name = i.get("name")
                    
                    # Sadece Turkey grubu ve URL'si geçerli olanları al
                    if group == "Turkey" and url and url.startswith("http"):
                        # İsim temizliği (Sayıları ve gereksiz boşlukları sil)
                        clean_name = re.sub(r'\s*\(\d+\)', '', name).replace(",", " ").strip()
                        
                        # --- DİNAMİK URL MANTIĞI ---
                        # Eskiden URL'yi kendimiz oluşturuyorduk (format string ile).
                        # Şimdi API ne veriyorsa onu kullanıyoruz.
                        # Eğer URL parametre gerektiriyorsa (?n=1 vb) olduğu gibi alır.
                        
                        add_channel("Vavoo", clean_name, url, REF_VAVOO)
            else:
                print("Vavoo JSON formatı beklenmedik bir yapıda (Liste değil).")
                
    except Exception as e:
        print(f"Vavoo Hatası: {e}")
        pass

    return Response("\n".join(out), content_type="application/x-mpegURL")

# ================= START =================
if __name__ == "__main__":
    print(f"Server is running on port {PORT}")
    print(f"EPG Source: {EPG_URL}")
    print(f"Logo Source: {LOGO_BASE_URL}...")
    print("Mod: Direct (Proxy Disabled)")
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
