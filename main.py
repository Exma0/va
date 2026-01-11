import re
import requests
import os
import time
from flask import Flask, Response, request, stream_with_context
from urllib.parse import urljoin
from functools import lru_cache

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

# Bağlantı havuzunu ve bekleme sürelerini optimize et
session = requests.Session()
session.verify = False
adapter = requests.adapters.HTTPAdapter(pool_connections=500, pool_maxsize=500, max_retries=3)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Vavoo'nun gerçek cihaz gibi görmesi için daha detaylı header
HEADERS = {
    "User-Agent": "VAVOO/2.6",
    "Accept": "*/*",
    "Range": "bytes=0-",
    "Connection": "keep-alive",
    "Referer": "https://vavoo.to/"
}

CACHE_DATA = {"list": None, "time": 0}
CACHE_TTL = 600

CHANNEL_REGEX = re.compile(r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"', re.DOTALL)
ID_REGEX = re.compile(r'/play/(\d+)')

@lru_cache(maxsize=1024)
def resolve_url(url):
    try:
        r = session.get(url, headers=HEADERS, timeout=5)
        if "#EXT-X-STREAM-INF" in r.text:
            lines = r.text.splitlines()
            # En yüksek kaliteyi (genelde en alt satırdaki link) seç
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
        r = session.get("https://vavoo.to/live2/index", headers=HEADERS, timeout=10)
        data = r.text
    except:
        return "ERROR", 500
    base = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    for m in CHANNEL_REGEX.finditer(data):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        mid = ID_REGEX.search(m.group(2))
        if mid:
            cid = mid.group(1)
            out.append(f'#EXTINF:-1 group-title="Turkey",{name}\n{base}/live.m3u8?id={cid}')
    res = "\n".join(out)
    CACHE_DATA["list"], CACHE_DATA["time"] = res, now
    return Response(res, content_type="application/x-mpegURL")

@app.route('/live.m3u8')
def live_m3u8():
    cid = request.args.get('id')
    target_url = resolve_url(f"https://vavoo.to/play/{cid}/index.m3u8")
    base_url = target_url.rsplit('/', 1)[0] + '/'
    try:
        r = session.get(target_url, headers=HEADERS, timeout=5)
        lines = r.text.splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("#"):
                new_lines.append(line)
                if "#EXT-X-TARGETDURATION" in line:
                    # Buffer'ı artırmak için başlangıç ofsetini büyüttük
                    new_lines.append("#EXT-X-START:TIME-OFFSET=-20")
            elif line.strip():
                ts_url = urljoin(base_url, line.strip())
                new_lines.append(f"{request.host_url.rstrip('/')}/ts_proxy?url={ts_url}")
        return Response("\n".join(new_lines), content_type="application/x-mpegURL")
    except:
        return "ERR", 500

@app.route('/ts_proxy')
def ts_proxy():
    ts_url = request.args.get('url')
    def generate():
        try:
            # Stream timeout'u artırıldı ve chunk boyutu optimize edildi
            with session.get(ts_url, headers=HEADERS, stream=True, timeout=15) as r:
                # Vavoo 200 harici dönerse veri gönderme (Hatalı 207 byte'ı önler)
                if r.status_code == 200:
                    for chunk in r.iter_content(chunk_size=16384):
                        yield chunk
        except:
            pass
    return Response(stream_with_context(generate()), content_type="video/mp2t")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
