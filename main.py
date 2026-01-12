# ==============================================================================
# VAVOO SINGULARITY: HIGH-PERFORMANCE MINIMAL
# ==============================================================================
from gevent import monkey; monkey.patch_all()
import requests, re, urllib3
from gevent.pywsgi import WSGIServer
from gevent.pool import Pool
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote, urljoin

urllib3.disable_warnings()
app = Flask(__name__)

# --- CONFIG & PRE-COMPILE ---
URLS = ["https://vavoo.to", "https://huhu.to", "https://oha.to", "https://kool.to"]
UA = {"User-Agent": "Vavoo/2.6"}
SESS = requests.Session(); SESS.headers.update(UA)
RE_CID = re.compile(r'/play/([\w\.]+)')
RE_KEY = re.compile(r'URI="([^"]+)"')

# --- CORE LOGIC (PARALLEL FETCH) ---
def check_src(args):
    url, cid = args
    try:
        r = SESS.get(f"{url}/play/{cid}/index.m3u8", verify=False, timeout=3)
        return (url, r.content) if r.ok and b"#EXTM3U" in r.content else None
    except: return None

def get_best_stream(cid):
    # Tum sunuculari ayni anda tarar, ilk calisani alir
    pool = Pool(len(URLS))
    for res in pool.imap_unordered(check_src, [(u, cid) for u in URLS]):
        if res: pool.kill(); return res
    return None, None

# --- ROUTES ---
@app.route('/')
def index():
    m3u = ["#EXTM3U"]
    # Liste cekimi icin de paralel tarama
    pool = Pool(len(URLS))
    data = None
    for res in pool.imap_unordered(lambda u: SESS.get(f"{u}/live2/index", verify=False, timeout=5), URLS):
        if res and res.ok:
            try: data = res.json(); pool.kill(); break
            except: continue
            
    if not data: return Response("Service Unavailable", 503)

    host = request.host_url.rstrip('/')
    # List comprehension ile hizli isleme
    turkey_chns = [x for x in data if x.get("group") == "Turkey"]
    
    for item in turkey_chns:
        match = RE_CID.search(item.get("url", ""))
        if match:
            cid = match.group(1).replace(".m3u8", "")
            m3u.append(f'#EXTINF:-1 tvg-id="{item.get("id")}" tvg-logo="{item.get("logo")}" group-title="Turkey",{item.get("name")}')
            m3u.append(f"{host}/live/{cid}.m3u8")
            
    return Response("\n".join(m3u), content_type="application/vnd.apple.mpegurl")

@app.route('/live/<cid>.m3u8')
def playlist(cid):
    base, content = get_best_stream(cid)
    if not base: return Response("Offline", 404)
    
    host = request.host_url.rstrip('/')
    lines = content.decode('utf-8').splitlines()
    new_lines = []
    
    for line in lines:
        if "EXT-X-KEY" in line:
            line = RE_KEY.sub(lambda m: f'URI="{host}/p?u={quote(urljoin(base+"/", m.group(1)))}"', line)
        elif line and not line.startswith("#"):
            line = f"{host}/p?u={quote(urljoin(base+'/', line))}"
        new_lines.append(line)
        
    return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

@app.route('/p')
def proxy():
    url = unquote(request.args.get('u', ''))
    if not url: return Response(status=400)
    
    def generate():
        try:
            with SESS.get(url, stream=True, verify=False, timeout=10) as r:
                yield from r.iter_content(chunk_size=65536)
        except: pass

    return Response(stream_with_context(generate()), content_type="video/mp2t" if ".ts" in url else "application/octet-stream")

if __name__ == "__main__":
    print("🚀 Vavoo High-Perf: :8080 calisiyor...")
    try: WSGIServer(('0.0.0.0', 8080), app, log=None).serve_forever()
    except: pass
