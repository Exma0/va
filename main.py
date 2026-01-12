from gevent import monkey; monkey.patch_all()
import requests, urllib3, json, logging
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

SOURCE = "https://vavoo.to"
USER_AGENT = "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
PORT = 8080

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

def proxy_req(url):
    try:
        r = session.get(url, stream=True, verify=False, timeout=None)
        if r.status_code == 200:
            return Response(stream_with_context(r.iter_content(chunk_size=8192)), content_type="video/mp2t")
        r.close()
    except: pass
    return Response("Error", 502)

@app.route('/')
def root():
    try:
        r = session.get(f"{SOURCE}/live2/index", verify=False, timeout=5)
        data = r.json()
    except: return Response("Error", 503)
    
    host = request.host_url.rstrip('/').encode()
    out = [b"#EXTM3U"]
    for i in data:
        if i.get("group") == "Turkey":
            try:
                cid = i['url'].split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                out.append(f'#EXTINF:-1 group-title="Turkey",{i["name"].replace(",", " ")}'.encode())
                out.append(host + b'/live/' + cid.encode() + b'.m3u8')
            except: pass
    return Response(b"\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def m3u8(cid):
    try:
        r = session.get(f"{SOURCE}/play/{cid.replace('.m3u8','')}/index.m3u8", verify=False, timeout=5)
        if r.status_code != 200: return Response("Error", 404)
        base = r.url.rsplit('/', 1)[0].encode()
    except: return Response("Error", 404)

    host = request.host_url.rstrip('/').encode()
    out = []
    for line in r.content.split(b'\n'):
        line = line.strip()
        if not line: continue
        if line.startswith(b'#'): out.append(line)
        else:
            tgt = line if line.startswith(b'http') else base + b'/' + line
            out.append(host + b'/ts?url=' + quote(tgt).encode())
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def ts():
    url = request.args.get('url')
    return proxy_req(unquote(url)) if url else ("Bad Request", 400)

if __name__ == "__main__":
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
