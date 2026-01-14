from gevent import monkey; monkey.patch_all()

import requests, urllib3, logging, re
from urllib.parse import quote, unquote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from gevent.pywsgi import WSGIServer
from gevent import sleep
from flask import Flask, Response, request, stream_with_context

# ================= CONFIG =================
PORT = 8080
CHUNK_SIZE = 16384 

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

REF_ANDRO = 'https://taraftarium.is/'
REF_HTML  = 'https://inattv1212.xyz/'
REF_FIXED = 'https://99d55c13ae7d1ebg.cfd/'

URL_ANDRO = 'https://andro.adece12.sbs/checklist/{}.m3u8'
URL_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/{}.m3u8'
URL_FIXED = 'https://k93.t24hls8.sbs/{}.m3u8'

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

FIXED_LIST = [
    {"name":"BeIN Sports 1 (Sabit)","id":"yayin1"},
    {"name":"BeIN Sports 2 (Sabit)","id":"yayinb2"},
    {"name":"BeIN Sports 3 (Sabit)","id":"yayinb3"},
    {"name":"BeIN Sports 4 (Sabit)","id":"yayinb4"},
    {"name":"BeIN Sports 5 (Sabit)","id":"yayinb5"},
    {"name":"BeIN Max 1 (Sabit)","id":"yayinbm1"},
    {"name":"BeIN Max 2 (Sabit)","id":"yayinbm2"},
    {"name":"S Sport (Sabit)","id":"yayinss"},
    {"name":"S Sport 2 (Sabit)","id":"yayinss2"},
    {"name":"Tivibu 1 (Sabit)","id":"yayint1"},
    {"name":"Tivibu 2 (Sabit)","id":"yayint2"},
    {"name":"Tivibu 3 (Sabit)","id":"yayint3"},
    {"name":"Tivibu 4 (Sabit)","id":"yayint4"},
    {"name":"Smartspor (Sabit)","id":"yayinsmarts"},
    {"name":"Smartspor 2 (Sabit)","id":"yayinsms2"},
    {"name":"TRT Spor (Sabit)","id":"yayintrtspor"},
    {"name":"TRT Spor 2 (Sabit)","id":"yayintrtspor2"},
    {"name":"TRT 1 (Sabit)","id":"yayintrt1"},
    {"name":"A Spor (Sabit)","id":"yayinas"},
    {"name":"ATV (Sabit)","id":"yayinatv"},
    {"name":"TV 8 (Sabit)","id":"yayintv8"},
    {"name":"TV 8,5 (Sabit)","id":"yayintv85"},
    {"name":"NBA TV (Sabit)","id":"yayinnbatv"},
    {"name":"Euro Sport 1 (Sabit)","id":"yayineu1"},
    {"name":"Euro Sport 2 (Sabit)","id":"yayineu2"},
    {"name":"Tabii Spor (Sabit)","id":"yayinex7"},
    {"name":"EXXEN (Sabit)","id":"yayinex1"},
    {"name":"Tabii Spor 2 (Sabit)","id":"yayinex2"},
    {"name":"Tabii Spor 3 (Sabit)","id":"yayinex3"},
    {"name":"Tabii Spor 4 (Sabit)","id":"yayinex4"},
    {"name":"Tabii Spor 5 (Sabit)","id":"yayinex5"},
    {"name":"Tabii Spor 6 (Sabit)","id":"yayinex6"},
]

# ================= ROOT (M3U) =================
@app.route('/')
def root():
    host = request.host_url.rstrip('/')
    out = ["#EXTM3U"]

    def add_channel(group, name, real_url, ref):
        # URL'leri güvenli hale getir (Encode)
        enc_url = quote(real_url)
        enc_ref = quote(ref)
        
        # Proxy
        out.append(f'#EXTINF:-1 group-title="{group}",{name}')
        out.append(f'{host}/api/m3u8?u={enc_url}&r={enc_ref}')
        # Direkt (VLC vb. için Headerlı)
        out.append(f'#EXTINF:-1 group-title="{group}",{name} (Direkt)')
        out.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        out.append(f'#EXTVLCOPT:http-referrer={ref}')
        out.append(f'#EXTHTTP:{{"User-Agent":"{USER_AGENT}","Referer":"{ref}"}}')
        out.append(real_url)

    for c in ANDRO_LIST:
        add_channel("Andro", c["name"], URL_ANDRO.format(c["id"]), REF_ANDRO)

    for c in HTML_LIST:
        name = re.sub(r'\s*\(.*?\)', '', c["name"])
        add_channel("HTML", name, URL_HTML.format(c["id"]), REF_HTML)

    for c in FIXED_LIST:
        name = re.sub(r'\s*\(.*?\)', '', c["name"])
        add_channel("Fixed", name, URL_FIXED.format(c["id"]), REF_FIXED)

    # Vavoo kısmı buradan tamamen kaldırılmıştır.

    return Response("\n".join(out), content_type="application/x-mpegURL")

# ================= M3U8 PROXY =================
@app.route('/api/m3u8')
def api_m3u8():
    u = request.args.get('u')
    rfr = request.args.get('r')
    
    # URL encoded geldiyse bazen decode gerekebilir ama requests genelde çözer.
    # Biz yine de parametre olarak gelen URL'in düzgün olduğundan emin olalım.
    if not u:
        return Response("No URL", 400)

    h = {"User-Agent": USER_AGENT}
    if rfr: h["Referer"] = rfr

    try:
        r = session.get(u, headers=h, timeout=10, verify=False)
    except Exception as e:
        return Response(f"Fetch Error: {e}", 502)

    # Adaptive Stream (Multi-quality) ise en iyisini seç
    if "EXT-X-STREAM-INF" in r.text:
        best, bw = None, 0
        l = r.text.splitlines()
        for i, line in enumerate(l):
            if "EXT-X-STREAM-INF" in line:
                m = re.search(r'BANDWIDTH=(\d+)', line)
                v = int(m.group(1)) if m else 0
                if v > bw and i+1 < len(l):
                    bw, best = v, l[i+1].strip()
        if best:
            base = r.url.rsplit('/',1)[0]
            u = best if best.startswith('http') else f"{base}/{best}"
            try:
                r = session.get(u, headers=h, timeout=10, verify=False)
            except:
                pass # İlk istek başarısız olursa orijinal içerikle devam et

    base = r.url.rsplit('/',1)[0]
    host = request.host_url.rstrip('/')
    out = []

    for line in r.text.splitlines():
        if not line or line.startswith('#'):
            out.append(line)
        else:
            # TS linklerini tam adresine çevir
            full = line if line.startswith('http') else f"{base}/{line}"
            # TS linkini proxy'den geçirmek için encode et
            ts = f"{host}/api/ts?u={quote(full)}"
            if rfr: ts += f"&r={quote(rfr)}"
            out.append(ts)

    return Response("\n".join(out), content_type="application/vnd.apple.mpegurl")

# ================= TS PROXY =================
@app.route('/api/ts')
def api_ts():
    u = request.args.get('u')
    rfr = request.args.get('r')
    
    if not u:
        return Response("No URL", 400)

    h = {"User-Agent": USER_AGENT}
    if rfr: h["Referer"] = rfr

    try:
        r = session.get(u, headers=h, stream=True, verify=False, timeout=(5, 10))
    except:
        return Response("TS Fetch Error", 502)

    def gen():
        try:
            for c in r.iter_content(chunk_size=CHUNK_SIZE):
                if c:
                    yield c
                    sleep(0) # Gevent context switch
        except:
            pass

    return Response(
        stream_with_context(gen()),
        headers=[("Content-Type","video/mp2t")],
        status=r.status_code
    )

# ================= START =================
if __name__ == "__main__":
    print(f"Server is running on port {PORT}")
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
