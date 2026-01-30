<?php
ob_start();
// ============================================================================
// XC API PROXY & BACKGROUND REFRESH SYSTEM (V3 - FINAL ULTIMATE)
// ============================================================================
// Özellikler:
// 1. Canlı TV, Film ve Dizi Yönlendirme (/live, /movie, /series)
// 2. Timeshift / Catch-up Desteği (/timeshift)
// 3. EPG, Playlist ve Portal Desteği (xmltv.php, get.php, portal.php)
// 4. Arka Planda Sessiz Hesap Yenileme (Kullanıcıyı bekletmez)
// 5. Akıllı Önbellek (Hesap 12 saati geçerse işaretler, 25 saati geçerse zorla yeniler)
// ============================================================================

// Kullanıcı bağlantıyı kesse bile script ölene kadar çalışsın
ignore_user_abort(true);
// Süre sınırını kaldır (Arka plan işlemi için şart)
set_time_limit(0);

// Hataları gizle (API çıktısını bozmamak için şart)
error_reporting(0);
ini_set('display_errors', 0);
date_default_timezone_set('Europe/Istanbul');

// AYARLAR
$jsonFile = __DIR__ . '/account.json';
$targetHost = "http://link4tv.me"; 

// Değişkenleri başlat
$realUser = "";
$realPass = "";
$needsUpdate = false; 

// ============================================================================
// 1. MEVCUT DURUMU KONTROL ET (Hesap var mı, yaşı kaç?)
// ============================================================================
if (file_exists($jsonFile)) {
    $fileData = file_get_contents($jsonFile);
    $json = json_decode($fileData, true);

    if ($json && isset($json['created_at'])) {
        $age = time() - $json['created_at'];
        
        // 12 Saat (43200 sn) geçtiyse "Yenileme Gerekiyor" işaretini koy
        // Ama hesap hala çalışıyor (24 saat dolmadı), o yüzden kullanıcıyı bekletme.
        if ($age > 43200) { 
            $needsUpdate = true;
        }
        
        $realUser = $json['u'];
        $realPass = $json['p'];
        
        // Eğer hesap ÇOK eskiyse (25 saatten fazla / 90000 sn), artık ölüdür.
        // Bu durumda kullanıcıyı mecburen bekletip yeni hesap üreteceğiz.
        if ($age > 90000) {
            $realUser = ""; 
        }
    }
}

// Eğer hiç hesap yoksa veya hesap çok bayatsa (25+ saat), şimdi üret.
if (empty($realUser)) {
    generateNewAccount($jsonFile);
    // Üretim bitti, taze veriyi çek
    $fileData = file_get_contents($jsonFile);
    $json = json_decode($fileData, true);
    $realUser = $json['u'];
    $realPass = $json['p'];
    $needsUpdate = false; // Zaten şu an ürettik
}

// ============================================================================
// 2. YÖNLENDİRME MANTIĞI (ROUTER)
// ============================================================================

$requestUri = $_SERVER['REQUEST_URI'];
$finalRedirectUrl = "";

// A) STANDART STREAM (Canlı, Film, Dizi) - Örn: /live/user/pass/123.ts
if (preg_match('#/(live|movie|series)/([^/]+)/([^/]+)/([0-9]+)\.(ts|m3u8|mp4|mkv|avi)#', $requestUri, $matches)) {
    $type = $matches[1];
    // $matches[2] ve [3] eski kullanıcı adı/şifredir, çöpe atıyoruz.
    $streamId = $matches[4];
    $ext = $matches[5];
    // Taze bilgilerle linki oluştur
    $finalRedirectUrl = "$targetHost/$type/$realUser/$realPass/$streamId.$ext";
} 
// B) TIMESHIFT STREAM (Geriye Sarma) - Örn: /timeshift/user/pass/süre/zaman/123.ts
elseif (preg_match('#/timeshift/([^/]+)/([^/]+)/([0-9]+)/([0-9\-\:T\s]+)/([0-9]+)\.ts#', $requestUri, $matches)) {
    $duration = $matches[3]; // Süre
    $start = $matches[4];    // Başlangıç zamanı
    $streamId = $matches[5]; // Kanal ID
    $finalRedirectUrl = "$targetHost/timeshift/$realUser/$realPass/$duration/$start/$streamId.ts";
}
// C) API İSTEKLERİ (player_api, xmltv, get, portal vb.)
else {
    // Mevcut GET parametrelerini al (örn: ?username=x&password=y&action=...)
    $currentParams = $_GET;
    
    // Bizim taze hesap bilgilerini enjekte et (Eskilerini ezer)
    $currentParams['username'] = $realUser;
    $currentParams['password'] = $realPass;

    // Hangi dosya çağrıldıysa ona göre yönlendir
    if (strpos($requestUri, 'xmltv.php') !== false) {
        // EPG İsteği
        $finalRedirectUrl = $targetHost . "/xmltv.php?" . http_build_query($currentParams);
    } 
    elseif (strpos($requestUri, 'get.php') !== false) {
        // M3U İndirme İsteği
        $finalRedirectUrl = $targetHost . "/get.php?" . http_build_query($currentParams);
    }
    elseif (strpos($requestUri, 'panel_api.php') !== false) {
        // Panel API
        $finalRedirectUrl = $targetHost . "/panel_api.php?" . http_build_query($currentParams);
    }
    elseif (strpos($requestUri, 'portal.php') !== false) {
        // MAG/STB Portal
        $finalRedirectUrl = $targetHost . "/portal.php?" . http_build_query($currentParams);
    }
    else {
        // Varsayılan: Standart XC API
        $finalRedirectUrl = $targetHost . "/player_api.php?" . http_build_query($currentParams);
    }
}

// ============================================================================
// 3. KULLANICIYA YANIT VER VE BAĞLANTIYI KES (FAST RESPONSE)
// ============================================================================

// 1. Yönlendirme başlığını ayarla
header("Location: " . $finalRedirectUrl);

// 2. İçerik uzunluğunu 0 ver (Gövde yok, sadece header)
header("Content-Length: 0");

// 3. Bağlantıyı kapat (Tarayıcı/Oynatıcı işlemi bitti sanacak)
header("Connection: close");

// 4. Tamponu boşalt ve gönder
if (ob_get_level()) ob_end_flush();
flush();

// 5. Eğer sunucuda fastcgi varsa işlemi resmen bitir (Nginx/PHP-FPM için süperdir)
if (function_exists('fastcgi_finish_request')) {
    fastcgi_finish_request();
}

// ============================================================================
// 4. ARKA PLAN İŞLEMLERİ (BACKGROUND PROCESS)
// ============================================================================
// Buradan aşağısı çalışırken kullanıcının haberi olmaz, beklemez.

if ($needsUpdate) {
    // Hesap 12 saati geçmiş. Kullanıcı yayınını aldı ve gitti.
    // Şimdi biz arkada sakince yeni hesabı üretip dosyaya yazalım.
    // Böylece bir sonraki istekte 0 saniye bekleme ile taze hesap sunulacak.
    generateNewAccount($jsonFile);
}

exit(); 

// ============================================================================
// 5. YARDIMCI FONKSİYONLAR
// ============================================================================

function generateNewAccount($jsonFile) {
    $retryLimit = 5; // En fazla 5 kere dene
    
    while ($retryLimit > 0) {
        $retryLimit--;
        
        $G_IDENTITY = getAdvancedFingerprint();
        $G_IP = generateRandomIP();

        // 1. Port Tara
        $ports = range(10000, 10060); 
        $mh = curl_multi_init();
        $handles = [];
        $foundPort = null;

        foreach ($ports as $port) {
            $ch = curl_init('https://www.weselliptv.com/api/check-proxy');
            $data = json_encode(['port' => intval($port)]);
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, $data);
            curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json', 'User-Agent: ' . $G_IDENTITY['ua'], "X-Forwarded-For: $G_IP"]);
            curl_setopt($ch, CURLOPT_TIMEOUT, 3);
            curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
            curl_multi_add_handle($mh, $ch);
            $handles[$port] = $ch;
        }

        $running = null;
        do { curl_multi_exec($mh, $running); } while ($running);
        
        foreach ($handles as $port => $ch) {
            $content = curl_multi_getcontent($ch);
            $json = json_decode($content, true);
            curl_multi_remove_handle($mh, $ch);
            curl_close($ch);
            if (isset($json['working']) && $json['working'] === true) {
                if (!$foundPort) $foundPort = $port;
            }
        }
        curl_multi_close($mh);

        if (!$foundPort) { sleep(1); continue; } // Port yoksa başa dön

        // 2. Deneme Hesabı İste
        $uniqueID = generateUUIDv4();
        $email = $uniqueID . "@gmail.com";
        
        $response = stealthRequest('https://www.weselliptv.com/api/trial', [
            'email' => $email,
            'proxyPort' => intval($foundPort)
        ], 15, $G_IDENTITY, $G_IP);
        
        if (!isset($response['json']['handle']['id'])) { sleep(1); continue; }

        // 3. Görev Durumunu Kontrol Et
        $taskId = $response['json']['handle']['id'];
        $counter = 0;
        
        while (true) {
            $counter++;
            $statusRes = stealthRequest("https://www.weselliptv.com/api/task-status?taskId=$taskId", null, 15, $G_IDENTITY, $G_IP);
            $stData = $statusRes['json'];

            if (isset($stData['status'])) {
                $st = $stData['status'];
                if ($st == 'COMPLETED') {
                    $finalUser = $stData['data']['output']['username'];
                    $finalPass = $stData['data']['output']['password'];
                    
                    $saveData = [
                        "u" => $finalUser,
                        "p" => $finalPass,
                        "h" => "http://link4tv.me", // Sabit host
                        "created_at" => time()
                    ];
                    
                    // Dosyaya yaz (Lock ile çakışmayı önle)
                    file_put_contents($jsonFile, json_encode($saveData), LOCK_EX);
                    @chmod($jsonFile, 0666);
                    return; // İşlem Başarılı
                }
                if ($st == 'FAILED' || $st == 'CANCELED') { break; }
            }
            sleep(2);
            if ($counter > 60) break; // 2 dakika dolarsa vazgeç
        }
        sleep(1);
    }
}

function getAdvancedFingerprint() {
    $majorVer = mt_rand(120, 124); 
    $minorVer = mt_rand(0, 9999) . "." . mt_rand(0, 150);
    $fullVer = "$majorVer.0.$minorVer";
    $platforms = [
        ['name' => '"Windows"', 'ua' => "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$fullVer Safari/537.36"],
        ['name' => '"macOS"', 'ua' => "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$fullVer Safari/537.36"],
        ['name' => '"Linux"', 'ua' => "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$fullVer Safari/537.36"]
    ];
    $p = $platforms[array_rand($platforms)];
    return ['ua' => $p['ua'], 'platform' => $p['name'], 'version' => (string)$majorVer];
}

function generateRandomIP() {
    do { $ip = mt_rand(1, 223) . "." . mt_rand(0, 255) . "." . mt_rand(0, 255) . "." . mt_rand(0, 255); } 
    while (preg_match('/^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.|0\.)/', $ip));
    return $ip;
}

function generateUUIDv4() {
    try {
        $data = random_bytes(16);
        $data[6] = chr(ord($data[6]) & 0x0f | 0x40); 
        $data[8] = chr(ord($data[8]) & 0x3f | 0x80); 
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
    } catch (Exception $e) { return uniqid('', true); }
}

function stealthRequest($url, $postData = null, $customTimeout = 10, $identity, $ip) {
    $ch = curl_init($url);
    $headers = [
        'Accept: application/json, text/plain, */*',
        'Origin: https://www.weselliptv.com',
        'Referer: https://www.weselliptv.com/free-trial',
        'User-Agent: ' . $identity['ua'],
        'X-Forwarded-For: ' . $ip, 'Client-IP: ' . $ip,
        'Content-Type: application/json', 'Connection: keep-alive'
    ];
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
    curl_setopt($ch, CURLOPT_TIMEOUT, $customTimeout);
    if ($postData) {
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($postData));
    }
    $res = curl_exec($ch);
    $json = json_decode($res, true);
    curl_close($ch);
    return ['json' => $json, 'raw' => $res];
}
?>
