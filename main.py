from gevent import monkey; monkey.patch_all()
import requests, re, urllib3, sys
from gevent.pywsgi import WSGIServer
from gevent.pool import Pool
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote, urljoin, urlparse

urllib3.disable_warnings()

app = Flask(__name__)

SOURCES = [
    "https://vavoo.to",
    "https://huhu.to",
    "https://oha.to",
    "https://kool.to"
]

HEADERS = {
    "User-Agent": "Vavoo/2.6",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive"
}

session = requests.Session()
session.headers.update(HEADERS)
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
session.mount('http://', adapter)
session.mount('https://', adapter)

REGEX_CID = re.compile(r'/play/([\w\.]+)')
REGEX_URI = re.compile(r'URI="([^"]+)"')

def resolve_stream(cid):
    def check_url(src):
        try:
            target_url = f"{src}/play/{cid}/index.m3u8"
            r = session.get(target_url, verify=False, timeout=5, allow_redirects=True)
            if r.status_code == 200 and b"#EXTM3U" in r.content:
                return {"base": r.url, "content": r.content}
        except:
            return None
        return None

    pool = Pool(len(SOURCES))
    for result in pool.imap_unordered(check_url, SOURCES):
        if result:
            pool.kill()
            return result
    return None

@app.route('/')
def index():
    api_data = []
    pool = Pool(len(SOURCES))
    for res in pool.imap_unordered(lambda s: session.get(f"{s}/live2/index", verify=False, timeout=5), SOURCES):
        if res and res.status_code == 200:
            try:
                api_data = res.json()
                pool.kill()
                break
            except:
                continue

    if not api_data:
        return Response("Vavoo API Erisilemiyor", 503)

    host = request.host_url.rstrip('/')
    m3u_output = ["#EXTM3U"]

    for channel in api_data:
        if channel.get("group") == "Turkey":
            url = channel.get("url", "")
            match = REGEX_CID.search(url)
            if match:
                cid = match.group(1).replace(".m3u8", "")
                name = channel.get("name", "Unknown")
                logo = channel.get("logo", "")
                tid = channel.get("id", "")
                
                m3u_output.append(f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{logo}" group-title="Turkey",{name}')
                m3u_output.append(f"{host}/live/{cid}.m3u8")

    return Response("\n".join(m3u_output), content_type="application/vnd.apple.mpegurl")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    stream = resolve_stream(cid)
    if not stream:
        return Response("Stream Bulunamadi", 404)

    base_url = stream["base"].rsplit('/', 1)[0]
    content = stream["content"].decode('utf-8', errors='ignore')
    host = request.host_url.rstrip('/')
    
    new_lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line: continue

        if line.startswith("#"):
            if "EXT-X-KEY" in line:
                line = REGEX_URI.sub(lambda m: f'URI="{host}/proxy?url={quote(urljoin(base_url + "/", m.group(1)))}"', line)
            new_lines.append(line)
        else:
            full_ts_url = urljoin(base_url + "/", line)
            proxied_ts = f"{host}/proxy?url={quote(full_ts_url)}"
            new_lines.append(proxied_ts)

    return Response("\n".join(new_lines), content_type="application/vnd.apple.mpegurl")

@app.route('/proxy')
def proxy_handler():
    target_url = request.args.get('url')
    if not target_url:
        return Response("Bad Request", 400)
    
    real_url = unquote(target_url)
    c_type = "video/mp2t"
    if ".key" in real_url: c_type = "application/octet-stream"
    
    def generate():
        try:
            with session.get(real_url, stream=True, verify=False, timeout=15) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=32768):
                    yield chunk
        except:
            pass

    return Response(stream_with_context(generate()), content_type=c_type)

if __name__ == "__main__":
    server = WSGIServer(('0.0.0.0', 8080), app, log=None)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
