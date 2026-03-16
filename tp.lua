-- ╔══════════════════════════════════════════════════════╗
-- ║       NETWORK TP - Gelişmiş Sunucu & TPA Sistemi     ║
-- ║       BungeeCord Otomatik Sunucu Algılama v2         ║
-- ╚══════════════════════════════════════════════════════╝

local TpaRequests = {}
local ValidServers = {} -- Artık buraya isim yazmana gerek yok, BungeeCord dolduracak!
local HasFetchedServers = false

function Initialize(Plugin)
    Plugin:SetName("NetworkTP")
    Plugin:SetVersion(2)

    cPluginManager:BindCommand("/tp",       "", HandleTpCommand,       "Sunucuya geçiş yaparsın.")
    cPluginManager:BindCommand("/tpa",      "", HandleTpaCommand,      "Bir oyuncuya ışınlanma isteği atarsın.")
    cPluginManager:BindCommand("/tpaccept", "", HandleTpAcceptCommand, "Sana gelen ışınlanma isteğini kabul edersin.")
    cPluginManager:BindCommand("/tpdeny",   "", HandleTpDenyCommand,   "Sana gelen ışınlanma isteğini reddedersin.")

    -- BungeeCord ile haberleşebilmek için gerekli Event Hook'ları
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_JOINED,   OnPlayerJoined)
    cPluginManager:AddHook(cPluginManager.HOOK_PLUGIN_MESSAGE,  OnPluginMessage)

    LOG("[NetworkTP] v2 Yüklendi - BungeeCord Otomatik Algılama Sistemi Aktif!")
    return true
end

-- ══════════════════════════════════════════════════════
--  BUNGEECORD HABERLEŞME MOTORU (Byte Parsing)
-- ══════════════════════════════════════════════════════

-- Java UTF-8 formatını Cuberite'ın anlayabileceği Byte dizisine çevirir
local function WriteJavaString(str)
    local len = #str
    local b1 = math.floor(len / 256)
    local b2 = len % 256
    return string.char(b1, b2) .. str
end

-- BungeeCord'dan gelen karmaşık Byte paketlerini metne (String) dönüştürür
local function ReadJavaString(msg, offset)
    if offset + 1 > #msg then return nil, offset end
    local len = string.byte(msg, offset) * 256 + string.byte(msg, offset + 1)
    offset = offset + 2
    if offset + len - 1 > #msg then return nil, offset end
    local str = string.sub(msg, offset, offset + len - 1)
    return str, offset + len
end

function OnPlayerJoined(Player)
    -- Eklenti iletişiminin çalışması için sunucuda en az 1 kişi olması gerekir.
    -- İlk oyuncu girdiğinde BungeeCord'dan sunucu listesini istiyoruz.
    if not HasFetchedServers then
        Player:SendPluginMessage("BungeeCord", WriteJavaString("GetServers"))
    end
end

function OnPluginMessage(ClientHandle, Channel, Message)
    -- Mesaj BungeeCord'dan gelmiyorsa yoksay
    if Channel ~= "BungeeCord" then return false end

    local subchannel, offset = ReadJavaString(Message, 1)
    
    -- Gelen paket bizim istediğimiz "GetServers" yanıtı mı?
    if subchannel == "GetServers" then
        local serverListStr, _ = ReadJavaString(Message, offset)
        if serverListStr then
            ValidServers = {} -- Eski listeyi temizle
            
            -- "hub, gm1, survival" formatındaki stringi virgüllerden bölüp listeye ekle
            for server in string.gmatch(serverListStr, "([^,]+)") do
                server = string.gsub(server, "^%s*(.-)%s*$", "%1") -- Boşlukları sil
                ValidServers[string.lower(server)] = true
            end
            
            HasFetchedServers = true
            LOG("[NetworkTP] BungeeCord'daki sunucular otomatik eklendi: " .. serverListStr)
        end
    end
    return false
end

-- ══════════════════════════════════════════════════════
--  SUNUCU DEĞİŞTİRME (/tp <Sunucu>)
-- ══════════════════════════════════════════════════════
function HandleTpCommand(Split, Player)
    if #Split < 2 then
        Player:SendMessageInfo("§eKullanım: §7/tp <SunucuAdı>")
        Player:SendMessageInfo("§7Oyuncuya gitmek için: §e/tpa <OyuncuAdı>")
        return true
    end

    local target = string.lower(Split[2])

    -- Hedef BungeeCord listesinde var mı? (Ya da liste henüz çekilmediyse bile denemesine izin ver)
    if ValidServers[target] or not HasFetchedServers then
        Player:SendMessageSuccess("§a" .. string.upper(target) .. " §esunucusuna bağlanılıyor, lütfen bekle...")
        
        -- BungeeCord'a "Connect" sinyali yolla
        Player:SendPluginMessage("BungeeCord", WriteJavaString("Connect") .. WriteJavaString(target))
        return true
    end

    -- Eğer listede yoksa bu bir oyuncudur diye uyarı ver
    Player:SendMessageWarning("§cAğ üzerinde '" .. target .. "' §aadında bir sunucu bulunamadı!")
    Player:SendMessageInfo("§7Eğer bir oyuncunun yanına gitmek istiyorsan §e/tpa " .. target .. " §7yazmalısın.")
    return true
end

-- ══════════════════════════════════════════════════════
--  IŞINLANMA İSTEĞİ (/tpa <Oyuncu>)
-- ══════════════════════════════════════════════════════
function HandleTpaCommand(Split, Player)
    if #Split < 2 then
        Player:SendMessageInfo("§eKullanım: §7/tpa <OyuncuAdı>")
        return true
    end

    local senderName = Player:GetName()
    local targetName = Split[2]

    if string.lower(senderName) == string.lower(targetName) then
        Player:SendMessageFailure("§cKendine ışınlanma isteği atamazsın!")
        return true
    end

    local isPlayerFound = false

    cRoot:Get():FindAndDoWithPlayer(targetName, function(TargetPlayer)
        isPlayerFound = true
        local tName = TargetPlayer:GetName()

        TpaRequests[tName] = senderName
        
        Player:SendMessageSuccess("§a" .. tName .. " §eadlı oyuncuya ışınlanma isteği gönderildi.")
        
        TargetPlayer:SendMessageSuccess("§6" .. senderName .. " §esana ışınlanmak istiyor!")
        TargetPlayer:SendMessageInfo("§7Kabul etmek için §a/tpaccept§7, reddetmek için §c/tpdeny §7yaz.")
    end)

    if not isPlayerFound then
        Player:SendMessageFailure("§cOyuncu bulunamadı! (Çevrimdışı veya farklı bir sunucuda olabilir)")
    end

    return true
end

-- ══════════════════════════════════════════════════════
--  İSTEK KABUL ETME (/tpaccept)
-- ══════════════════════════════════════════════════════
function HandleTpAcceptCommand(Split, Player)
    local targetName = Player:GetName()
    local senderName = TpaRequests[targetName]

    if not senderName then
        Player:SendMessageFailure("§cSana gönderilmiş bekleyen bir ışınlanma isteği yok.")
        return true
    end

    local isSenderFound = false

    cRoot:Get():FindAndDoWithPlayer(senderName, function(SenderPlayer)
        isSenderFound = true
        SenderPlayer:TeleportToEntity(Player)
        SenderPlayer:SendMessageSuccess("§a" .. targetName .. " §eisteğini kabul etti! Işınlandın.")
        Player:SendMessageSuccess("§a" .. senderName .. " §eyanına ışınlandı.")
    end)

    if not isSenderFound then
        Player:SendMessageFailure("§cİsteği atan oyuncu şu an çevrimdışı veya başka sunucuya geçmiş.")
    end

    TpaRequests[targetName] = nil
    return true
end

-- ══════════════════════════════════════════════════════
--  İSTEK REDDETME (/tpdeny)
-- ══════════════════════════════════════════════════════
function HandleTpDenyCommand(Split, Player)
    local targetName = Player:GetName()
    local senderName = TpaRequests[targetName]

    if not senderName then
        Player:SendMessageFailure("§cSana gönderilmiş bekleyen bir ışınlanma isteği yok.")
        return true
    end

    cRoot:Get():FindAndDoWithPlayer(senderName, function(SenderPlayer)
        SenderPlayer:SendMessageFailure("§c" .. targetName .. " §eışınlanma isteğini reddetti.")
    end)

    Player:SendMessageSuccess("§eIşınlanma isteği reddedildi ve iptal edildi.")
    TpaRequests[targetName] = nil
    return true
end
