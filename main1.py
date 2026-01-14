from gevent import monkey; monkey.patch_all()
import requests, re, logging
from urllib.parse import quote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from gevent.pywsgi import WSGIServer
from gevent import sleep
from flask import Flask, Response, request, stream_with_context

# AYARLAR
PORT, CHUNK_SIZE = 8080, 16384
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CONF = {
    'ANDRO': {'r': 'https://taraftarium.is/', 'u': 'https://andro.adece12.sbs/checklist/{}.m3u8'},
    'HTML':  {'r': 'https://inattv1212.xyz/', 'u': 'https://ogr.d72577a9dd0ec6.sbs/{}.m3u8'}
}

# KANAL LİSTELERİ
ANDRO_L = [('BeIN Sports 1','receptestt'),('BeIN Sports 2','androstreamlivebs2'),('BeIN Sports 3','androstreamlivebs3'),('BeIN Sports 4','androstreamlivebs4'),('BeIN Sports 5','androstreamlivebs5'),('BeIN Sports Max 1','androstreamlivebsm1'),('BeIN Sports Max 2','androstreamlivebsm2'),('S Sport','androstreamlivess1'),('S Sport 2','androstreamlivess2'),('S Sport Plus','androstreamlivessplus1'),('Tivibu Spor','androstreamlivets'),('Tivibu Spor 1','androstreamlivets1'),('Tivibu Spor 2','androstreamlivets2'),('Tivibu Spor 3','androstreamlivets3'),('Tivibu Spor 4','androstreamlivets4'),('Smart Spor 1','androstreamlivesm1'),('Smart Spor 2','androstreamlivesm2'),('Eurosport 1','androstreamlivees1'),('Eurosport 2','androstreamlivees2'),('İDMAN TV','androstreamliveidm'),('TRT 1','androstreamlivetrt1'),('TRT Spor','androstreamlivetrts'),('TRT Spor Yıldız','androstreamlivetrtsy'),('ATV','androstreamliveatv'),('A Spor','androstreamliveas'),('A2','androstreamlivea2'),('TJK TV','androstreamlivetjk'),('HT Spor','androstreamliveht'),('NBA TV','androstreamlivenba'),('TV8','androstreamlivetv8'),('TV8.5','androstreamlivetv85'),('Tabii Spor','androstreamlivetb'),('Tabii Spor 1','androstreamlivetb1'),('Tabii Spor 2','androstreamlivetb2'),('Tabii Spor 3','androstreamlivetb3'),('Tabii Spor 4','androstreamlivetb4'),('Tabii Spor 5','androstreamlivetb5'),('Tabii Spor 6','androstreamlivetb6'),('Tabii Spor 7','androstreamlivetb7'),('Tabii Spor 8','androstreamlivetb8'),('FB TV','androstreamlivefb'),('CBC Sport','androstreamlivecbcs'),('GS TV','androstreamlivegs'),('Sports TV','androstreamlivesptstv'),('Exxen TV','androstreamliveexn'),('Exxen Sports 1','androstreamliveexn1'),('Exxen Sports 2','androstreamliveexn2'),('Exxen Sports 3','androstreamliveexn3'),('Exxen Sports 4','androstreamliveexn4'),('Exxen Sports 5','androstreamliveexn5'),('Exxen Sports 6','androstreamliveexn6'),('Exxen Sports 7','androstreamliveexn7'),('Exxen Sports 8','androstreamliveexn8')]
HTML_L = [('BeIN Sports 1 (Alt)','yayininat'),('BeIN Sports 2 (Alt)','yayinb2'),('BeIN Sports 3 (Alt)','yayinb3'),('BeIN Sports 4 (Alt)','yayinb4'),('BeIN Sports 5 (Alt)','yayinb5'),('BeIN Max 1 (Alt)','yayinbm1'),('BeIN Max 2 (Alt)','yayinbm2'),('S Sport (Alt)','yayinss'),('S Sport 2 (Alt)','yayinss2'),('Tivibu 1 (Alt)','yayint1'),('Tivibu 2 (Alt)','yayint2'),('Tivibu 3 (Alt)','yayint3'),('Tivibu 4 (Alt)','yayint4'),('Smartspor (Alt)','yayinsmarts'),('Smartspor 2 (Alt)','yayinsms2'),('TRT Spor (Alt)','yayintrtspor'),('TRT Spor 2 (Alt)','yayintrtspor2'),('TRT 1 (Alt)','yayintrt1'),('A Spor (Alt)','yayinas'),('ATV (Alt)','yayinatv'),('TV 8 (Alt)','yayintv8'),('TV 8,5 (Alt)','yayintv85'),('NBA TV (Alt)','yayinnbatv'),('Euro Sport 1 (Alt)','yayineu1'),('Euro Sport 2 (Alt)','yayineu2')]

requests.packages.urllib3.disable_warnings()
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

s = requests.Session()
s.headers.update({"User-Agent": UA, "Connection": "keep-alive"})
s.mount("http://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.1, status_forcelist=[500,502,503,504]), pool_connections=200, pool_maxsize=200))
s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.1, status_forcelist=[500,502,503,504]), pool_connections=200, pool_maxsize=200))

@app.route('/')
def root():
    h, out = request.host_url.rstrip('/'), ["#EXTM3U"]
    
    def add(grp, name, url, ref):
        # Sadece Proxy linki ekleniyor, direkt linkler kaldırıldı
        out.append(f'#EXTINF:-1 group-title="{grp}",{name}')
        out.append(f'{h}/api/m3u8?u={quote(url)}&r={quote(ref)}')

    for n, i in ANDRO_L: 
        add("Andro", n, CONF['ANDRO']['u'].format(i), CONF['ANDRO']['r'])
        
    for n, i in HTML_L:  
        add("HTML", re.sub(r'\s*\(.*?\)', '', n), CONF['HTML']['u'].format(i), CONF['HTML']['r'])
        
    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/api/m3u8')
def m3u8():
    u, rfr = request.args.get('u'), request.args.get('r')
    if not u: return Response("No URL", 400)
    h = {"User-Agent": UA, "Referer": rfr} if rfr else {"User-Agent": UA}
    try:
        r = s.get(u, headers=h, timeout=10, verify=False)
        if "EXT-X-STREAM-INF" in r.text:
            ls = r.text.splitlines()
            best = max([(int(re.search(r'BANDWIDTH=(\d+)', l).group(1)), ls[i+1].strip()) for i, l in enumerate(ls) if "BANDWIDTH=" in l], key=lambda x:x[0], default=(0,None))[1]
            if best:
                u = best if best.startswith('http') else f"{r.url.rsplit('/',1)[0]}/{best}"
                r = s.get(u, headers=h, timeout=10, verify=False)
    except Exception as e: return Response(f"Err: {e}", 502)
    
    base, host, out = r.url.rsplit('/',1)[0], request.host_url.rstrip('/'), []
    for l in r.text.splitlines():
        if not l or l.startswith('#'): out.append(l)
        else:
            full = l if l.startswith('http') else f"{base}/{l}"
            # TS istekleri de proxy'ye yönlendiriliyor
            out.append(f"{host}/api/ts?u={quote(full)}{'&r='+quote(rfr) if rfr else ''}")
    return Response("\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/api/ts')
def ts():
    u, rfr = request.args.get('u'), request.args.get('r')
    if not u: return Response("No URL", 400)
    h = {"User-Agent": UA, "Referer": rfr} if rfr else {"User-Agent": UA}
    try: r = s.get(u, headers=h, stream=True, verify=False, timeout=(5, 10))
    except: return Response("Err", 502)
    def g():
        try:
            for c in r.iter_content(CHUNK_SIZE):
                if c: yield c; sleep(0)
        except: pass
    return Response(stream_with_context(g()), headers=[("Content-Type","video/mp2t")], status=r.status_code)

if __name__ == "__main__":
    print(f"Running on port: {PORT}"); WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
