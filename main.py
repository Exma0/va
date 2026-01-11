import re, time, threading, requests
from collections import deque
from urllib.parse import urljoin, urlparse
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

# ======================================================
# CONFIG
# ======================================================
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}

RAM_SEGMENTS = 30
DEFAULT_START = 10

# ======================================================
# SHARED STREAM (RAM ONLY)
# ======================================================
class SharedStream:
    def __init__(self, cid):
        self.cid = cid
        self.master = f"https://vavoo.to/play/{cid}/index.m3u8"
        self.seg_dur = 2.0
        self.buffer = deque(maxlen=RAM_SEGMENTS)
        self.lock = threading.Lock()
        self.running = False

    def resolve_master(self):
        r = requests.get(self.master, headers=HEADERS, timeout=10, verify=False)
        if "#EXT-X-STREAM-INF" in r.text:
            m = re.search(r'#EXT-X-STREAM-INF.*\n(.+)', r.text)
            if m:
                self.master = urljoin(r.url, m.group(1).strip())

    def worker(self):
        self.resolve_master()
        seen = set()
        while True:
            try:
                pl = requests.get(self.master, headers=HEADERS, timeout=10, verify=False)
                for line in pl.text.splitlines():
                    if line.startswith("#EXTINF"):
                        try:
                            self.seg_dur = float(line.split(':')[1].split(',')[0])
                        except:
                            pass
                    if line and not line.startswith("#"):
                        ts = urljoin(pl.url, line)
                        name = urlparse(ts).path.split('/')[-1]
                        if name in seen:
                            continue
                        rts = requests.get(ts, headers=HEADERS, timeout=15, verify=False)
                        if rts.status_code == 200:
                            with self.lock:
                                self.buffer.append((name, rts.content))
                            seen.add(name)
                time.sleep(max(self.seg_dur * 0.8, 1))
            except:
                time.sleep(2)

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self.worker, daemon=True).start()

# ======================================================
# STREAM REGISTRY
# ======================================================
STREAMS = {}
LOCK = threading.Lock()

def get_stream(cid):
    with LOCK:
        if cid not in STREAMS:
            STREAMS[cid] = SharedStream(cid)
            STREAMS[cid].start()
        return STREAMS[cid]

# ======================================================
# ROOT PLAYLIST (DIRECT M3U)
# ======================================================
@app.route('/')
def playlist():
    start = int(request.args.get('start', DEFAULT_START))
    try:
        r = requests.get(
            "https://vavoo.to/live2/index",
            headers={"User-Agent": UA},
            timeout=20,
            verify=False
        )
        data = r.text
    except:
        return "LIST ERROR"

    base = request.host_url.rstrip('/')
    out = "#EXTM3U\n"

    pattern = r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"'
    for m in re.finditer(pattern, data, re.DOTALL):
        name = m.group(1).encode().decode('unicode_escape').replace(',', '')
        mid = re.search(r'/play/(\d+)', m.group(2))
        if mid:
            out += f'#EXTINF:-1 group-title="Turkey",{name}\n'
            out += f'{base}/channel.m3u8?id={mid.group(1)}&start={start}\n'

    return Response(out, content_type="application/x-mpegURL")

# ======================================================
# VLC EXT-X-START PLAYLIST
# ======================================================
@app.route('/channel.m3u8')
def channel():
    cid = request.args.get('id')
    start = int(request.args.get('start', DEFAULT_START))
    if not cid:
        return "NO ID"

    get_stream(cid)

    m3u = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-START:TIME-OFFSET=-{start},PRECISE=YES",
        "#EXT-X-TARGETDURATION:5",
        "#EXT-X-MEDIA-SEQUENCE:0",
        f"{request.host_url.rstrip('/')}/stream.ts?id={cid}&shift={start}"
    ]

    return Response("\n".join(m3u), content_type="application/x-mpegURL")

# ======================================================
# TS STREAM
# ======================================================
@app.route('/stream.ts')
def stream_ts():
    cid = request.args.get('id')
    shift = int(request.args.get('shift', 0))
    if not cid:
        return "NO ID"

    s = get_stream(cid)

    def generate():
        with s.lock:
            back = int(shift / max(s.seg_dur, 1))
            start = max(len(s.buffer) - back, 0)
            play = list(s.buffer)[start:]
        sent = set()
        for name, data in play:
            sent.add(name)
            yield data
        while True:
            with s.lock:
                for name, data in list(s.buffer):
                    if name not in sent:
                        sent.add(name)
                        yield data
            time.sleep(0.2)

    return Response(
        stream_with_context(generate()),
        content_type="video/mp2t",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# ======================================================
# RUN
# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
