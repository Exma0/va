from gevent import monkey; monkey.patch_all()
import requests, urllib3, logging, time, re
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context

# ==============================================================================
# AYARLAR
# ==============================================================================
PORT = 8080
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"

# PHP Kodundaki Referanslar
REF_ANDRO = 'https://taraftarium.is/'
REF_HTML  = 'https://inatspor35.xyz/'
REF_FIXED = 'https://99d55c13ae7d1ebg.cfd/'
SOURCE_VAVOO = "https://vavoo.to"

# URL Şablonları
URL_ANDRO = 'https://andro.adece12.sbs/checklist/{}.m3u8'
URL_HTML  = 'https://ogr.d72577a9dd0ec6.sbs/{}.m3u8'
URL_FIXED = 'https://k93.t24hls8.sbs/{}.m3u8'

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

# ==============================================================================
# 1. TAM LİSTE: ANDRO KANALLARI (PHP'den Birebir)
# ==============================================================================
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

# ==============================================================================
# 2. TAM LİSTE: HTML PERFECT PLAYER (PHP'den Birebir)
# ==============================================================================
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

# ==============================================================================
# 3. TAM LİSTE: SABİT PERFECT PLAYER (PHP'den Birebir)
# ==============================================================================
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

# ==============================================================================
# VAVOO OPTİMİZE EDİLMİŞ CACHE YAPISI
# ==============================================================================
m3u8_cache = {}

def parse_m3u8_to_map(base_url, content):
    segment_map = {}
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'): continue
        full_url = line if line.startswith('http') else f"{base_url}/{line}"
        filename = line.split('/')[-1].split('?')[0]
        segment_map[filename] = full_url
    return segment_map

def get_fresh_vavoo(cid, force_refresh=False):
    now = time.time()
    if not force_refresh and cid in m3u8_cache and (now - m3u8_cache[cid]['time'] < 4.0):
        return m3u8_cache[cid]['map'], m3u8_cache[cid]['raw_m3u8']
    try:
        r = session.get(f"{SOURCE_VAVOO}/play/{cid}/index.m3u8", verify=False, timeout=5)
        if r.status_code == 200:
            base_url = r.url.rsplit('/', 1)[0]
            content = r.text
            seg_map = parse_m3u8_to_map(base_url, content)
            m3u8_cache[cid] = {'time': now, 'map': seg_map, 'raw_m3u8': content}
            return seg_map, content
    except Exception as e:
        print(f"Vavoo Error ({cid}): {e}")
    return None, None

# ==============================================================================
# PROXY FONKSİYONLARI
# ==============================================================================
def universal_proxy_req(url, referer=None):
    """Hem Vavoo hem diğer kanallar için ortak akış fonksiyonu"""
    headers = {"User-Agent": USER_AGENT}
    if referer: headers["Referer"] = referer
    
    try:
        r = session.get(url, headers=headers, stream=True, verify=False, timeout=10)
        if r.status_code == 200:
            return Response(stream_with_context(r.iter_content(chunk_size=8192)), content_type="video/mp2t")
        return Response(f"Source returned {r.status_code}", status=r.status_code)
    except Exception as e:
        return Response(str(e), 502)

@app.route('/')
def root():
    host = request.host_url.rstrip('/')
    out = ["#EXTM3U"]

    # 1️⃣ ANDRO KANALLARI EKLE
    for c in ANDRO_LIST:
        real_url = URL_ANDRO.format(c['id'])
        proxy_url = f"{host}/static_p?u={real_url}&r={REF_ANDRO}"
        out.append(f'#EXTINF:-1 group-title="Andro",{c["name"]}')
        out.append(proxy_url)

    # 2️⃣ HTML KANALLARI EKLE
    for c in HTML_LIST:
        real_url = URL_HTML.format(c['id'])
        proxy_url = f"{host}/static_p?u={real_url}&r={REF_HTML}"
        out.append(f'#EXTINF:-1 group-title="HTML",{c["name"]}')
        out.append(proxy_url)

    # 3️⃣ FIXED KANALLARI EKLE
    for c in FIXED_LIST:
        real_url = URL_FIXED.format(c['id'])
        proxy_url = f"{host}/static_p?u={real_url}&r={REF_FIXED}"
        out.append(f'#EXTINF:-1 group-title="Fixed",{c["name"]}')
        out.append(proxy_url)

    # 4️⃣ VAVOO KANALLARI EKLE
    try:
        r = session.get(f"{SOURCE_VAVOO}/live2/index", verify=False, timeout=8)
        v_data = r.json()
        for i in v_data:
            if i.get("group") == "Turkey":
                try:
                    raw_url = i['url']
                    if '/play/' in raw_url:
                        cid = raw_url.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                        name = i["name"].replace(",", " ")
                        out.append(f'#EXTINF:-1 group-title="Vavoo",{name}')
                        out.append(f"{host}/live/{cid}.m3u8")
                except: pass
    except: pass
            
    return Response("\n".join(out), content_type="application/x-mpegURL")

# ==============================================================================
# ENDPOINT: STATİK KANAL PROXY (Andro, HTML, Fixed için)
# ==============================================================================
@app.route('/static_p')
def static_proxy_m3u8():
    target_url = request.args.get('u')
    referer = request.args.get('r')
    
    if not target_url: return Response("Missing URL", 400)
    
    try:
        headers = {"User-Agent": USER_AGENT}
        if referer: headers["Referer"] = referer
        r = session.get(target_url, headers=headers, verify=False, timeout=10)
        
        if r.status_code != 200: return Response("Source Error", r.status_code)
        
        base_url = target_url.rsplit('/', 1)[0]
        host = request.host_url.rstrip('/')
        new_lines = []
        
        for line in r.text.splitlines():
            line = line.strip()
            if not line: continue
            if line.startswith('#'):
                new_lines.append(line)
            else:
                full_ts_url = line if line.startswith('http') else f"{base_url}/{line}"
                proxy_ts_link = f"{host}/static_ts?u={full_ts_url}&r={referer}"
                new_lines.append(proxy_ts_link)
                
        return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")
    except Exception as e:
        return Response(str(e), 500)

@app.route('/static_ts')
def static_proxy_ts():
    target_url = request.args.get('u')
    referer = request.args.get('r')
    if not target_url: return Response("Missing URL", 400)
    return universal_proxy_req(target_url, referer)

# ==============================================================================
# ENDPOINT: VAVOO ENDPOINTS (Optimize Hali)
# ==============================================================================
@app.route('/live/<cid>.m3u8')
def vavoo_m3u8(cid):
    seg_map, content = get_fresh_vavoo(cid, force_refresh=False)
    if not content: return Response("Stream Not Found", 404)

    host = request.host_url.rstrip('/')
    out = []
    for line in content.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith('#'):
            out.append(line)
        else:
            ts_filename = line.split('/')[-1].split('?')[0]
            new_link = f"{host}/ts?cid={cid}&file={ts_filename}"
            out.append(new_link)
    return Response("\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def vavoo_ts():
    cid = request.args.get('cid')
    filename = request.args.get('file')
    if not cid or not filename: return Response("Bad Request", 400)

    seg_map, _ = get_fresh_vavoo(cid, force_refresh=False)
    target_url = seg_map.get(filename) if seg_map else None

    if not target_url:
        seg_map, _ = get_fresh_vavoo(cid, force_refresh=True)
        if seg_map: target_url = seg_map.get(filename)

    if target_url:
        return universal_proxy_req(target_url, referer=None)
    else:
        return Response("Segment expired", 404)

if __name__ == "__main__":
    print(f"Yayın sunucusu {PORT} portunda başlatıldı. TÜM KANALLAR EKLENDİ.")
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
