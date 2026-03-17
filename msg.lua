-- ╔══════════════════════════════════════════════════════╗
-- ║       SOHBET VE YARDIM KOMUTLARI EKLENTİSİ v2        ║
-- ║       /yardim, /msg, /r, /zar, /kurallar             ║
-- ╚══════════════════════════════════════════════════════╝

local LastMsg = {} -- Hangi oyuncunun en son kime mesaj attığını tutar

function Initialize(Plugin)
    Plugin:SetName("SohbetKomutlari")
    Plugin:SetVersion(2)

    -- Yardım Komutları
    cPluginManager.BindCommand("/yardim",   "", HandleYardimCommand,   "Kullanabileceğin tüm komutları listeler.")
    cPluginManager.BindCommand("/komutlar", "", HandleYardimCommand,   "Kullanabileceğin tüm komutları listeler.")

    -- Sohbet Komutları
    cPluginManager.BindCommand("/msg",      "", HandleMsgCommand,      "Bir oyuncuya özel mesaj gönderir.")
    cPluginManager.BindCommand("/r",        "", HandleReplyCommand,    "Sana gelen son özel mesaja hızlı yanıt verir.")
    cPluginManager.BindCommand("/zar",      "", HandleZarCommand,      "1 ile 100 arasında şans zarı atar.")
    cPluginManager.BindCommand("/kurallar", "", HandleKurallarCommand, "Sunucu kurallarını gösterir.")
    
    -- Hafıza sızıntısını önlemek için çıkan oyuncuları temizle
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    LOG("[Sohbet] v2 Aktif - Yardım menüsü ve sohbet komutları yüklendi!")
    return true
end

-- ══════════════════════════════════════════════════════
--  YARDIM MENÜSÜ (/yardim veya /komutlar)
-- ══════════════════════════════════════════════════════
function HandleYardimCommand(Split, Player)
    Player:SendMessage(" ")
    Player:SendMessage("§8§m                                     ")
    Player:SendMessage("§3§l      ♦ WC NETWORK KOMUTLARI ♦      ")
    Player:SendMessage("§8§m                                     ")
    Player:SendMessage("§a/hub §7veya §a/sunucu §f- Sunucu listesini açar.")
    Player:SendMessage("§a/tp <sunucu> §f- Başka bir sunucuya geçiş yaparsın.")
    Player:SendMessage("§a/tpa <oyuncu> §f- Bir oyuncuya ışınlanma isteği atarsın.")
    Player:SendMessage("§a/tpaccept §f- Gelen ışınlanma isteğini kabul edersin.")
    Player:SendMessage("§a/tpdeny §f- Gelen ışınlanma isteğini reddedersin.")
    Player:SendMessage("§e/msg <oyuncu> <mesaj> §f- Özel mesaj gönderirsin.")
    Player:SendMessage("§e/r <mesaj> §f- Sana gelen son mesaja yanıt verirsin.")
    Player:SendMessage("§e/zar §f- 1-100 arası şans zarı atarsın.")
    Player:SendMessage("§e/kurallar §f- Sunucu kurallarını gösterir.")
    Player:SendMessage("§8§m                                     ")
    Player:SendMessage(" ")
    return true
end

-- ══════════════════════════════════════════════════════
--  ÖZEL MESAJLAŞMA (/msg ve /r)
-- ══════════════════════════════════════════════════════
function HandleMsgCommand(Split, Player)
    if #Split < 3 then
        Player:SendMessageInfo("§eKullanım: §7/msg <Oyuncu> <Mesaj>")
        return true
    end

    local TargetName = Split[2]
    local Message = table.concat(Split, " ", 3)
    local SenderName = Player:GetName()

    if string.lower(TargetName) == string.lower(SenderName) then
        Player:SendMessageFailure("§cKendinize mesaj gönderemezsiniz!")
        return true
    end

    local Found = false
    cRoot:Get():FindAndDoWithPlayer(TargetName, function(TargetPlayer)
        Found = true
        local RealTargetName = TargetPlayer:GetName()

        Player:SendMessage("§d[Ben -> " .. RealTargetName .. "] §f" .. Message)
        TargetPlayer:SendMessage("§d[" .. SenderName .. " -> Ben] §f" .. Message)

        LastMsg[SenderName] = RealTargetName
        LastMsg[RealTargetName] = SenderName
    end)

    if not Found then
        Player:SendMessageFailure("§c" .. TargetName .. " §aadlı oyuncu bulunamadı veya çevrimdışı.")
    end
    return true
end

function HandleReplyCommand(Split, Player)
    if #Split < 2 then
        Player:SendMessageInfo("§eKullanım: §7/r <Mesaj>")
        return true
    end

    local SenderName = Player:GetName()
    local TargetName = LastMsg[SenderName]

    if not TargetName then
        Player:SendMessageFailure("§cŞu anda yanıt vereceğiniz kimse yok.")
        return true
    end

    local Message = table.concat(Split, " ", 2)
    local Found = false

    cRoot:Get():FindAndDoWithPlayer(TargetName, function(TargetPlayer)
        Found = true
        Player:SendMessage("§d[Ben -> " .. TargetName .. "] §f" .. Message)
        TargetPlayer:SendMessage("§d[" .. SenderName .. " -> Ben] §f" .. Message)

        LastMsg[SenderName] = TargetName
        LastMsg[TargetName] = SenderName
    end)

    if not Found then
        Player:SendMessageFailure("§c" .. TargetName .. " §aadlı oyuncu şu an çevrimdışı.")
    end
    return true
end

function OnPlayerDestroyed(Player)
    LastMsg[Player:GetName()] = nil
end

-- ══════════════════════════════════════════════════════
--  EĞLENCE VE BİLGİ KOMUTLARI
-- ══════════════════════════════════════════════════════
function HandleZarCommand(Split, Player)
    local zar = math.random(1, 100)
    cRoot:Get():BroadcastChat("§e" .. Player:GetName() .. " §7zar attı ve §a" .. zar .. " §7geldi!")
    return true
end

function HandleKurallarCommand(Split, Player)
    Player:SendMessage("§8§m                                     ")
    Player:SendMessage("§c§l  SUNUCU KURALLARI")
    Player:SendMessage("§71. Küfür, hile ve 3. parti yazılım yasaktır.")
    Player:SendMessage("§72. Diğer oyunculara ve yetkililere saygılı olun.")
    Player:SendMessage("§73. Bug (oyun açığı) kullanmak ban sebebidir.")
    Player:SendMessage("§8§m                                     ")
    return true
end
