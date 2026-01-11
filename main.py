import re
import requests
import os
import time
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin
from functools import lru_cache

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

session = requests.Session()
session.verify = False
adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200, max_retries=2)
session.mount("http://", adapter)
session.mount("https://", adapter)

UA = 'VAVOO/2.6'
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Connection": "keep-alive"}
CACHE_DATA = {"list": None, "time": 0}
CACHE_TTL = 600

CHANNEL_REGEX = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
ID_REGEX = re.compile(r'/play/(\d+)')

@lru_cache(maxsize=512)
def resolve_url(url):
    try:
        r = session.get(url, headers=HEADERS, timeout=3)
        if "#EXT-X-STREAM-INF" in r.text:
            for line in r.text.splitlines():
                if line and not line.startswith("#"):
                    return urljoin(url, line.strip())
        return url
    except:
        return url

@app.route('/', methods=['GET'])
def root_playlist():
    now = time.time()
    if CACHE_DATA["list"] and now - CACHE_DATA["time"] < CACHE_TTL:
        return Response(CACHE_DATA["list"], content_type="application/x-mpegURL")
    try:
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, timeout=10)
        data = r.text
    except:
        return "ERR", 500
    base = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    for m in CHANNEL_REGEX.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        mid = ID_REGEX.search(m.group(2))
        if mid:
            cid = mid.group(1)
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base}/live.m3u8?id={cid}')
    result = "\n".join(out)
    CACHE_DATA["list"] = result
    CACHE_DATA["time"] = now
    return Response(result, content_type="application/x-mpegURL")

@app.route('/live.m3u8')
def live_m3u8():
    cid = request.args.get('id')
    if not cid: return "ID MISSING", 400
    target_url = resolve_url(f"https://vavoo.to/play/{cid}/index.m3u8")
    base_url = target_url.rsplit('/', 1)[0] + '/'
    try:
        r = session.get(target_url, headers=HEADERS, timeout=5)
        lines = r.text.splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("#") or not line.strip():
                new_lines.append(line)
                if "#EXT-X-TARGETDURATION" in line:
                    new_lines.append("#EXT-X-START:TIME-OFFSET=-10")
            else:
                ts_url = urljoin(base_url, line)
                new_lines.append(f"{request.host_url.rstrip('/')}/ts_proxy?url={ts_url}")
        return Response("\n".join(new_lines), content_type="application/x-mpegURL")
    except:
        return "STREAM ERR", 500

@app.route('/ts_proxy')
def ts_proxy():
    ts_url = request.args.get('url')
    def generate():
        try:
            with session.get(ts_url, headers=HEADERS, stream=True, timeout=10) as r:
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
        except:
            pass
    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
