import ftplib
import io

# ================= AYARLAR =================
FTP_HOST = "x11.x10hosting.com"
FTP_USER = "gbbbhbdz"
FTP_PASS = "20192019zZ.."
FILENAME = "hello.txt"
FILE_CONTENT = "Merhaba, bu dosya Python scripti tarafindan olusturuldu."

def create_ftp_file():
    print(f"{FTP_HOST} sunucusuna baglaniliyor...")
    
    try:
        # 1. FTP Sunucusuna Bağlan
        ftp = ftplib.FTP(FTP_HOST)
        
        # 2. Giriş Yap
        ftp.login(FTP_USER, FTP_PASS)
        print("Giris basarili.")

        # 3. Dosya İçeriğini Hazırla (Bellekte sanal dosya oluşturma)
        # String'i byte formatına çeviriyoruz
        virtual_file = io.BytesIO(FILE_CONTENT.encode('utf-8'))

        # 4. Dosyayı Yükle (STOR komutu)
        print(f"{FILENAME} dosyasi yukleniyor...")
        ftp.storbinary(f'STOR {FILENAME}', virtual_file)

        # 5. Bağlantıyı Kapat
        ftp.quit()
        print("Islem tamamlandi. Dosya olusturuldu.")

    except ftplib.all_errors as e:
        print(f"FTP Hatasi olustu: {e}")

if __name__ == "__main__":
    create_ftp_file()
