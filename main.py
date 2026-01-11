import requests
import re
import time
import threading
import queue
from collections import deque
from urllib.parse import urljoin, urlparse
from flask import Flask, Response, request, stream_with_context

# ======================================================
# APP
# ======================================================
app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

# ======================================================
# GLOBAL HEADERS
# ======================================================
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Origin": "https://vavoo.to",
    "Connection": "keep-alive"
}

# ======================================================
# URL RESOLVER
# ======================================================
def resolve_url(base, rel):
    return urljoin(base, rel)

# ======================================================
# MAIN CONTROLLER
# ======================================================
@app.route('/')
def controller():
    channel_id = request.args.get('id')

    # ==================================================
    # PLAY MODE
    # ==================================================
    if channel_id:

        buffer_queue = queue.Queue(maxsize=12)   # ~10–15 sn RAM buffer
        played_segments = deque(maxlen=100)      # FIFO segment takibi

        def stream_generator():
            # ------------------------------
            # MASTER PLAYLIST
            # ------------------------------
            master_url = f"https://vavoo.to/play/{channel_id}/index.m3u8"

            try:
                r = requests.get(master_url, headers=HEADERS, timeout=10, verify=False)
                base = r.url
                content = r.text

                # Variant varsa en üst kaliteyi al
                if "#EXT-X-STREAM-INF" in content:
                    m = re.search(r'#EXT-X-STREAM-INF.*\n(.+)', content)
                    if m:
                        master_url = resolve_url(base, m.group(1).strip())
            except:
                return

            segment_duration = 2.0

            # ------------------------------
            # PREFETCH WORKER
            # ------------------------------
            def prefetch_worker():
                nonlocal segment_duration
                while True:
                    try:
                        pl = requests.get(master_url, headers=HEADERS, timeout=10, verify=False)
                        lines = pl.text.splitlines()

                        segments = []
                        for i, line in enumerate(lines):
                            if line.startswith("#EXTINF"):
                                try:
                                    segment_duration = float(line.split(':')[1].split(',')[0])
                                except:
                                    pass
                            if line and not line.startswith("#"):
                                segments.append(resolve_url(pl.url, line))

                        for ts_url in segments:
                            name = urlparse(ts_url).path.split('/')[-1]
                            if name in played_segments:
                                continue

                            try:
                                rts = requests.get(ts_url, headers=HEADERS, timeout=15, verify=False)
                                if rts.status_code == 200:
                                    buffer_queue.put(rts.content)
                                    played_segments.append(name)
                            except:
                                pass

                        time.sleep(max(segment_duration * 0.8, 1))

                    except:
                        time.sleep(2)

            # Worker başlat
            threading.Thread(target=prefetch_worker, daemon=True).start()

            # ------------------------------
            # CLIENT STREAM
            # ------------------------------
            while True:
                try:
                    chunk = buffer_queue.get(timeout=60)
                    yield chunk
                except queue.Empty:
                    # Donma yerine bekle
                    time.sleep(1)
                    continue

        return Response(
            stream_with_context(stream_generator()),
            content_type='video/mp2t',
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    # ==================================================
    # PLAYLIST MODE
    # ==================================================
    else:
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

        output = "#EXTM3U\n"
        base_self = request.base_url.rstrip('/')

        pattern = r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"'
        for m in re.finditer(pattern, data, re.IGNORECASE | re.DOTALL):
            name = m.group(1).encode().decode('unicode_escape').replace(',', '')
            id_match = re.search(r'/play/(\d+)', m.group(2))
            if id_match:
                output += f'#EXTINF:-1 group-title="Turkey",{name}\n'
                output += f'{base_self}?id={id_match.group(1)}\n'

        return Response(output, content_type='application/x-mpegURL')

# ======================================================
# RUN
# ======================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
