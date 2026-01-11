import re
import requests
import os
import time
import random
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin
from functools import lru_cache

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

session = requests.Session()
session.verify = False
adapter = requests.adapters.HTTPAdapter(pool_connections=1000, pool_maxsize=1000, max_retries=5)
session.mount("http://", adapter)
session.mount("https://", adapter)

UA = 'VAVOO/2.6'
COMMON_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://vavoo.to/"
}

CACHE_DATA = {"list": None, "time": 0}
CACHE_TTL = 300

CHANNEL_REGEX = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
ID_REGEX = re.compile(r'/play/(\d+)')

def get_random_ip():
    return ".".join(map(str, (random.randint(0, 255) for _ in range(4))))

@lru_cache(maxsize=2048)
def resolve_url(url):
    try:
        r = session.get(url, headers=COMMON_HEADERS, timeout=4)
        if "#EXT-X-STREAM-INF" in r.text:
            lines = r.text.splitlines()
            streams = [l.strip() for l in lines if l and not l.startswith("#")]
            return urljoin(url, streams[-1]) if streams else url
        return url
    except:
        return url

@app.route('/')
def root_playlist():
    now = time.time()
    if CACHE_DATA["list"] and now - CACHE_DATA["time"] < CACHE_TTL:
        return Response(CACHE_DATA["list"], content_type="application/x-mpegURL")
    
    try:
        headers = COMMON_HEADERS.copy()
        headers["X-Forwarded-For"] = get_random_ip()
        r = session.get("https://vavoo.to/live2/index", headers=headers, timeout=8)
        data = r.text
    except:
        return "ERROR", 500

    base = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    matches = list(CHANNEL_REGEX.finditer(data))
    for m in matches:
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        mid = ID_REGEX.search(m.group(2))
        if mid:
            cid = mid.group(1)
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base}/live.m3u8?id={cid}')
            
    res = "\n".join(out)
    CACHE_DATA["list"] = res
    CACHE_DATA["time"] = now
    return Response(res, content_type="application/x-mpegURL")

@app.route('/live.m3u8')
def live_m3u8():
    cid = request.args.get('id')
    if not cid: return "NO ID", 400
    
    target_url = resolve_url(f"https://vavoo.to/play/{cid}/index.m3u8")
    base_url = target_url.rsplit('/', 1)[0] + '/'
    
    try:
        headers = COMMON_HEADERS.copy()
        headers["X-Forwarded-For"] = get_random_ip()
        r = session.get(target_url, headers=headers, timeout=5)
        
        if r.status_code != 200: return "SRC ERR", 403

        lines = r.text.splitlines()
        new_lines = []
        
        for line in lines:
            if line.startswith("#"):
                new_lines.append(line)
                if "#EXT-X-TARGETDURATION" in line:
                    new_lines.append("#EXT-X-START:TIME-OFFSET=-60")
            elif line.strip():
                ts_url = urljoin(base_url, line.strip())
                proxy_url = f"{request.host_url.rstrip('/')}/ts_proxy?url={ts_url}"
                new_lines.append(proxy_url)
                
        return Response("\n".join(new_lines), content_type="application/x-mpegURL")
    except:
        return "GEN ERR", 500

@app.route('/ts_proxy')
def ts_proxy():
    ts_url = request.args.get('url')
    if not ts_url: return "NO URL", 400
    
    def generate():
        try:
            headers = COMMON_HEADERS.copy()
            headers["X-Forwarded-For"] = get_random_ip()
            
            with session.get(ts_url, headers=headers, stream=True, timeout=15) as r:
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: yield chunk
                else:
                    return
        except:
            return

    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
