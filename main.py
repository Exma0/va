from gevent import monkey
monkey.patch_all()

import requests
import urllib3
from gevent import pool
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

try: import ujson as json
except ImportError: import json

SOURCES = ["https://vavoo.to"]
USER_AGENT = "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
PORT = 8080

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=1, pool_block=False)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({"User-Agent": USER_AGENT, "Connection": "keep-alive"})

def get_best_live_data():
    for src in SOURCES:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=5)
            if r.status_code == 200: return r.json(), src
        except: continue
    return None, None

def fetch_playlist_content(cid):
    cid_clean = cid.replace('.m3u8', '')
    for src in SOURCES:
        try:
            url = f"{src}/play/{cid_clean}/index.m3u8"
            r = session.get(url, verify=False, timeout=5)
            if r.status_code == 200: return r.content, r.url.rsplit('/', 1)[0], src
        except: continue
    return None, None, None

def generate_stream(r):
    try:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk: yield chunk
    finally: r.close()

def proxy_stream(url):
    try:
        r = session.get(url, stream=True, verify=False, timeout=(4, 10))
        if r.status_code == 200:
            return Response(stream_with_context(generate_stream(r)), content_type="video/mp2t")
        r.close()
    except: pass
    return Response("Error", 502)

@app.route('/')
def root():
    data, _ = get_best_live_data()
    if not data: return Response("Servers Down", 503)
    host_b = request.host_url.rstrip('/').encode()
    out_lines = [b"#EXTM3U"]
    for item in data:
        if item.get("group") == "Turkey":
            try:
                name = item['name'].replace(',', ' ')
                cid = item['url'].split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                out_lines.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode('utf-8'))
                out_lines.append(host_b + b'/live/' + cid.encode('utf-8') + b'.m3u8')
            except: pass
    return Response(b"\n".join(out_lines), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    content, base_url, _ = fetch_playlist_content(cid)
    if not content: return Response("Stream Bulunamadi", 404)
    host_b = request.host_url.rstrip('/').encode()
    base_b = base_url.encode()
    out = []
    for line in content.split(b'\n'):
        line = line.strip()
        if not line: continue
        if line.startswith(b'#'): out.append(line)
        else:
            target = line if line.startswith(b'http') else base_b + b'/' + line
            out.append(host_b + b'/ts?url=' + quote(target, safe='/:?=&').encode())
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    if not url_enc: return "Bad Request", 400
    original_target = unquote(url_enc)
    return proxy_stream(original_target)

if __name__ == "__main__":
    server = WSGIServer(('0.0.0.0', PORT), app, spawn=pool.Pool(10), log=None)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
