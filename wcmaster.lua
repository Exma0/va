-- ╔══════════════════════════════════════════════════════╗
-- ║        WC NETWORK ULTIMATE MASTER PLUGIN v1.3        ║
-- ║  Sohbet, TP, Bungee, SafeSpawn, WCSync, ClearLag vb. ║
-- ║  * YENİ: Global Hata Yönetimi ve Chat Raporlama      ║
-- ╚══════════════════════════════════════════════════════╝

-- ========================================================
-- DEĞİŞKENLER (VARIABLES)
-- ========================================================
-- [SafeSpawn]
local E_BLOCK_WATER = 8
local E_BLOCK_STATIONARY_WATER = 9
local E_BLOCK_LAVA = 10
local E_BLOCK_STATIONARY_LAVA = 11

-- [ClearLag]
local ClearLag_Config = {
    Interval       = 300, 
    Warnings       = {60, 30, 10, 5, 3, 2, 1}, 
    ClearItems     = true,
    ClearExpOrbs   = true,
    ClearProjectiles= true,
    UnloadChunks   = true
}
local TimeUntilClear = ClearLag_Config.Interval

-- [Otomatik Sohbet Temizleyici]
local ChatClear_Config = {
    Enabled  = true,
    Interval = 600
}
local TimeUntilChatClear = ChatClear_Config.Interval

-- [NetworkTP]
local TpaRequests = {}   
local ValidServers = {}
local HasFetchedServers = false

-- [WCHub]
local ProxyURL = "http://127.0.0.1:{PORT}"
local HubLastSentTime = {} 
local HUB_COOLDOWN_SEC = 2

-- [WCSync]
local SyncRecentJoins  = {}
local SyncRecentQuits  = {}
local JOIN_DEDUP   = 5    
local QUIT_DEDUP   = 3    
local PLAYER_DIR = "/server/world/players/"

-- [Sohbet & Yardım]
local LastMsg = {}

-- ========================================================
-- HATA YÖNETİMİ (ERROR HANDLING) SİSTEMİ
-- ========================================================
function BroadcastError(kaynak, hata)
    local kisaHata = string.sub(tostring(hata), 1, 100)
    local mesaj = "§8[§4SİSTEM HATASI§8] §7" .. kaynak .. " -> §c" .. kisaHata
    cRoot:Get():BroadcastChat(mesaj)
    LOGWARNING("[WCMaster HATA] Kaynak: " .. kaynak .. " | Detay: " .. tostring(hata))
end

function SafeTask(kaynak, func)
    return function(a, b, c, d, e)
        local ok, err = pcall(function() return func(a, b, c, d, e) end)
        if not ok then BroadcastError(kaynak, err) end
    end
end

local function SafeWrap(funcName, sourceName)
    local originalFunc = _G[funcName]
    if type(originalFunc) == "function" then
        _G[funcName] = function(a, b, c, d, e)
            local ok, err = pcall(function() return originalFunc(a, b, c, d, e) end)
            if not ok then 
                BroadcastError(sourceName, err) 
                return true -- Komut hatasıysa sunucuyu çökertmeden işlemi iptal et
            end
            return err -- pcall başarılıysa asıl fonksiyonun dönüş değerini ilet
        end
    end
end

-- ========================================================
-- BAŞLATICI (INITIALIZE) VE KOMUT KAYITLARI
-- ========================================================
function Initialize(Plugin)
    Plugin:SetName("WCMasterPlugin")
    Plugin:SetVersion(3)

    local PM = cRoot:Get():GetPluginManager()

    -- [Yardım ve Sohbet Komutları]
    PM:BindCommand("/yardim",   "", "HandleYardimCommand",   "Kullanabileceğin komutları listeler.")
    PM:BindCommand("/komutlar", "", "HandleYardimCommand",   "Kullanabileceğin komutları listeler.")
    PM:BindCommand("/msg",      "", "HandleMsgCommand",      "Bir oyuncuya özel mesaj gönderir.")
    PM:BindCommand("/r",        "", "HandleReplyCommand",    "Son özel mesaja hızlı yanıt verir.")
    PM:BindCommand("/zar",      "", "HandleZarCommand",      "Zar atar.")
    PM:BindCommand("/kurallar", "", "HandleKurallarCommand", "Kuralları gösterir.")

    -- [Sohbet Temizleme Komutları]
    PM:BindCommand("/sil",      "chat.admin", "HandleClearChatCommand", "Sohbet penceresini temizler.")
    PM:BindCommand("/cc",       "chat.admin", "HandleClearChatCommand", "Sohbet penceresini temizler.")

    -- [NetworkTP Komutları]
    PM:BindCommand("/tp",       "", "HandleTpCommand",       "Sunucuya geçiş yaparsın.")
    PM:BindCommand("/tpa",      "", "HandleTpaCommand",      "Işınlanma isteği atarsın.")
    PM:BindCommand("/tpaccept", "", "HandleTpAcceptCommand", "Işınlanma isteğini kabul edersin.")
    PM:BindCommand("/tpdeny",   "", "HandleTpDenyCommand",   "Işınlanma isteğini reddedersin.")

    -- [WCHub Komutları]
    PM:BindCommand("/hub",         "", "HandleHubCommand",      "Sunucu listesini goster.")
    PM:BindCommand("/sunucu",      "", "HandleHubCommand",      "Sunucu listesini goster.")
    PM:BindCommand("/oyuncu",      "", "HandleHubCommand",      "Sunucu listesini goster.")
    PM:BindCommand("/wc_transfer", "", "HandleTransferCommand", "Sunucu transferi (proxy).")

    -- [ClearLag Komutları]
    PM:BindCommand("/clearlag", "clearlag.admin", "HandleClearLagCommand", "Lag temizleyici.")

    -- [WCSync Konsol Komutları]
    PM:BindConsoleCommand("wcreload", "HandleWcReload", "Oyuncu envanterini yeniden yukler.")

    -- [Merkezi Event Hook'ları]
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,   Global_OnPlayerSpawned)
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, Global_OnPlayerDestroyed)
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_JOINED,    Global_OnPlayerJoined)
    cPluginManager.AddHook(cPluginManager.HOOK_PLUGIN_MESSAGE,   Global_OnPluginMessage)

    -- Döngüleri Başlat
    cRoot:Get():GetDefaultWorld():ScheduleTask(20, TimerTick_ClearLag)
    if ChatClear_Config.Enabled then
        cRoot:Get():GetDefaultWorld():ScheduleTask(20, TimerTick_ClearChat)
    end

    -- ========================================================
    -- FONKSİYONLARI HATA KALKANI (WRAPPER) İLE KAPLA
    -- ========================================================
    SafeWrap("HandleYardimCommand", "/yardim komutu")
    SafeWrap("HandleMsgCommand", "/msg komutu")
    SafeWrap("HandleReplyCommand", "/r komutu")
    SafeWrap("HandleZarCommand", "/zar komutu")
    SafeWrap("HandleKurallarCommand", "/kurallar komutu")
    SafeWrap("HandleClearChatCommand", "/sil komutu")
    SafeWrap("HandleTpCommand", "/tp komutu")
    SafeWrap("HandleTpaCommand", "/tpa komutu")
    SafeWrap("HandleTpAcceptCommand", "/tpaccept komutu")
    SafeWrap("HandleTpDenyCommand", "/tpdeny komutu")
    SafeWrap("HandleHubCommand", "/hub komutu")
    SafeWrap("HandleTransferCommand", "Hub Transfer Sistemi")
    SafeWrap("HandleClearLagCommand", "/clearlag komutu")
    SafeWrap("HandleWcReload", "wcreload sistemi")

    SafeWrap("Global_OnPlayerSpawned", "Oyuncu Doğma (Spawn) Eventi")
    SafeWrap("Global_OnPlayerDestroyed", "Oyuncu Çıkış Eventi")
    SafeWrap("Global_OnPlayerJoined", "Oyuncu Katılma Eventi")
    SafeWrap("Global_OnPluginMessage", "BungeeCord Bağlantı Eventi")
    
    SafeWrap("TimerTick_ClearLag", "Otomatik Lag Temizleyici")
    SafeWrap("TimerTick_ClearChat", "Otomatik Sohbet Temizleyici")

    LOG("[WCMaster] v1.3 - Global Hata Koruma Sistemi AKTİF!")
    return true
end

-- ========================================================
-- MERKEZİ EVENT FONKSİYONLARI (GLOBAL HOOKS)
-- ========================================================
function Global_OnPlayerSpawned(Player)
    SafeSpawn_CheckLand(Player)
    WCHub_ShowMenu(Player)
    WCSync_JoinNotify(Player)
end

function Global_OnPlayerDestroyed(Player)
    LastMsg[Player:GetName()] = nil
    NetworkTP_CleanRequests(Player)
    HubLastSentTime[Player:GetUUID()] = nil
    WCSync_QuitNotify(Player)
end

function Global_OnPlayerJoined(Player)
    if not HasFetchedServers then
        Player:SendPluginMessage("BungeeCord", WriteJavaString("GetServers"))
    end
end

function Global_OnPluginMessage(ClientHandle, Channel, Message)
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
            LOG("[WCMaster] BungeeCord sunuculari eklendi: " .. serverListStr)
        end
    end
    return false
end

-- ========================================================
-- YARDIMCI FONKSİYONLAR (UTILS)
-- ========================================================
local function Hub_Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function WriteJavaString(str)
    local len = #str
    return string.char(math.floor(len / 256), len % 256) .. str
end

function ReadJavaString(msg, offset)
    if offset + 1 > #msg then return nil, offset end
    local len = string.byte(msg, offset) * 256 + string.byte(msg, offset + 1)
    offset = offset + 2
    if offset + len - 1 > #msg then return nil, offset end
    return string.sub(msg, offset, offset + len - 1), offset + len
end

-- ========================================================
-- OTOMATİK SOHBET TEMİZLEYİCİ (CLEAR CHAT)
-- ========================================================
function TimerTick_ClearChat(World)
    TimeUntilChatClear = TimeUntilChatClear - 1
    if TimeUntilChatClear <= 0 then
        PerformChatClear("Otomatik Sistem")
        TimeUntilChatClear = ChatClear_Config.Interval
    end
    World:ScheduleTask(20, TimerTick_ClearChat) -- Döngü, SafeWrap ile korumalıdır
end

function PerformChatClear(SenderName)
    for i = 1, 100 do
        cRoot:Get():BroadcastChat(" ")
    end
    cRoot:Get():BroadcastChatInfo("§8§m                                     ")
    cRoot:Get():BroadcastChatSuccess("§8[§bSistem§8] §aSohbet penceresi §e" .. SenderName .. " §atarafından temizlendi!")
    cRoot:Get():BroadcastChatInfo("§8§m                                     ")
end

function HandleClearChatCommand(Split, Player)
    PerformChatClear(Player:GetName())
    TimeUntilChatClear = ChatClear_Config.Interval 
    return true
end

-- ========================================================
-- SOHBET VE YARDIM SİSTEMİ
-- ========================================================
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

    if not Found then Player:SendMessageFailure("§c" .. TargetName .. " §aadlı oyuncu bulunamadı.") end
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

    if not Found then Player:SendMessageFailure("§c" .. TargetName .. " §aadlı oyuncu şu an çevrimdışı.") end
    return true
end

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

-- ========================================================
-- SAFESPAWN SİSTEMİ (OKYANUSTA DOĞMAYI ENGELLEME)
-- ========================================================
local function IsWater(blockType) return blockType == E_BLOCK_WATER or blockType == E_BLOCK_STATIONARY_WATER end
local function IsLava(blockType) return blockType == E_BLOCK_LAVA or blockType == E_BLOCK_STATIONARY_LAVA end

local function FindSafeLand(Player, World, startX, startZ, attempt)
    if attempt > 30 then
        Player:SendMessageFailure("§cÇok fazla okyanus var! Güvenli kara bulunamadı.")
        return
    end

    local searchX = startX + math.random(-800, 800)
    local searchZ = startZ + math.random(-800, 800)
    local chunkX = math.floor(searchX / 16)
    local chunkZ = math.floor(searchZ / 16)

    World:ChunkStay({ {chunkX, chunkZ} }, nil, SafeTask("SafeSpawn Zemin Tarama", function()
        local y = World:GetHeight(searchX, searchZ)
        if y > 0 then
            local blockSurface = World:GetBlock(searchX, y - 1, searchZ)
            if not IsWater(blockSurface) and not IsLava(blockSurface) and blockSurface ~= 0 then
                Player:TeleportToCoords(searchX + 0.5, y + 1.0, searchZ + 0.5)
                pcall(function() Player:SetBedPos(Vector3i(math.floor(searchX), math.floor(y + 1), math.floor(searchZ))) end)
                Player:SendMessageSuccess("§aKuru topraklara ulaştın! Doğuş noktan güncellendi.")
            else
                FindSafeLand(Player, World, startX, startZ, attempt + 1)
            end
        else
            FindSafeLand(Player, World, startX, startZ, attempt + 1)
        end
    end))
end

function SafeSpawn_CheckLand(Player)
    local World = Player:GetWorld()
    local UUID = Player:GetUUID()
    World:ScheduleTask(10, SafeTask("SafeSpawn Döngüsü", function()
        cRoot:Get():DoWithPlayerByUUID(UUID, function(P)
            local px, py, pz = math.floor(P:GetPosX()), math.floor(P:GetPosY()), math.floor(P:GetPosZ())
            local blockAtFeet = World:GetBlock(px, py, pz)
            local blockBelow  = World:GetBlock(px, py - 1, pz)
            if IsWater(blockAtFeet) or IsWater(blockBelow) then
                P:SendMessageWarning("§eOkyanusta doğdun! Seni güvenli bir karaya taşıyorum, lütfen bekle...")
                FindSafeLand(P, World, px, pz, 1)
            end
        end)
    end))
end

-- ========================================================
-- WCHUB SİSTEMİ (SUNUCU LİSTESİ)
-- ========================================================
function WCHub_ShowMenu(Player)
    Player:GetWorld():ScheduleTask(20, SafeTask("Hub Menü Açılışı", function() SendServerList(Player) end))
end

function HandleHubCommand(CmdSplit, Player)
    SendServerList(Player)
    return true
end

function HandleTransferCommand(CmdSplit, Player)
    return true
end

function SendServerList(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()
    if HubLastSentTime[UUID] and (now - HubLastSentTime[UUID]) < HUB_COOLDOWN_SEC then return end
    HubLastSentTime[UUID] = now

    local PlayerName = Player:GetName()
    local World      = Player:GetWorld()
    if not cUrlClient then return end

    cUrlClient:Get(ProxyURL .. "/api/servers", {
        OnSuccess = SafeTask("Sunucu Listesi Veri Çekme", function(Body)
            World:ScheduleTask(0, SafeTask("Sunucu Listesi Ekrana Yazma", function()
                local TargetPlayer = nil
                cRoot:Get():FindAndDoWithPlayer(PlayerName, function(P) TargetPlayer = P end)
                if not TargetPlayer or not Body or Body == "" then return end

                TargetPlayer:SendMessageInfo(" ")
                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo("§3§l      ♦ WC NETWORK AĞI ♦      ")
                TargetPlayer:SendMessageInfo("§7  Geçiş için §a[BAĞLAN]§7'a tıklayın:")
                TargetPlayer:SendMessageInfo(" ")

                local servers = Hub_Split(Body, ";")
                local count = 0
                for _, srv in ipairs(servers) do
                    local parts = Hub_Split(srv, ":")
                    if #parts == 2 then
                        count = count + 1
                        local msg = cCompositeChat()
                        msg:ParseText("  §8" .. count .. ". §b" .. parts[1] .. " §7(§e" .. parts[2] .. " §7oyuncu)   ")
                        msg:AddRunCommandPart("§a§n[BAĞLAN]", "/wc_transfer " .. parts[1])
                        TargetPlayer:SendMessage(msg)
                    end
                end

                if count == 0 then TargetPlayer:SendMessageInfo("§c  Şu an aktif sunucu yok.") end
                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo(" ")
            end))
        end),
        OnError = function(Err) end
    })
end

-- ========================================================
-- NETWORK TP & TPA SİSTEMİ
-- ========================================================
function NetworkTP_CleanRequests(Player)
    local leavingName = Player:GetName()
    if TpaRequests[leavingName] then
        local senderName = TpaRequests[leavingName]
        TpaRequests[leavingName] = nil
        cRoot:Get():FindAndDoWithPlayer(senderName, function(SP)
            SP:SendMessageFailure("§c" .. leavingName .. " §esunucudan ayrıldı; ışınlanma isteği iptal edildi.")
        end)
    end
    for targetName, senderName in pairs(TpaRequests) do
        if senderName == leavingName then TpaRequests[targetName] = nil break end
    end
end

function HandleTpCommand(Split, Player)
    if #Split < 2 then
        Player:SendMessageInfo("§eKullanım: §7/tp <SunucuAdı>")
        return true
    end
    local target = string.lower(Split[2])
    if ValidServers[target] or not HasFetchedServers then
        Player:SendMessageSuccess("§a" .. string.upper(target) .. " §esunucusuna bağlanılıyor, lütfen bekle...")
        Player:SendPluginMessage("BungeeCord", WriteJavaString("Connect") .. WriteJavaString(target))
        return true
    end
    Player:SendMessageWarning("§cAğ üzerinde '" .. target .. "' §aadında bir sunucu bulunamadı!")
    return true
end

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
    cRoot:Get():FindAndDoWithPlayer(targetName, function(TP)
        isPlayerFound = true
        local tName = TP:GetName()
        if TpaRequests[tName] and TpaRequests[tName] ~= senderName then
            cRoot:Get():FindAndDoWithPlayer(TpaRequests[tName], function(OldSender)
                OldSender:SendMessageFailure("§c" .. tName .. " §eyeni bir ışınlanma isteği aldı; senin isteğin iptal edildi.")
            end)
        end
        TpaRequests[tName] = senderName
        Player:SendMessageSuccess("§a" .. tName .. " §eadlı oyuncuya ışınlanma isteği gönderildi.")
        TP:SendMessageSuccess("§6" .. senderName .. " §esana ışınlanmak istiyor!")
        TP:SendMessageInfo("§7Kabul etmek için §a/tpaccept§7, reddetmek için §c/tpdeny §7yaz.")
    end)
    if not isPlayerFound then Player:SendMessageFailure("§cOyuncu bulunamadı!") end
    return true
end

function HandleTpAcceptCommand(Split, Player)
    local targetName = Player:GetName()
    local senderName = TpaRequests[targetName]
    if not senderName then Player:SendMessageFailure("§cSana gönderilmiş bekleyen bir ışınlanma isteği yok."); return true end
    
    TpaRequests[targetName] = nil  
    local isSenderFound = false
    cRoot:Get():FindAndDoWithPlayer(senderName, function(SP)
        isSenderFound = true
        SP:TeleportToEntity(Player)
        SP:SendMessageSuccess("§a" .. targetName .. " §eisteğini kabul etti! Işınlandın.")
        Player:SendMessageSuccess("§a" .. senderName .. " §eyanına ışınlandı.")
    end)
    if not isSenderFound then Player:SendMessageFailure("§cİsteği atan oyuncu şu an çevrimdışı.") end
    return true
end

function HandleTpDenyCommand(Split, Player)
    local targetName = Player:GetName()
    local senderName = TpaRequests[targetName]
    if not senderName then Player:SendMessageFailure("§cSana gönderilmiş bekleyen bir ışınlanma isteği yok."); return true end
    
    TpaRequests[targetName] = nil  
    cRoot:Get():FindAndDoWithPlayer(senderName, function(SP)
        SP:SendMessageFailure("§c" .. targetName .. " §eışınlanma isteğini reddetti.")
    end)
    Player:SendMessageSuccess("§eIşınlanma isteği reddedildi.")
    return true
end

-- ========================================================
-- WCSYNC (ENVANTER SENKRONİZASYONU)
-- ========================================================
function WCSync_JoinNotify(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()
    if SyncRecentJoins[UUID] and (now - SyncRecentJoins[UUID]) < JOIN_DEDUP then return end
    SyncRecentJoins[UUID] = now
    LOG("WCSYNC_JOIN:" .. Player:GetName() .. ":" .. UUID)
end

function WCSync_QuitNotify(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()
    if SyncRecentQuits[UUID] and (now - SyncRecentQuits[UUID]) < QUIT_DEDUP then return end
    SyncRecentQuits[UUID] = now
    LOG("WCSYNC_QUIT:" .. Player:GetName() .. ":" .. UUID)
end

function HandleWcReload(CmdSplit, EntireCommand)
    local name = CmdSplit[2]
    if not name or name == "" then return true end

    cRoot:Get():FindAndDoWithPlayer(name, function(Player)
        local UUID = Player:GetUUID()
        local uuidClean = UUID:gsub("%-", "")
        local paths = { PLAYER_DIR .. UUID .. ".json", PLAYER_DIR .. uuidClean .. ".json" }
        local content = nil

        for _, path in ipairs(paths) do
            local f = io.open(path, "r")
            if f then content = f:read("*all"); f:close(); break end
        end

        if not content or content == "" then return end
        local data, err = cJson:Parse(content)
        if not data then return end

        local inv = Player:GetInventory()
        inv:Clear()
        
        local items = data["Inventory"]
        if type(items) == "table" then
            for _, entry in ipairs(items) do
                local slot   = tonumber(entry["Slot"]   or -1)
                local itemID = tonumber(entry["ID"]     or 0)
                local count  = tonumber(entry["Count"]  or 1)
                local damage = tonumber(entry["Damage"] or 0)
                if slot >= 0 and itemID > 0 then
                    pcall(function() inv:SetSlot(slot, cItem(itemID, count, damage)) end)
                end
            end
        end

        if data["Health"] then
            local hp = tonumber(data["Health"]) or 20
            hp = math.max(1, math.min(hp, Player:GetMaxHealth()))
            pcall(function() Player:SetHealth(hp) end)
        end
        if data["FoodLevel"] then
            local food = tonumber(data["FoodLevel"]) or 20
            food = math.max(0, math.min(food, 20))
            pcall(function() Player:SetFoodLevel(food) end)
        end
    end)
    return true
end

-- ========================================================
-- CLEARLAG (LAG TEMİZLEYİCİ)
-- ========================================================
function TimerTick_ClearLag(World)
    TimeUntilClear = TimeUntilClear - 1

    for _, warnTime in ipairs(ClearLag_Config.Warnings) do
        if TimeUntilClear == warnTime then
            cRoot:Get():BroadcastChatWarning("§8[§cClearLag§8] §eYerlerdeki eşyalar §c" .. warnTime .. " §esaniye içinde silinecek!")
        end
    end

    if TimeUntilClear <= 0 then
        PerformClear()
        TimeUntilClear = ClearLag_Config.Interval
    end
    World:ScheduleTask(20, TimerTick_ClearLag) -- Döngü, SafeWrap ile korumalıdır
end

function PerformClear()
    local removedCount = 0
    cRoot:Get():ForEachWorld(function(TargetWorld)
        TargetWorld:ForEachEntity(function(Entity)
            local eType = Entity:GetEntityType()
            if ClearLag_Config.ClearItems and eType == cEntity.etItem then
                Entity:Destroy(); removedCount = removedCount + 1
            elseif ClearLag_Config.ClearExpOrbs and eType == cEntity.etExpOrb then
                Entity:Destroy(); removedCount = removedCount + 1
            elseif ClearLag_Config.ClearProjectiles and eType == cEntity.etProjectile then
                Entity:Destroy(); removedCount = removedCount + 1
            end
        end)
        if ClearLag_Config.UnloadChunks then TargetWorld:QueueUnloadUnusedChunks() end
    end)
    cRoot:Get():BroadcastChatSuccess("§8[§cClearLag§8] §aBaşarıyla §2" .. removedCount .. " §aobje dünyadan silindi!")
end

function HandleClearLagCommand(Split, Player)
    Player:SendMessageInfo("§8[§cClearLag§8] §eManuel temizlik başlatılıyor...")
    PerformClear()
    TimeUntilClear = ClearLag_Config.Interval 
    return true
end
