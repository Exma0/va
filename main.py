from gevent import monkey
monkey.patch_all()

import requests
import urllib3
import gc
from gevent import pool
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context
from urllib.parse import quote, unquote

try:
    import ujson as json
except ImportError:
    import json

SOURCES = [
    "https://vavoo.to"
]

USER_AGENT = "VAVOO/3.1.20"
PORT = 8080

gc.set_threshold(700, 10, 10)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app.logger.disabled = True

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=200,
    pool_maxsize=500,
    max_retries=1,
    pool_block=False
)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({
    "User-Agent": USER_AGENT,
    "Connection": "keep-alive"
})

def get_best_live_data():
    for src in SOURCES:
        try:
            r = session.get(f"{src}/live2/index", verify=False, timeout=4)
            if r.status_code == 200:
                return r.json(), src
        except:
            continue
    return None, None

def fetch_playlist_content(cid):
    cid_clean = cid.replace('.m3u8', '')
    for src in SOURCES:
        try:
            url = f"{src}/play/{cid_clean}/index.m3u8"
            r = session.get(url, verify=False, timeout=4)
            if r.status_code == 200:
                return r.content, r.url.rsplit('/', 1)[0], src
        except:
            continue
    return None, None, None

def proxy_stream(url, timeout_settings):
    try:
        r = session.get(url, stream=True, verify=False, timeout=timeout_settings)
        return Response(stream_with_context(r.iter_content(chunk_size=None)), 
                        content_type="video/mp2t")
    except:
        return Response("Error", 502)

@app.route('/')
def root():
    data, working_src = get_best_live_data()
    
    if not data:
        return Response("Servers Down", 503)

    host_b = request.host_url.rstrip('/').encode()
    out_lines = [b"#EXTM3U"]
    
    for item in data:
        if item.get("group") == "Turkey":
            try:
                name = item['name'].replace(',', ' ')
                u = item['url']
                cid = u.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                
                out_lines.append(f'#EXTINF:-1 group-title="Turkey",{name}'.encode('utf-8'))
                out_lines.append(host_b + b'/live/' + cid.encode('utf-8') + b'.m3u8')
            except: 
                pass

    return Response(b"\n".join(out_lines), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def playlist_handler(cid):
    content, base_url, used_src = fetch_playlist_content(cid)
    
    if not content:
        return Response("Stream Bulunamadi", 404)

    host_b = request.host_url.rstrip('/').encode()
    base_b = base_url.encode()
    out = []
    
    for line in content.split(b'\n'):
        line = line.strip()
        if not line: continue
        
        if line.startswith(b'#'):
            out.append(line)
        else:
            if line.startswith(b'http'): target = line
            else: target = base_b + b'/' + line
            
            safe_target = quote(target, safe='/:?=&').encode()
            out.append(host_b + b'/ts?url=' + safe_target)
            
    return Response(b"\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def segment_handler():
    url_enc = request.args.get('url')
    if not url_enc: return "Bad Request", 400
    
    original_target = unquote(url_enc)
    TIMEOUT_SETTINGS = (None, None)

    path_part = None
    target_domain = None
    
    for src in SOURCES:
        if src in original_target:
            target_domain = src
            try: path_part = original_target.split(src, 1)[1]
            except: pass
            break
            
    if not target_domain:
        return proxy_stream(original_target, TIMEOUT_SETTINGS)

    try:
        r = session.get(original_target, stream=True, verify=False, timeout=TIMEOUT_SETTINGS)
        if r.status_code == 200:
            return Response(stream_with_context(r.iter_content(chunk_size=None)), 
                          content_type="video/mp2t")
        r.close()
    except:
        pass 
        
    if path_part:
        for src in SOURCES:
            if src == target_domain: continue
            
            new_target = src + path_part
            try:
                r = session.get(new_target, stream=True, verify=False, timeout=TIMEOUT_SETTINGS)
                if r.status_code == 200:
                    return Response(stream_with_context(r.iter_content(chunk_size=None)), 
                                  content_type="video/mp2t")
                r.close()
            except:
                continue

    return Response("Source Error", 502)

if __name__ == "__main__":
    worker_pool = pool.Pool(1000)
    server = WSGIServer(('0.0.0.0', PORT), app, spawn=worker_pool, log=None)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
