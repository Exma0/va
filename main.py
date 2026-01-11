import requests
import re
import time
import threading
import queue
from urllib.parse import urljoin, urlparse
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)
requests.packages.urllib3.disable_warnings()

# Global ayarlar
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {"User-Agent": UA, "Referer": "https://vavoo.to/", "Connection": "keep-alive"}

def resolve_url(base, rel):
    return urljoin(base, rel)

@app.route('/')
def main_controller():
    channel_id = request.args.get('id')
    
    if channel_id:
        # Buffer Boyutu: 512MB RAM'in yaklaşık 100-150MB'ını sadece videoya ayırıyoruz (Yaklaşık 10-15 segment)
        # 0.1 CPU olduğu için thread sayısını dengeli tutuyoruz
        buffer_queue = queue.Queue(maxsize=15) 
        played_segments = set()

        def generate():
            master_url = f"https://vavoo.to/play/{channel_id}/index.m3u8"
            
            # 1. Playlist Çözümleme
            try:
                r = requests.get(master_url, headers=HEADERS, timeout=10, verify=False)
                content, base = r.text, r.url
                if "#EXT-X-STREAM-INF" in content:
                    match = re.search(r'[\r\n]+([^\r\n]+)', content.split('#EXT-X-STREAM-INF')[1])
                    if match: 
                        master_url = resolve_url(base, match.group(1).strip())
            except:
                return

            # 2. Arka Plan İşçisi (Vavoo'yu sömüren kısım)
            def prefetch_worker():
                nonlocal master_url
                fails = 0
                while fails < 20:
                    try:
                        r_m = requests.get(master_url, headers=HEADERS, timeout=7, verify=False)
                        if r_m.status_code != 200: raise Exception()
                        
                        lines = r_m.text.splitlines()
                        for line in lines:
                            if line and not line.startswith("#"):
                                ts_url = resolve_url(r_m.url, line)
                                name = urlparse(ts_url).path.split('/')[-1]
                                
                                if name not in played_segments:
                                    # Segmenti indirirken 2 paralel istek at (En hızlıyı al)
                                    segment_data = [None]
                                    def download_attempt():
                                        try:
                                            # Zaman aşımını uzun tutuyoruz ki yavaş da olsa insin
                                            res = requests.get(ts_url, headers=HEADERS, timeout=15, verify=False)
                                            if res.status_code == 200 and segment_data[0] is None:
                                                segment_data[0] = res.content
                                        except: pass

                                    t1 = threading.Thread(target=download_attempt)
                                    t2 = threading.Thread(target=download_attempt)
                                    t1.start(); t2.start()
                                    t1.join(timeout=16); t2.join(timeout=1) # Bekleme süresi

                                    if segment_data[0]:
                                        # RAM'e koy (Kuyruk doluysa boşalana kadar bekle)
                                        buffer_queue.put(segment_data[0], timeout=60)
                                        played_segments.add(name)
                                        if len(played_segments) > 60:
                                            # Bellek yönetimi: listedeki en eski ismi sil
                                            played_segments.remove(next(iter(played_segments)))
                        
                        fails = 0
                        time.sleep(1) # Playlist yenileme hızı
                    except Exception:
                        fails += 1
                        time.sleep(2)

            # İşçiyi hemen başlat
            worker_thread = threading.Thread(target=prefetch_worker, daemon=True)
            worker_thread.start()

            # 3. İstemciye (VLC) RAM'den Veri Akışı
            while True:
                try:
                    # Kuyrukta hazır bekleyen segmenti al ve gönder
                    chunk = buffer_queue.get(timeout=45) 
                    yield chunk
                except queue.Empty:
                    # Eğer Vavoo o kadar yavaşsa ki kuyruk boşaldıysa...
                    break 

        return Response(stream_with_context(generate()), content_type='video/mp2t')

    else:
        # Liste Kısmı (Aynı kalıyor)
        try:
            r = requests.get('https://vavoo.to/live2/index', headers={"User-Agent": UA}, timeout=20, verify=False)
            json_data = r.text
        except: return "Liste Hatasi"
            
        output = "#EXTM3U\n"
        pattern = r'"group":"Turkey".*?"name":"([^"]+)".*?"url":"([^"]+)"'
        matches = re.finditer(pattern, json_data, re.IGNORECASE | re.DOTALL)
        base_self = request.base_url.rstrip('/')
        for m in matches:
            name = m.group(1).encode().decode('unicode_escape').replace(',', '')
            id_match = re.search(r'/play/(\d+)', m.group(2))
            if id_match:
                output += f'#EXTINF:-1 group-title="Turkey",{name}\n{base_self}?id={id_match.group(1)}\n'
        return Response(output, content_type='application/x-mpegURL')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
