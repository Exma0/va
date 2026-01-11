import requests
import re
import time
from urllib.parse import urljoin, urlparse
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {"User-Agent": UA, "Referer": "https://vavoo.to/", "Connection": "keep-alive"}

def resolve_url(base, rel):
    return urljoin(base, rel)

def get_data(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10, verify=False)
        return r.text, r.url
    except:
        return None, None

@app.route('/')
def main_controller():
    channel_id = request.args.get('id')
    if channel_id:
        def generate():
            master_url = f"https://vavoo.to/play/{channel_id}/index.m3u8"
            played_segments = []
            content, base = get_data(master_url)
            if not content: return
            if "#EXT-X-STREAM-INF" in content:
                match = re.search(r'[\r\n]+([^\r\n]+)', content.split('#EXT-X-STREAM-INF')[1])
                if match: master_url = resolve_url(base, match.group(1).strip())

            while True:
                content, base = get_data(master_url)
                if not content: break
                lines = content.splitlines()
                dur = 2.0
                for line in lines:
                    line = line.strip()
                    if line.startswith("#EXTINF:"):
                        try: dur = float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0])
                        except: dur = 2.0
                    if line and not line.startswith("#"):
                        ts_url = resolve_url(base, line)
                        name = urlparse(ts_url).path.split('/')[-1]
                        if name not in played_segments:
                            try:
                                with requests.get(ts_url, headers=HEADERS, stream=True, timeout=10, verify=False) as r:
                                    for chunk in r.iter_content(chunk_size=16384):
                                        if chunk: yield chunk
                            except: pass
                            played_segments.append(name)
                            if len(played_segments) > 30: played_segments.pop(0)
                time.sleep(dur / 2)
        return Response(stream_with_context(generate()), content_type='video/mp2t')
    else:
        try:
            r = requests.get('https://vavoo.to/live2/index', headers={"User-Agent": UA}, timeout=20, verify=False)
            json_raw = r.text
        except:
            return "#EXTM3U\n#EXTINF:-1,HATA: Veri Alinamadi\n"
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
