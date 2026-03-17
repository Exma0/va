-- ╔══════════════════════════════════════════════════════╗
-- ║       NETWORK TP - Gelişmiş Sunucu & TPA Sistemi     ║
-- ║       BungeeCord Otomatik Sunucu Algılama v3         ║
-- ╚══════════════════════════════════════════════════════╝

local TpaRequests = {}   -- hedef_adı → gönderen_adı
local ValidServers = {}
local HasFetchedServers = false

function Initialize(Plugin)
    Plugin:SetName("NetworkTP")
    Plugin:SetVersion(3)

    cPluginManager.BindCommand("/tp",       "", HandleTpCommand,       "Sunucuya geçiş yaparsın.")
    cPluginManager.BindCommand("/tpa",      "", HandleTpaCommand,      "Bir oyuncuya ışınlanma isteği atarsın.")
    cPluginManager.BindCommand("/tpaccept", "", HandleTpAcceptCommand, "Sana gelen ışınlanma isteğini kabul edersin.")
    cPluginManager.BindCommand("/tpdeny",   "", HandleTpDenyCommand,   "Sana gelen ışınlanma isteğini reddedersin.")

    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_JOINED,    OnPlayerJoined)
    cPluginManager.AddHook(cPluginManager.HOOK_PLUGIN_MESSAGE,   OnPluginMessage)

    -- DÜZELTME #1: Oyuncu sunucudan ayrıldığında bekleyen TPA isteği
    -- TpaRequests tablosunda sonsuza kadar kalıyordu (bellek sızıntısı).
    -- Hem gönderici hem de hedef ayrıldığında ilgili kayıt temizleniyor.
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    LOG("[NetworkTP] v3 Yüklendi - BungeeCord Otomatik Algılama + TPA Temizleme Aktif!")
    return true
end

-- ══════════════════════════════════════════════════════
--  BUNGEECORD HABERLEŞME MOTORU (Byte Parsing)
-- ══════════════════════════════════════════════════════

local function WriteJavaString(str)
    local len = #str
    local b1 = math.floor(len / 256)
    local b2 = len % 256
    return string.char(b1, b2) .. str
end

local function ReadJavaString(msg, offset)
    if offset + 1 > #msg then return nil, offset end
    local len = string.byte(msg, offset) * 256 + string.byte(msg, offset + 1)
    offset = offset + 2
    if offset + len - 1 > #msg then return nil, offset end
    local str = string.sub(msg, offset, offset + len - 1)
    return str, offset + len
end

function OnPlayerJoined(Player)
    if not HasFetchedServers then
        Player:SendPluginMessage("BungeeCord", WriteJavaString("GetServers"))
    end
end

function OnPluginMessage(ClientHandle, Channel, Message)
    if Channel ~= "BungeeCord" then return false end

    local subchannel, offset = ReadJavaString(Message, 1)
    
    if subchannel == "GetServers" then
        local serverListStr, _ = ReadJavaString(Message, offset)
        if serverListStr then
            ValidServers = {}
            for server in string.gmatch(serverListStr, "([^,]+)") do
                server = string.gsub(server, "^%s*(.-)%s*$", "%1")
                ValidServers[string.lower(server)] = true
            end
            HasFetchedServers = true
            LOG("[NetworkTP] BungeeCord'daki sunucular otomatik eklendi: " .. serverListStr)
        end
    end
    return false
end

-- ══════════════════════════════════════════════════════
--  OYUNCU AYRILINCA TEMİZLEME
-- ══════════════════════════════════════════════════════
function OnPlayerDestroyed(Player)
    local leavingName = Player:GetName()

    -- Hedef ayrıldı: bekleyen isteği iptal et ve göndericiyi bildir
    if TpaRequests[leavingName] then
        local senderName = TpaRequests[leavingName]
        TpaRequests[leavingName] = nil
        cRoot:Get():FindAndDoWithPlayer(senderName, function(SenderPlayer)
            SenderPlayer:SendMessageFailure("§c" .. leavingName .. " §esunucudan ayrıldı; ışınlanma isteği iptal edildi.")
        end)
    end

    -- Gönderici ayrıldı: hedefin tablosundaki kaydı temizle
    for targetName, senderName in pairs(TpaRequests) do
        if senderName == leavingName then
            TpaRequests[targetName] = nil
            break
        end
    end
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

    if ValidServers[target] or not HasFetchedServers then
        Player:SendMessageSuccess("§a" .. string.upper(target) .. " §esunucusuna bağlanılıyor, lütfen bekle...")
        Player:SendPluginMessage("BungeeCord", WriteJavaString("Connect") .. WriteJavaString(target))
        return true
    end

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

        -- DÜZELTME #2: Önceki bir TPA isteği varsa eski göndericiye sessizce
        -- kaybolmak yerine iptal mesajı gönder.
        if TpaRequests[tName] then
            local oldSender = TpaRequests[tName]
            if oldSender ~= senderName then
                cRoot:Get():FindAndDoWithPlayer(oldSender, function(OldSender)
                    OldSender:SendMessageFailure("§c" .. tName .. " §eyeni bir ışınlanma isteği aldı; senin isteğin iptal edildi.")
                end)
            end
        end

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

    TpaRequests[targetName] = nil  -- Kabul/red öncesinde temizle (çift işlem koruması)

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

    TpaRequests[targetName] = nil  -- Reddetmeden önce temizle

    cRoot:Get():FindAndDoWithPlayer(senderName, function(SenderPlayer)
        SenderPlayer:SendMessageFailure("§c" .. targetName .. " §eışınlanma isteğini reddetti.")
    end)

    Player:SendMessageSuccess("§eIşınlanma isteği reddedildi ve iptal edildi.")
    return true
end
