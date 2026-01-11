import re
import requests
import os
import time
from flask import Flask, Response, request
from urllib.parse import urljoin
from functools import lru_cache

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
HEADERS = {"User-Agent": UA, "Referer": "https://vavoo.to/", "Origin": "https://vavoo.to"}

CACHE_DATA = {"list": None, "time": 0}
CACHE_TTL = 300 

@lru_cache(maxsize=128)
def get_real_m3u8(cid):
    base_url = f"https://vavoo.to/play/{cid}/index.m3u8"
    try:
        r = requests.get(base_url, headers=HEADERS, timeout=5, verify=False)
        if "#EXT-X-STREAM-INF" in r.text:
            for line in r.text.splitlines():
                if line and not line.startswith("#"):
                    return urljoin(base_url, line.strip())
        return base_url
    except:
        return base_url

@app.route('/', methods=['GET'])
def root_playlist():
    now = time.time()
    if CACHE_DATA["list"] and (now - CACHE_DATA["time"] < CACHE_TTL):
        return Response(CACHE_DATA["list"], content_type="application/x-mpegURL")

    try:
        r = requests.get("https://vavoo.to/live2/index", headers={"User-Agent": UA}, timeout=10, verify=False)
        data = r.text
    except:
        return Response("ERROR", status=500)

    base = request.host_url.rstrip('/')
    out = "#EXTM3U\n"
    pattern = r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"'
    
    for m in re.finditer(pattern, data, re.DOTALL):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        mid = re.search(r'/play/(\d+)', m.group(2))
        if mid:
            cid = mid.group(1)
            out += f'#EXTINF:-1 group-title="Turkey",{name}\n{base}/live.m3u8?id={cid}\n'

    CACHE_DATA["list"] = out
    CACHE_DATA["time"] = now
    return Response(out, content_type="application/x-mpegURL")

@app.route('/live.m3u8', methods=['GET'])
def live_m3u8():
    cid = request.args.get('id')
    if not cid: return "NO ID", 400

    real_url = get_real_m3u8(cid)
    try:
        r = requests.get(real_url, headers=HEADERS, timeout=5, verify=False)
        lines = r.text.splitlines()
        new_content = []
        for line in lines:
            if line.startswith("#EXT-X-TARGETDURATION"):
                new_content.extend([line, "#EXT-X-START:TIME-OFFSET=-12,PRECISE=YES"])
            elif line and not line.startswith("#"):
                new_content.append(urljoin(real_url, line))
            else:
                new_content.append(line)

        return Response(
            "\n".join(new_content),
            content_type="application/x-mpegURL",
            headers={"Cache-Control": "public, max-age=2", "Access-Control-Allow-Origin": "*"}
        )
    except:
        return "ERROR", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
