from gevent import monkey; monkey.patch_all()
import requests, urllib3, logging, re, time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin

# ---------------- AYARLAR ----------------
PORT = 8080
CHUNK_SIZE = 32768
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# AKILLI LİNK HAVUZU (Database gibi çalışır)
# Link patlarsa yenisini buraya yazarız.
CDN_CACHE = {} 

# REFERANS ADRESLERİ
REF_ANDRO = 'https://taraftarium.is/'
REF_HTML = 'https://inatspor35.xyz/'
REF_FIXED = 'https://99d55c13ae7d1ebg.cfd/'
REF_VAVOO = 'https://vavoo.to/'

# KAYNAK ADRESLERİ
SOURCE_VAVOO = "https://vavoo.to"
URL_ANDRO = 'https://andro.adece12.sbs/checklist/{}.m3u8'
URL_HTML = 'https://ogr.d72577a9dd0ec6.sbs/{}.m3u8'
URL_FIXED = 'https://k93.t24hls8.sbs/{}.m3u8'
URL_VAVOO = "https://vavoo.to/play/{}/index.m3u8"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Performanslı Session Ayarları
session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Connection": "keep-alive"
})

retry_strategy = Retry(
    total=2,
    backoff_factor=0.1,
    status_forcelist=[500, 502, 503, 504],
)

adapter = HTTPAdapter(
    pool_connections=200,
    pool_maxsize=200,
    max_retries=retry_strategy,
    pool_block=False
)
session.mount("https://", adapter)
session.mount("http://", adapter)

# ---------------- LİSTELER ----------------
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

@app.route('/')
def root():
    host = request.host_url.rstrip('/')
    out = ["#EXTM3U"]

    def add_channel(name, real_url, referer, group):
        p_url = f"{host}/api/m3u8?u={real_url}&r={referer}"
        out.append(f'#EXTINF:-1 group-title="{group}",{name}')
        out.append(p_url)

    # ANDRO
    for c in ANDRO_LIST:
        add_channel(c["name"], URL_ANDRO.format(c['id']), REF_ANDRO, "Andro")

    # HTML
    for c in HTML_LIST:
        clean_name = re.sub(r'\s*\(.*?\)', '', c["name"]).strip()
        add_channel(clean_name, URL_HTML.format(c['id']), REF_HTML, "HTML")

    # FIXED
    for c in FIXED_LIST:
        clean_name = re.sub(r'\s*\(.*?\)', '', c["name"]).strip()
        add_channel(clean_name, URL_FIXED.format(c['id']), REF_FIXED, "Fixed")

    # VAVOO - Dinamik Tarama
    try:
        r = session.get(f"{SOURCE_VAVOO}/live2/index", verify=False, timeout=5)
        v_data = r.json()
        for i in v_data:
            if i.get("group") == "Turkey":
                try:
                    raw_url = i['url']
                    if '/play/' in raw_url:
                        cid = raw_url.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                        name = i["name"].replace(",", " ").strip()
                        name = re.sub(r'\s*\(\d+\)', '', name).strip()
                        v_real_url = URL_VAVOO.format(cid)
                        add_channel(name, v_real_url, REF_VAVOO, "Vavoo")
                except: pass
    except: pass

    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/api/m3u8')
def api_m3u8():
    # Bu fonksiyon "Merkez Üs" görevi görür.
    # Oynatıcı her 5-10 saniyede bir buraya gelir.
    
    original_url = request.args.get('u')
    referer = request.args.get('r')
    
    if not original_url: return Response("No URL", 400)

    try:
        headers = {"User-Agent": USER_AGENT}
        if referer: headers["Referer"] = referer

        # -------------------------------------------------------------
        # AKILLI LINK YENİLEME SİSTEMİ (SELF-HEALING)
        # -------------------------------------------------------------
        target_url = original_url
        
        # 1. Eğer hafızada çalışan bir CDN linki varsa onu dene
        if original_url in CDN_CACHE:
            target_url = CDN_CACHE[original_url]
        
        # 2. Linki çekmeyi dene
        r = session.get(target_url, headers=headers, verify=False, timeout=8)

        # 3. Eğer hafızadaki link hata verdiyse (403 Forbidden / 404 Not Found)
        # Demek ki linkin süresi dolmuş. HEMEN ORJİNALİNDEN YENİSİNİ AL.
        if r.status_code >= 400 and target_url != original_url:
            # "Link ölmüş, yenisini alıyorum..."
            r = session.get(original_url, headers=headers, verify=False, timeout=8)
            
            # Yeni linki hafızaya at (Bir sonraki istekte bunu kullanalım)
            if r.status_code == 200:
                 CDN_CACHE[original_url] = r.url

        # Vavoo JSON koruması
        try:
            if "application/json" in r.headers.get("Content-Type", ""):
                json_data = r.json()
                if "url" in json_data:
                    target_url = json_data["url"]
                    r = session.get(target_url, headers=headers, verify=False, timeout=8)
                    if r.status_code == 200:
                        CDN_CACHE[original_url] = r.url
        except: pass

        if r.status_code != 200:
            return Response(f"Source Error: {r.status_code}", status=r.status_code)
        
        # CDN Linki güncellendiyse (ve ilk deneme değilse) cache'e yaz
        if r.url != original_url and r.url != target_url:
             CDN_CACHE[original_url] = r.url

        # -------------------------------------------------------------

        base_url = r.url.rsplit('/', 1)[0]
        final_text = r.text

        # Master Playlist Çözümleme
        if "EXT-X-STREAM-INF" in r.text:
            lines = r.text.splitlines()
            best_url = None
            max_bw = 0
            
            for i, line in enumerate(lines):
                if "#EXT-X-STREAM-INF" in line:
                    bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                    bw = int(bw_match.group(1)) if bw_match else 0
                    if bw > max_bw:
                        max_bw = bw
                        if i + 1 < len(lines):
                            potential_url = lines[i+1].strip()
                            if potential_url and not potential_url.startswith('#'):
                                best_url = urljoin(r.url, potential_url)

            if best_url:
                target_url = best_url
                r = session.get(target_url, headers=headers, verify=False, timeout=8)
                base_url = r.url.rsplit('/', 1)[0]
                final_text = r.text

        # Proxy Link Oluşturma
        host = request.host_url.rstrip('/')
        new_lines = []
        
        for line in final_text.splitlines():
            line = line.strip()
            if not line: continue
            
            if line.startswith('#'):
                new_lines.append(line)
            else:
                full_ts_url = urljoin(base_url + '/', line)
                proxy_ts_link = f"{host}/api/ts?u={full_ts_url}"
                if referer:
                    proxy_ts_link += f"&r={referer}"
                new_lines.append(proxy_ts_link)

        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

    except Exception as e:
        return Response(str(e), 500)

@app.route('/api/ts')
def api_ts():
    target_url = request.args.get('u')
    referer = request.args.get('r')

    if not target_url: return Response("No URL", 400)

    try:
        req_headers = {key: value for (key, value) in request.headers if key != 'Host'}
        req_headers['User-Agent'] = USER_AGENT
        if referer: 
            req_headers['Referer'] = referer
        else:
            req_headers['Referer'] = "https://vavoo.to/"

        with session.get(target_url, headers=req_headers, stream=True, verify=False, timeout=(3.05, 30)) as r:
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            headers = [(name, value) for (name, value) in r.headers.items()
                       if name.lower() not in excluded_headers]

            def generate():
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE): 
                    if chunk:
                        yield chunk

            return Response(stream_with_context(generate()), headers=headers, status=r.status_code)

    except Exception as e:
        return Response("Stream Error", 500)

if __name__ == "__main__":
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
