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

# Global Cache: {cid: {'time': timestamp, 'url': base_url, 'content': m3u8_text}}
m3u8_cache = {}

def get_fresh_m3u8(cid):
    """
    Kanalın en güncel m3u8 verisini çeker. 
    Eğer 2 saniye içinde çekilmişse hafızadan verir (Hız ve engellenmemek için).
    """
    now = time.time()
    if cid in m3u8_cache and (now - m3u8_cache[cid]['time'] < 2.0):
        return m3u8_cache[cid]['url'], m3u8_cache[cid]['content']

    try:
        # Vavoo bazen POST bazen GET ister ama genellikle play/{id}/index.m3u8 çalışır
        # Redirectleri takip eder (allow_redirects=True defaulttur)
        r = session.get(f"{SOURCE}/play/{cid}/index.m3u8", verify=False, timeout=5)
        if r.status_code == 200:
            # Redirect sonrası asıl base URL'yi al
            base_url = r.url.rsplit('/', 1)[0]
            content = r.text
            m3u8_cache[cid] = {'time': now, 'url': base_url, 'content': content}
            return base_url, content
    except Exception as e:
        print(f"Update Error: {e}")
    return None, None

def proxy_req(url):
    try:
        # Stream=True ile veriyi parça parça aktar
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
        r = session.get(f"{SOURCE}/live2/index", verify=False, timeout=5)
        data = r.json()
    except: return Response("Source Error", 503)
    
    host = request.host_url.rstrip('/')
    out = ["#EXTM3U"]
    
    # Sadece Türkiye grubunu filtrele
    for i in data:
        if i.get("group") == "Turkey":
            try:
                # URL yapısından CID'yi temizle
                raw_url = i['url']
                # Genelde url şöyledir: http://.../play/123456/index.m3u8
                if '/play/' in raw_url:
                    cid = raw_url.split('/play/', 1)[1].split('/', 1)[0].replace('.m3u8', '')
                    name = i["name"].replace(",", " ")
                    out.append(f'#EXTINF:-1 group-title="Turkey",{name}')
                    # Bizim sunucuya yönlendir
                    out.append(f"{host}/live/{cid}.m3u8")
            except: pass
            
    return Response("\n".join(out), content_type="application/x-mpegURL")

@app.route('/live/<cid>.m3u8')
def m3u8_endpoint(cid):
    base_url, content = get_fresh_m3u8(cid)
    if not content:
        return Response("Stream Not Found", 404)

    host = request.host_url.rstrip('/')
    out = []
    
    # Satır satır işle
    for line in content.splitlines():
        line = line.strip()
        if not line: continue
        
        if line.startswith('#'):
            out.append(line)
        else:
            # Burası TS dosyasıdır.
            # Eski yöntem: URL'yi şifreleyip gönderiyorduk (Link ölüyordu).
            # Yeni yöntem: Sadece dosya ismini ve CID'yi gönderiyoruz.
            # TS dosyasının adı genellikle unique'dir veya sıralıdır.
            ts_filename = line.split('/')[-1] # örn: segment_150.ts veya tokenli_uzun_isim.ts
            
            # Client'a bizim TS endpointimizi veriyoruz, CID ve dosya ismini parametre geçiyoruz
            new_link = f"{host}/ts?cid={cid}&file={ts_filename}"
            out.append(new_link)

    return Response("\n".join(out), content_type="application/vnd.apple.mpegurl")

@app.route('/ts')
def ts_endpoint():
    # Bu endpoint her çağrıldığında GÜNCEL linki bulur.
    cid = request.args.get('cid')
    filename = request.args.get('file')
    
    if not cid or not filename:
        return Response("Bad Request", 400)

    # 1. Adım: Kanalın en son m3u8'ini hafızadan veya netten çek
    base_url, content = get_fresh_m3u8(cid)
    if not base_url:
        return Response("Stream Lost", 404)

    # 2. Adım: İstenen dosyayı m3u8 içinde ara ve gerçek URL'sini bul
    target_url = None
    
    # Hızlı eşleşme için satırları tara
    lines = content.splitlines()
    for line in lines:
        if filename in line: # Dosya ismini içeren satırı bulduk
            line = line.strip()
            if line.startswith('http'):
                target_url = line
            else:
                target_url = f"{base_url}/{line}"
            break
    
    # Eğer o anki m3u8'de yoksa, belki liste yenilendi, bir şans daha verip taze çekelim (force refresh)
    if not target_url:
         # Cache'i bypass edip zorla yenile
        if cid in m3u8_cache: del m3u8_cache[cid] 
        base_url, content = get_fresh_m3u8(cid)
        if content:
             for line in content.splitlines():
                if filename in line:
                    line = line.strip()
                    if line.startswith('http'):
                        target_url = line
                    else:
                        target_url = f"{base_url}/{line}"
                    break

    # 3. Adım: Bulduysak indirip yayınla
    if target_url:
        return proxy_req(target_url)
    else:
        return Response("Segment expired or not found", 404)

if __name__ == "__main__":
    print(f"Yayın sunucusu {PORT} portunda başlatıldı...")
    WSGIServer(('0.0.0.0', PORT), app, log=None).serve_forever()
