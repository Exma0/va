import requests
import re
import time
import threading
import queue
from urllib.parse import urljoin, urlparse
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {"User-Agent": UA, "Referer": "https://vavoo.to/", "Connection": "keep-alive"}

def resolve_url(base, rel):
    return urljoin(base, rel)

# --- AKILLI SEGMENT İNDİRİCİ (RACE + RETRY) ---
def fetch_segment(url):
    """Segmenti çekmek için 2 paralel deneme yapar (Race Condition)."""
    result = [None]
    def download():
        try:
            r = requests.get(url, headers=HEADERS, timeout=8, verify=False)
            if r.status_code == 200 and len(r.content) > 1024:
                if result[0] is None: result[0] = r.content
        except: pass

    threads = [threading.Thread(target=download) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=9)
    return result[0]

@app.route('/')
def main_controller():
    channel_id = request.args.get('id')
    
    if channel_id:
        def generate():
            master_url = f"https://vavoo.to/play/{channel_id}/index.m3u8"
            played_segments = []
            buffer_queue = queue.Queue(maxsize=5) # Arka planda 5 segment biriktirir
            
            # 1. Playlist Çözümleme
            r = requests.get(master_url, headers=HEADERS, timeout=5, verify=False)
            content, base = r.text, r.url
            if "#EXT-X-STREAM-INF" in content:
                match = re.search(r'[\r\n]+([^\r\n]+)', content.split('#EXT-X-STREAM-INF')[1])
                if match: 
                    master_url = resolve_url(base, match.group(1).strip())

            # 2. ARKA PLAN İŞÇİSİ (Pre-fetcher)
            # Sen izlerken o bir sonraki parçaları RAM'e doldurur
            def worker():
                while True:
                    try:
                        r_m = requests.get(master_url, headers=HEADERS, timeout=5, verify=False)
                        lines = r_m.text.splitlines()
                        for line in lines:
                            if line and not line.startswith("#"):
                                ts_url = resolve_url(r_m.url, line)
                                name = urlparse(ts_url).path.split('/')[-1]
                                
                                if name not in played_segments:
                                    data = fetch_segment(ts_url)
                                    if data:
                                        buffer_queue.put(data, timeout=15)
                                        played_segments.append(name)
                                        if len(played_segments) > 40: played_segments.pop(0)
                        time.sleep(1)
                    except: time.sleep(2)

            # İşçiyi başlat
            t = threading.Thread(target=worker, daemon=True)
            t.start()

            # 3. VERİ AKIŞI (Consumer)
            # Kuyruktaki verileri oynatıcıya (VLC) basar
            consecutive_fails = 0
            while consecutive_fails < 20:
                try:
                    # Kuyruktan veriyi al (VLC'ye gönder)
                    # 15 saniye içinde veri gelmezse döngü kırılır
                    chunk = buffer_queue.get(timeout=20) 
                    yield chunk
                    consecutive_fails = 0
                except queue.Empty:
                    consecutive_fails += 1
                    time.sleep(0.5)

        return Response(stream_with_context(generate()), content_type='video/mp2t')

    else:
        # Liste Oluşturma (Turkey kanalları)
        try:
            r = requests.get('https://vavoo.to/live2/index', headers={"User-Agent": UA}, timeout=15, verify=False)
            json_raw = r.text
        except: return "Hata"
            
        output = "#EXTM3U\n"
        pattern = r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"'
        matches = re.finditer(pattern, json_raw, re.IGNORECASE | re.DOTALL)
        base_self = request.base_url.rstrip('/')
        for m in matches:
            name = m.group(1).encode().decode('unicode_escape')
            name = re.sub(r'[,"\r\n]', '', name).strip()
            id_match = re.search(r'/play/(\d+)', m.group(2))
            if id_match:
                output += f'#EXTINF:-1 group-title="Turkey",{name}\n{base_self}?id={id_match.group(1)}\n'
        return Response(output, content_type='application/x-mpegURL')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
