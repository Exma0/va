import os
import re
import time
import threading
import requests
from collections import deque
from urllib.parse import urljoin, urlparse
from flask import Flask, Response, request, stream_with_context

# ======================================================
# APP
# ======================================================
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

BASE_DIR = "/tmp/vavoo_buf"
RAM_SEGMENTS = 15          # ~15 segment RAM
DISK_SEGMENTS = 120        # disk üzerinde ~2–4 dk
DEFAULT_SHIFT = 0

os.makedirs(BASE_DIR, exist_ok=True)

# ======================================================
# SHARED BUFFER OBJECT
# ======================================================
class SharedStream:
    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.master_url = f"https://vavoo.to/play/{channel_id}/index.m3u8"
        self.segment_duration = 2.0

        self.ram_buffer = deque(maxlen=RAM_SEGMENTS)   # [(name, data)]
        self.segment_index = deque(maxlen=DISK_SEGMENTS)  # segment name FIFO

        self.lock = threading.Lock()
        self.running = False

        self.disk_path = os.path.join(BASE_DIR, channel_id)
        os.makedirs(self.disk_path, exist_ok=True)

    # --------------------------------------------------
    def resolve_master(self):
        r = requests.get(self.master_url, headers=HEADERS, timeout=10, verify=False)
        if "#EXT-X-STREAM-INF" in r.text:
            m = re.search(r'#EXT-X-STREAM-INF.*\n(.+)', r.text)
            if m:
                self.master_url = urljoin(r.url, m.group(1).strip())

    # --------------------------------------------------
    def worker(self):
        self.resolve_master()

        while True:
            try:
                pl = requests.get(self.master_url, headers=HEADERS, timeout=10, verify=False)
                lines = pl.text.splitlines()

                segments = []
                for line in lines:
                    if line.startswith("#EXTINF"):
                        try:
                            self.segment_duration = float(line.split(':')[1].split(',')[0])
                        except:
                            pass
                    if line and not line.startswith("#"):
                        segments.append(urljoin(pl.url, line))

                for ts in segments:
                    name = urlparse(ts).path.split('/')[-1]

                    with self.lock:
                        if name in self.segment_index:
                            continue

                    rts = requests.get(ts, headers=HEADERS, timeout=15, verify=False)
                    if rts.status_code != 200:
                        continue

                    data = rts.content

                    with self.lock:
                        # RAM
                        self.ram_buffer.append((name, data))

                        # DISK
                        fpath = os.path.join(self.disk_path, name)
                        with open(fpath, "wb") as f:
                            f.write(data)

                        self.segment_index.append(name)

                        # Disk cleanup
                        if len(self.segment_index) >= DISK_SEGMENTS:
                            old = self.segment_index[0]
                            op = os.path.join(self.disk_path, old)
                            if os.path.exists(op):
                                try: os.remove(op)
                                except: pass

                time.sleep(max(self.segment_duration * 0.8, 1))

            except:
                time.sleep(2)

    # --------------------------------------------------
    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self.worker, daemon=True).start()

# ======================================================
# GLOBAL STREAM REGISTRY (MULTI-CLIENT)
# ======================================================
STREAMS = {}
STREAM_LOCK = threading.Lock()

def get_stream(cid):
    with STREAM_LOCK:
        if cid not in STREAMS:
            STREAMS[cid] = SharedStream(cid)
            STREAMS[cid].start()
        return STREAMS[cid]

# ======================================================
# CONTROLLER
# ======================================================
@app.route('/')
def controller():
    cid = request.args.get('id')
    if not cid:
        return "NO ID"

    shift = int(request.args.get('shift', DEFAULT_SHIFT))

    stream = get_stream(cid)

    def generate():
        # -------------------------------
        # DVR OFFSET HESABI
        # -------------------------------
        with stream.lock:
            seg_back = int(shift / max(stream.segment_duration, 1))
            start_index = max(len(stream.segment_index) - seg_back, 0)
            play_list = list(stream.segment_index)[start_index:]

        # -------------------------------
        # DISK'TEN GERİDEN BAŞLA
        # -------------------------------
        for name in play_list:
            fpath = os.path.join(stream.disk_path, name)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    yield f.read()

        # -------------------------------
        # CANLI RAM AKIŞI
        # -------------------------------
        last_sent = set(play_list)

        while True:
            with stream.lock:
                for name, data in list(stream.ram_buffer):
                    if name not in last_sent:
                        last_sent.add(name)
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
