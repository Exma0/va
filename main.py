from gevent import monkey; monkey.patch_all()
import requests, urllib3, logging, time
from gevent.pywsgi import WSGIServer
from flask import Flask, Response, request, stream_with_context

# Ayarlar
SOURCE = "https://vavoo.to"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
PORT = 8080

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

# Global Cache Yapısı: 
# {cid: {'time': timestamp, 'map': {filename: full_url}, 'raw_m3u8': text}}
m3u8_cache = {}

def parse_m3u8_to_map(base_url, content):
    """
    M3U8 içeriğini tarar ve dosya isimlerini anahtar, tam URL'leri değer olarak bir sözlüğe atar.
    Bu işlem arama hızını O(n)'den O(1)'e düşürür.
    """
    segment_map = {}
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'): continue
        
        # Dosya ismini URL'den ayıkla (query parametrelerini atarak)
        # Örn: segment_1.ts?token=xyz -> segment_1.ts
        full_url = line if line.startswith('http') else f"{base_url}/{line}"
        
        # Sadece dosya ismini al (token öncesi)
        filename = line.split('/')[-1].split('?')[0]
        segment_map[filename] = full_url
        
    return segment_map

def get_fresh_m3u8(cid, force_refresh=False):
    """
    Kanalın verisini çeker ve parse edilmiş haritayı döndürür.
    """
    now = time.time()
    
    # Eğer zorla yenileme istenmemişse ve veri yeniyse cache'den dön
    if not force_refresh and cid in m3u8_cache and (now - m3u8_cache[cid]['time'] < 4.0): # Süreyi 4sn yaptım, Vavoo segmentleri 10sn sürer
        return m3u8_cache[cid]['map'], m3u8_cache[cid]['raw_m3u8']

    try:
        r = session.get(f"{SOURCE}/play/{cid}/index.m3u8", verify=False, timeout=5)
        if r.status_code == 200:
            base_url = r.url.rsplit('/', 1)[0]
            content = r.text
            
            # PARSE İŞLEMİNİ BURADA BİR KERE YAPIYORUZ
            seg_map = parse_m3u8_to_map(base_url, content)
            
            m3u8_cache[cid] = {'time': now, 'map': seg_map, 'raw_m3u8': content}
            return seg_map, content
    except Exception as e:
        print(f"Update Error ({cid}): {e}")
    
    return None, None

def proxy_req(url):
    try:
        r = session.get(url, stream=True, verify=False, timeout=10)
        if r.status_code == 200:
            return Response(stream_with_context(r.iter_content(chunk_size=8192)), content_type="video/mp2t")
        else:
            return Response(f"Source returned {r.status_code}", status=r.status_code)
    except Exception as e:
        return Response(str(e), 502)

@app.route('/')
def root():
    try:
        # Liste çekme işlemi de bazen zaman aşımına uğrayabilir, try-except kalsın
        r = session.get(f"{SOURCE}/live2/index", verify=False, timeout=8)
        data = r.json()
    except: return Response("Source Error or Timeout", 503)
    
    host = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    for i in data:
        if i.get("group") == "Turkey":
            try:
                raw_url = i['url']
                if '/play/' in raw_url:
                    cid = raw_url.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                    name = i["name"].replace(",", " ")
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}')
                    out.append(f"{host}/live/{cid}.m3u8")
            except: pass
            
    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def m3u8_endpoint(cid):
    # force_refresh=False ile çağırıyoruz
    seg_map, content = get_fresh_m3u8(cid)
    if not content:
        return Response("Stream Not Found", 404)

    host = request.host_url.rstrip('/')
    out = []
    
    for line in content.splitlines():
        line = line.strip()
        if not line: continue
        
        if line.startswith('#'):
            out.append(line)
        else:
            # TS dosyasının adını al (token kısmını at)
            # Vavoo'da bazen index.m3u8 içinde de tokenli url döner, temizleyip sadece dosya ismini alalım
            raw_filename = line.split('/')[-1]
            ts_filename = raw_filename.split('?')[0] # Query string varsa temizle
            
            # Client'a temiz isim gönderiyoruz
            new_link = f"{host}/ts?cid={cid}&file={ts_filename}"
            out.append(new_link)

    return Response("\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def ts_endpoint():
    cid = request.args.get('cid')
    filename = request.args.get('file')
    
    if not cid or not filename:
        return Response("Bad Request", 400)

    # 1. Adım: Cache'deki haritaya bak
    seg_map, _ = get_fresh_m3u8(cid, force_refresh=False)
    
    target_url = None
    if seg_map:
        target_url = seg_map.get(filename)

    # 2. Adım: Eğer haritada yoksa, yayın ilerlemiş olabilir. ZORLA YENİLE (Force Refresh)
    if not target_url:
        # print(f"Segment {filename} cache'de yok, yenileniyor...")
        seg_map, _ = get_fresh_m3u8(cid, force_refresh=True)
        if seg_map:
            target_url = seg_map.get(filename)

    # 3. Adım: Proxy
    if target_url:
        return proxy_req(target_url)
    else:
        return Response("Segment expired", 404)

if __name__ == "__main__":
    print(f"Yayın sunucusu {PORT} portunda başlatıldı...")
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
