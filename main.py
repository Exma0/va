import requests
import re
import time
import threading
from urllib.parse import urljoin, urlparse
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://vavoo.to/",
    "Connection": "keep-alive"
}

def resolve_url(base, rel):
    return urljoin(base, rel)

# --- MOTOR 1: INSTANT START (PHP stream_direct_pipe karşılığı) ---
def stream_direct(url):
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=5, verify=False) as r:
            for chunk in r.iter_content(chunk_size=16384):
                if chunk:
                    yield chunk
    except:
        pass

# --- MOTOR 2: RACE & BURST (PHP download_race_burst karşılığı) ---
def download_race_burst(url):
    """3 farklı kanaldan veriyi ister, ilk bitenden veriyi alır."""
    winner_data = [None]
    event = threading.Event()

    def racer():
        try:
            # Taze bağlantı için session kullanmıyoruz (PHP Fresh Connect mantığı)
            r = requests.get(url, headers=HEADERS, timeout=6, verify=False)
            if r.status_code == 200 and len(r.content) > 1024:
                if not event.is_set():
                    winner_data[0] = r.content
                    event.set()
        except:
            pass

    threads = []
    for _ in range(3): # 3 sunucuyla yarış
        t = threading.Thread(target=racer)
        t.start()
        threads.append(t)

    # Maksimum 6 saniye bekle veya biri bitene kadar dur
    event.wait(timeout=6)
    return winner_data[0]

def get_playlist(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=5, verify=False)
        return r.text, r.url
    except:
        return None, None

@app.route('/')
def main_controller():
    channel_id = request.args.get('id')
    
    # --- MOD 1: FUSION OYNATICI ---
    if channel_id:
        def generate():
            master_url = f"https://vavoo.to/play/{channel_id}/index.m3u8"
            played_segments = []
            first_run = True

            while True:
                content, base = get_playlist(master_url)
                if not content:
                    time.sleep(1)
                    continue
                
                # Master/Varyant kontrolü
                if "#EXT-X-STREAM-INF" in content:
                    match = re.search(r'[\r\n]+([^\r\n]+)', content.split('#EXT-X-STREAM-INF')[1])
                    if match:
                        master_url = resolve_url(base, match.group(1).strip())
                        continue

                lines = content.splitlines()
                dur = 4.0
                found_new = False

                for line in lines:
                    line = line.strip()
                    if line.startswith("#EXTINF:"):
                        try:
                            dur = float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0])
                        except: dur = 4.0
                    
                    if line and not line.startswith("#"):
                        ts_url = resolve_url(base, line)
                        name = urlparse(ts_url).path.split('/')[-1]

                        if name not in played_segments:
                            if first_run:
                                # FAZ 1: İLK AÇILIŞ (Hız Odaklı)
                                for chunk in stream_direct(ts_url):
                                    yield chunk
                                first_run = False
                            else:
                                # FAZ 2: DEVAMLILIK (Race & Burst)
                                data = download_race_burst(ts_url)
                                if data:
                                    yield data
                            
                            played_segments.append(name)
                            found_new = True
                            if len(played_segments) > 40:
                                played_segments.pop(0)
                
                if found_new:
                    # PHP: usleep((int)($dur * 0.85 * 1000000))
                    time.sleep(dur * 0.7) 
                else:
                    time.sleep(0.5)

        return Response(stream_with_context(generate()), content_type='video/mp2t')

    # --- MOD 2: LISTE (Flash Regex) ---
    else:
        try:
            r = requests.get('https://vavoo.to/live2/index', headers={"User-Agent": UA}, timeout=20, verify=False)
            json_raw = r.text
        except:
            return "#EXTM3U\n#EXTINF:-1,HATA: Liste Alinamadi\n"
            
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
