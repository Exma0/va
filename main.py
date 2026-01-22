from gevent import monkey; monkey.patch_all()

import requests, urllib3, logging, re
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

# Sadece Andro, HTML ve Vavoo Referansları kaldı
REF_ANDRO = 'https://taraftarium.is/'
REF_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/'
REF_VAVOO = 'https://vavoo.to/'

SOURCE_VAVOO = "https://vavoo.to"
URL_ANDRO = 'https://andro.adece12.sbs/checklist/{}.m3u8'
URL_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/{}.m3u8'
URL_VAVOO = "https://vavoo.to/play/{}/index.m3u8"

urllib3.disable_warnings()
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# ================= SESSION =================
# Vavoo listesini çekmek için gerekli session ayarları
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
    out = ["#EXTM3U"]

    def add_channel(group, name, real_url, ref):
        # M3U Standart Başlık
        out.append(f'#EXTINF:-1 group-title="{group}",{name}')
        
        # Oynatıcılar için Header (User-Agent ve Referer)
        # Bu kısım VLC, Tivimate, OTT Navigator vb. oynatıcıların
        # yayını açabilmesi için gereklidir.
        out.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        out.append(f'#EXTVLCOPT:http-referrer={ref}')
        out.append(f'#EXTHTTP:{{"User-Agent":"{USER_AGENT}","Referer":"{ref}"}}')
        
        # Orijinal Yayın Linki
        out.append(real_url)

    # 1. ANDRO Kaynakları
    for c in ANDRO_LIST:
        add_channel("Andro", c["name"], URL_ANDRO.format(c["id"]), REF_ANDRO)

    # 2. HTML Kaynakları
    for c in HTML_LIST:
        name = re.sub(r'\s*\(.*?\)', '', c["name"])
        add_channel("HTML", name, URL_HTML.format(c["id"]), REF_HTML)

    # 3. VAVOO Kaynakları (Otomatik Çekilir)
    try:
        r = session.get(f"{SOURCE_VAVOO}/live2/index", timeout=4, verify=False)
        if r.status_code == 200:
            data = r.json()
            for i in data:
                # Sadece Turkey grubu ve oynatılabilir linkleri al
                if i.get("group") == "Turkey" and "/play/" in i.get("url",""):
                    cid = i["url"].split("/play/")[1].split("/")[0]
                    name = re.sub(r'\s*\(\d+\)', '', i["name"]).replace(",", " ")
                    add_channel("Vavoo", name, URL_VAVOO.format(cid), REF_VAVOO)
    except Exception as e:
        print(f"Vavoo Hatası: {e}")
        pass

    return Response("\n".join(out), content_type="application/x-mpegURL")

# ================= START =================
if __name__ == "__main__":
    print(f"Server is running on port {PORT}")
    print("Mod: Direct (Proxy Disabled)")
    print("Sources: ANDRO, HTML, VAVOO")
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
