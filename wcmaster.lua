-- ╔══════════════════════════════════════════════════════╗
-- ║        WC NETWORK ULTIMATE MASTER PLUGIN v1.5        ║
-- ║  Sohbet, TP, Bungee, SafeSpawn, WCSync, ClearLag    ║
-- ║  BUG FIX: Hafıza sızıntısı, entity iterasyon,       ║
-- ║           WriteJavaString overflow, TPA tablo hatası,║
-- ║           SendPluginMessage ClientHandle Hatası     ║
-- ╚══════════════════════════════════════════════════════╝

-- ========================================================
-- YAPILANDIRMA (CONFIG)
-- ========================================================

-- [SafeSpawn]
local E_BLOCK_WATER            = 8
local E_BLOCK_STATIONARY_WATER = 9
local E_BLOCK_LAVA             = 10
local E_BLOCK_STATIONARY_LAVA  = 11

-- [ClearLag]
local ClearLag_Config = {
    Interval         = 300,
    Warnings         = {60, 30, 10, 5, 3, 2, 1},
    ClearItems       = true,
    ClearExpOrbs     = true,
    ClearProjectiles = true,
    UnloadChunks     = true
}
local TimeUntilClear = ClearLag_Config.Interval

-- [Otomatik Sohbet Temizleyici]
local ChatClear_Config = {
    Enabled  = true,
    Interval = 600
}
local TimeUntilChatClear = ChatClear_Config.Interval

-- [NetworkTP]
local TpaRequests       = {}
local ValidServers      = {}
local HasFetchedServers = false

-- [WCHub]
local ProxyURL          = "http://127.0.0.1:{PORT}"
local HubLastSentTime   = {}
local HUB_COOLDOWN_SEC  = 2

-- [WCSync]
local SyncRecentJoins   = {}
local SyncRecentQuits   = {}
local JOIN_DEDUP        = 5
local QUIT_DEDUP        = 3
local SYNC_CLEANUP_INTERVAL = 300

-- [Sohbet]
local LastMsg = {}

-- ========================================================
-- HATA YÖNETİMİ
-- ========================================================
function BroadcastError(kaynak, hata)
    local kisaHata = string.sub(tostring(hata), 1, 150)
    local mesaj    = "§8[§4SİSTEM HATASI§8] §7" .. kaynak .. " -> §c" .. kisaHata
    cRoot:Get():BroadcastChat(mesaj)
    LOGWARNING("[WCMaster HATA] Kaynak: " .. kaynak .. " | Detay: " .. tostring(hata))
end

function SafeTask(kaynak, func)
    return function(...)
        local ok, err = pcall(func, ...)
        if not ok then BroadcastError(kaynak, err) end
    end
end

local function SafeWrap(funcName, sourceName)
    local originalFunc = _G[funcName]
    if type(originalFunc) == "function" then
        _G[funcName] = function(...)
            local results = {pcall(originalFunc, ...)}
            if not results[1] then
                BroadcastError(sourceName, results[2])
                return true
            end
            return unpack(results, 2)
        end
    end
end

-- ========================================================
-- BAŞLATICI (INITIALIZE)
-- ========================================================
function Initialize(Plugin)
    Plugin:SetName("WCMasterPlugin")
    Plugin:SetVersion(5)

    local toWrap = {
        {"HandleYardimCommand",    "/yardim komutu"},
        {"HandleMsgCommand",       "/msg komutu"},
        {"HandleReplyCommand",     "/r komutu"},
        {"HandleZarCommand",       "/zar komutu"},
        {"HandleKurallarCommand",  "/kurallar komutu"},
        {"HandleClearChatCommand", "/sil komutu"},
        {"HandleTpCommand",        "/tp komutu"},
        {"HandleTpaCommand",       "/tpa komutu"},
        {"HandleTpAcceptCommand",  "/tpaccept komutu"},
        {"HandleTpDenyCommand",    "/tpdeny komutu"},
        {"HandleHubCommand",       "/hub komutu"},
        {"HandleTransferCommand",  "Hub Transfer Sistemi"},
        {"HandleClearLagCommand",  "/clearlag komutu"},
        {"HandleWcReload",         "wcreload sistemi"},
        {"Global_OnPlayerSpawned",   "Oyuncu Spawn Eventi"},
        {"Global_OnPlayerDestroyed", "Oyuncu Çıkış Eventi"},
        {"Global_OnPlayerJoined",    "Oyuncu Katılma Eventi"},
        {"Global_OnPluginMessage",   "BungeeCord Mesaj Eventi"},
        {"TimerTick_ClearLag",       "ClearLag Döngüsü"},
        {"TimerTick_ClearChat",      "Sohbet Temizleyici Döngüsü"},
        {"TimerTick_SyncCleanup",    "Senkronizasyon Temizleyici"},
    }
    for _, pair in ipairs(toWrap) do
        SafeWrap(pair[1], pair[2])
    end

    local PM = cRoot:Get():GetPluginManager()
    PM:BindCommand("/yardim",    "", HandleYardimCommand,   "Komut listesi.")
    PM:BindCommand("/komutlar",  "", HandleYardimCommand,   "Komut listesi.")
    PM:BindCommand("/msg",       "", HandleMsgCommand,      "Özel mesaj gönder.")
    PM:BindCommand("/r",         "", HandleReplyCommand,    "Son mesaja yanıt ver.")
    PM:BindCommand("/zar",       "", HandleZarCommand,      "Zar at.")
    PM:BindCommand("/kurallar",  "", HandleKurallarCommand, "Kuralları göster.")
    PM:BindCommand("/sil",       "chat.admin", HandleClearChatCommand, "Sohbeti temizle.")
    PM:BindCommand("/cc",        "chat.admin", HandleClearChatCommand, "Sohbeti temizle.")
    PM:BindCommand("/tp",        "", HandleTpCommand,       "Sunucuya geçiş.")
    PM:BindCommand("/tpa",       "", HandleTpaCommand,      "Işınlanma isteği gönder.")
    PM:BindCommand("/tpaccept",  "", HandleTpAcceptCommand, "Isteği kabul et.")
    PM:BindCommand("/tpdeny",    "", HandleTpDenyCommand,   "Isteği reddet.")
    PM:BindCommand("/hub",       "", HandleHubCommand,      "Sunucu listesi.")
    PM:BindCommand("/sunucu",    "", HandleHubCommand,      "Sunucu listesi.")
    PM:BindCommand("/oyuncu",    "", HandleHubCommand,      "Sunucu listesi.")
    PM:BindCommand("/wc_transfer","", HandleTransferCommand, "Sunucu transferi.")
    PM:BindCommand("/clearlag",  "clearlag.admin", HandleClearLagCommand, "Lag temizle.")
    PM:BindConsoleCommand("wcreload", HandleWcReload, "Oyuncu envanterini yeniden yükle.")

    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,   Global_OnPlayerSpawned)
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, Global_OnPlayerDestroyed)
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_JOINED,    Global_OnPlayerJoined)
    cPluginManager.AddHook(cPluginManager.HOOK_PLUGIN_MESSAGE,   Global_OnPluginMessage)

    cRoot:Get():GetDefaultWorld():ScheduleTask(20, TimerTick_ClearLag)
    if ChatClear_Config.Enabled then
        cRoot:Get():GetDefaultWorld():ScheduleTask(20, TimerTick_ClearChat)
    end
    cRoot:Get():GetDefaultWorld():ScheduleTask(
        SYNC_CLEANUP_INTERVAL * 20, TimerTick_SyncCleanup
    )

    LOG("[WCMaster] v1.5 - Tüm sistemler aktif.")
    return true
end

-- ========================================================
-- MERKEZİ HOOK FONKSİYONLARI
-- ========================================================
function Global_OnPlayerSpawned(Player)
    SafeSpawn_CheckLand(Player)
    WCHub_ShowMenu(Player)
    WCSync_JoinNotify(Player)
end

function Global_OnPlayerDestroyed(Player)
    local name = Player:GetName()
    LastMsg[name] = nil
    NetworkTP_CleanRequests(Player)
    HubLastSentTime[Player:GetUUID()] = nil
    WCSync_QuitNotify(Player)
end

function Global_OnPlayerJoined(Player)
    if not HasFetchedServers then
        -- DÜZELTME: BungeeCord mesajları doğrudan Player üzerinden değil, ClientHandle üzerinden gönderilmeli.
        local client = Player:GetClientHandle()
        if client then
            client:SendPluginMessage("BungeeCord", WriteJavaString("GetServers"))
        end
    end
end

function Global_OnPluginMessage(ClientHandle, Channel, Message)
    if Channel ~= "BungeeCord" then return false end
    local subchannel, offset = ReadJavaString(Message, 1)
    if subchannel == "GetServers" then
        local serverListStr = ReadJavaString(Message, offset)
        if serverListStr and serverListStr ~= "" then
            ValidServers = {}
            for server in string.gmatch(serverListStr, "([^,]+)") do
                server = string.match(server, "^%s*(.-)%s*$")
                if server ~= "" then
                    ValidServers[string.lower(server)] = true
                end
            end
            HasFetchedServers = true
            LOG("[WCMaster] BungeeCord sunucuları: " .. serverListStr)
        end
    end
    return false
end

-- ========================================================
-- YARDIMCI FONKSİYONLAR
-- ========================================================
local function Hub_Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^" .. sep .. "]+)") do
        table.insert(res, w)
    end
    return res
end

function WriteJavaString(str)
    local len = #str
    if len > 65535 then
        str = string.sub(str, 1, 65535)
        len = 65535
    end
    return string.char(math.floor(len / 256), len % 256) .. str
end

function ReadJavaString(msg, offset)
    if not msg or offset + 1 > #msg then return nil, offset end
    local len = string.byte(msg, offset) * 256 + string.byte(msg, offset + 1)
    offset = offset + 2
    if offset + len - 1 > #msg then return nil, offset end
    return string.sub(msg, offset, offset + len - 1), offset + len
end

-- ========================================================
-- PERİYODİK SYNC BELLEK TEMİZLEYİCİ
-- ========================================================
function TimerTick_SyncCleanup(World)
    local now     = os.time()
    local maxAge  = math.max(JOIN_DEDUP, QUIT_DEDUP) + 10

    local removeJoin = {}
    for uuid, ts in pairs(SyncRecentJoins) do
        if (now - ts) > maxAge then table.insert(removeJoin, uuid) end
    end
    for _, uuid in ipairs(removeJoin) do SyncRecentJoins[uuid] = nil end

    local removeQuit = {}
    for uuid, ts in pairs(SyncRecentQuits) do
        if (now - ts) > maxAge then table.insert(removeQuit, uuid) end
    end
    for _, uuid in ipairs(removeQuit) do SyncRecentQuits[uuid] = nil end

    World:ScheduleTask(SYNC_CLEANUP_INTERVAL * 20, TimerTick_SyncCleanup)
end

-- ========================================================
-- OTOMATİK SOHBET TEMİZLEYİCİ
-- ========================================================
function TimerTick_ClearChat(World)
    TimeUntilChatClear = TimeUntilChatClear - 1
    if TimeUntilChatClear <= 0 then
        PerformChatClear("Otomatik Sistem")
        TimeUntilChatClear = ChatClear_Config.Interval
    end
    World:ScheduleTask(20, TimerTick_ClearChat)
end

function PerformChatClear(SenderName)
    for i = 1, 100 do cRoot:Get():BroadcastChat(" ") end
    cRoot:Get():BroadcastChatInfo("§8§m                                     ")
    cRoot:Get():BroadcastChatSuccess(
        "§8[§bSistem§8] §aSohbet §e" .. SenderName .. " §atarafından temizlendi!"
    )
    cRoot:Get():BroadcastChatInfo("§8§m                                     ")
end

function HandleClearChatCommand(Split, Player)
    PerformChatClear(Player:GetName())
    TimeUntilChatClear = ChatClear_Config.Interval
    return true
end

-- ========================================================
-- SOHBET VE YARDIM
-- ========================================================
function HandleYardimCommand(Split, Player)
    Player:SendMessage(" ")
    Player:SendMessage("§8§m                                     ")
    Player:SendMessage("§3§l      ♦ WC NETWORK KOMUTLARI ♦      ")
    Player:SendMessage("§8§m                                     ")
    Player:SendMessage("§a/hub §7veya §a/sunucu §f- Sunucu listesi.")
    Player:SendMessage("§a/tp <sunucu> §f- Başka sunucuya geçiş.")
    Player:SendMessage("§a/tpa <oyuncu> §f- Işınlanma isteği.")
    Player:SendMessage("§a/tpaccept §f- Isteği kabul et.")
    Player:SendMessage("§a/tpdeny §f- Isteği reddet.")
    Player:SendMessage("§e/msg <oyuncu> <mesaj> §f- Özel mesaj.")
    Player:SendMessage("§e/r <mesaj> §f- Son mesaja yanıt.")
    Player:SendMessage("§e/zar §f- 1-100 zar.")
    Player:SendMessage("§e/kurallar §f- Sunucu kuralları.")
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
    local Message    = table.concat(Split, " ", 3)
    local SenderName = Player:GetName()

    if string.lower(TargetName) == string.lower(SenderName) then
        Player:SendMessageFailure("§cKendine mesaj gönderemezsin!")
        return true
    end

    local Found = false
    cRoot:Get():FindAndDoWithPlayer(TargetName, function(TP)
        Found = true
        local RealName = TP:GetName()
        Player:SendMessage("§d[Ben → " .. RealName .. "] §f" .. Message)
        TP:SendMessage("§d[" .. SenderName .. " → Ben] §f" .. Message)
        LastMsg[SenderName] = RealName
        LastMsg[RealName]   = SenderName
    end)

    if not Found then
        Player:SendMessageFailure("§c" .. TargetName .. " §abulunamadı.")
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
        Player:SendMessageFailure("§cYanıt verecek kimse yok.")
        return true
    end
    local Message = table.concat(Split, " ", 2)
    local Found   = false
    cRoot:Get():FindAndDoWithPlayer(TargetName, function(TP)
        Found = true
        Player:SendMessage("§d[Ben → " .. TargetName .. "] §f" .. Message)
        TP:SendMessage("§d[" .. SenderName .. " → Ben] §f" .. Message)
        LastMsg[SenderName] = TargetName
        LastMsg[TargetName] = SenderName
    end)
    if not Found then
        Player:SendMessageFailure("§c" .. TargetName .. " §aşu an çevrimdışı.")
    end
    return true
end

function HandleZarCommand(Split, Player)
    local zar = math.random(1, 100)
    cRoot:Get():BroadcastChat(
        "§e" .. Player:GetName() .. " §7zar attı: §a" .. zar
    )
    return true
end

function HandleKurallarCommand(Split, Player)
    Player:SendMessage("§8§m                                     ")
    Player:SendMessage("§c§l  SUNUCU KURALLARI")
    Player:SendMessage("§71. Küfür, hile ve 3. parti yazılım yasaktır.")
    Player:SendMessage("§72. Diğer oyunculara ve yetkililere saygılı olun.")
    Player:SendMessage("§73. Oyun açığı kullanmak ban sebebidir.")
    Player:SendMessage("§8§m                                     ")
    return true
end

-- ========================================================
-- SAFESPAWN
-- ========================================================
local function IsWater(b) return b == E_BLOCK_WATER or b == E_BLOCK_STATIONARY_WATER end
local function IsLava(b)  return b == E_BLOCK_LAVA  or b == E_BLOCK_STATIONARY_LAVA  end

local function FindSafeLand(Player, World, startX, startZ, attempt)
    if attempt > 30 then
        Player:SendMessageFailure("§cGüvenli kara bulunamadı.")
        return
    end
    local searchX = startX + math.random(-800, 800)
    local searchZ = startZ + math.random(-800, 800)
    local chunkX  = math.floor(searchX / 16)
    local chunkZ  = math.floor(searchZ / 16)

    World:ChunkStay({{chunkX, chunkZ}}, nil,
        SafeTask("SafeSpawn Tarama", function()
            local y = World:GetHeight(searchX, searchZ)
            if y > 0 then
                local blockSurface = World:GetBlock(searchX, y - 1, searchZ)
                if not IsWater(blockSurface) and not IsLava(blockSurface)
                        and blockSurface ~= 0 then
                    Player:TeleportToCoords(searchX + 0.5, y + 1.0, searchZ + 0.5)
                    pcall(function()
                        Player:SetBedPos(Vector3i(
                            math.floor(searchX), math.floor(y + 1), math.floor(searchZ)
                        ))
                    end)
                    Player:SendMessageSuccess("§aKuru karaya ulaştın! Doğuş noktası güncellendi.")
                else
                    FindSafeLand(Player, World, startX, startZ, attempt + 1)
                end
            else
                FindSafeLand(Player, World, startX, startZ, attempt + 1)
            end
        end)
    )
end

function SafeSpawn_CheckLand(Player)
    local World = Player:GetWorld()
    local UUID  = Player:GetUUID()
    World:ScheduleTask(10, SafeTask("SafeSpawn Kontrol", function()
        cRoot:Get():DoWithPlayerByUUID(UUID, function(P)
            local px = math.floor(P:GetPosX())
            local py = math.floor(P:GetPosY())
            local pz = math.floor(P:GetPosZ())
            if IsWater(World:GetBlock(px, py, pz))
                    or IsWater(World:GetBlock(px, py - 1, pz)) then
                P:SendMessageWarning("§eOkyanusta doğdun! Güvenli karaya taşınıyorsun...")
                FindSafeLand(P, World, px, pz, 1)
            end
        end)
    end))
end

-- ========================================================
-- WCHUB (SUNUCU LİSTESİ)
-- ========================================================
function WCHub_ShowMenu(Player)
    Player:GetWorld():ScheduleTask(
        20, SafeTask("Hub Menü", function() SendServerList(Player) end)
    )
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
    if HubLastSentTime[UUID] and (now - HubLastSentTime[UUID]) < HUB_COOLDOWN_SEC then
        return
    end
    HubLastSentTime[UUID] = now

    local PlayerName = Player:GetName()
    local World      = Player:GetWorld()
    if not cUrlClient then return end

    cUrlClient:Get(ProxyURL .. "/api/servers", {
        OnSuccess = SafeTask("Sunucu Listesi", function(Body)
            World:ScheduleTask(0, SafeTask("Sunucu Listesi Ekran", function()
                local TargetPlayer = nil
                cRoot:Get():FindAndDoWithPlayer(PlayerName, function(P)
                    TargetPlayer = P
                end)
                if not TargetPlayer or not Body or Body == "" then return end

                TargetPlayer:SendMessageInfo(" ")
                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo("§3§l      ♦ WC NETWORK AĞI ♦      ")
                TargetPlayer:SendMessageInfo("§7  Geçiş için §a[BAĞLAN]§7'a tıklayın:")
                TargetPlayer:SendMessageInfo(" ")

                local servers = Hub_Split(Body, ";")
                local count   = 0
                for _, srv in ipairs(servers) do
                    local parts = Hub_Split(srv, ":")
                    if #parts == 2 then
                        count = count + 1
                        local msg = cCompositeChat()
                        msg:ParseText(
                            "  §8" .. count .. ". §b" .. parts[1] ..
                            " §7(§e" .. parts[2] .. " §7oyuncu)   "
                        )
                        msg:AddRunCommandPart("§a§n[BAĞLAN]", "/wc_transfer " .. parts[1])
                        TargetPlayer:SendMessage(msg)
                    end
                end

                if count == 0 then
                    TargetPlayer:SendMessageInfo("§c  Şu an aktif sunucu yok.")
                end
                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo(" ")
            end))
        end),
        OnError = function(Err)
        end
    })
end

-- ========================================================
-- NETWORK TP & TPA
-- ========================================================
function NetworkTP_CleanRequests(Player)
    local leavingName = Player:GetName()

    if TpaRequests[leavingName] then
        local senderName = TpaRequests[leavingName]
        TpaRequests[leavingName] = nil
        cRoot:Get():FindAndDoWithPlayer(senderName, function(SP)
            SP:SendMessageFailure(
                "§c" .. leavingName .. " §esunucudan ayrıldı; isteğin iptal edildi."
            )
        end)
    end

    local toRemove = {}
    for targetName, senderName in pairs(TpaRequests) do
        if senderName == leavingName then
            table.insert(toRemove, targetName)
        end
    end
    for _, targetName in ipairs(toRemove) do
        TpaRequests[targetName] = nil
    end
end

function HandleTpCommand(Split, Player)
    if #Split < 2 then
        Player:SendMessageInfo("§eKullanım: §7/tp <SunucuAdı>")
        return true
    end
    local target = string.lower(Split[2])
    if ValidServers[target] or not HasFetchedServers then
        Player:SendMessageSuccess(
            "§a" .. string.upper(target) .. " §esunucusuna bağlanılıyor..."
        )
        
        -- DÜZELTME: BungeeCord mesajları doğrudan Player üzerinden değil, ClientHandle üzerinden gönderilmeli.
        local client = Player:GetClientHandle()
        if client then
            client:SendPluginMessage(
                "BungeeCord",
                WriteJavaString("Connect") .. WriteJavaString(target)
            )
        end
    else
        Player:SendMessageWarning(
            "§cAğda '" .. target .. "' adında bir sunucu bulunamadı!"
        )
    end
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

    local isFound = false
    cRoot:Get():FindAndDoWithPlayer(targetName, function(TP)
        isFound = true
        local tName = TP:GetName()
        if TpaRequests[tName] and TpaRequests[tName] ~= senderName then
            cRoot:Get():FindAndDoWithPlayer(TpaRequests[tName], function(OldSender)
                OldSender:SendMessageFailure(
                    "§c" .. tName .. " §eyeni bir istek aldı; senin isteğin iptal edildi."
                )
            end)
        end
        TpaRequests[tName] = senderName
        Player:SendMessageSuccess("§a" .. tName .. " §eadlı oyuncuya istek gönderildi.")
        TP:SendMessageSuccess("§6" .. senderName .. " §esana ışınlanmak istiyor!")
        TP:SendMessageInfo("§7Kabul: §a/tpaccept §7| Reddet: §c/tpdeny")
    end)

    if not isFound then
        Player:SendMessageFailure("§cOyuncu bulunamadı!")
    end
    return true
end

function HandleTpAcceptCommand(Split, Player)
    local targetName = Player:GetName()
    local senderName = TpaRequests[targetName]
    if not senderName then
        Player:SendMessageFailure("§cSana bekleyen bir ışınlanma isteği yok.")
        return true
    end
    TpaRequests[targetName] = nil
    local isFound = false
    cRoot:Get():FindAndDoWithPlayer(senderName, function(SP)
        isFound = true
        SP:TeleportToEntity(Player)
        SP:SendMessageSuccess("§a" .. targetName .. " §eisteği kabul etti! Işınlandın.")
        Player:SendMessageSuccess("§a" .. senderName .. " §eyanına ışınlandı.")
    end)
    if not isFound then
        Player:SendMessageFailure("§cIsteği atan oyuncu şu an çevrimdışı.")
    end
    return true
end

function HandleTpDenyCommand(Split, Player)
    local targetName = Player:GetName()
    local senderName = TpaRequests[targetName]
    if not senderName then
        Player:SendMessageFailure("§cSana bekleyen bir ışınlanma isteği yok.")
        return true
    end
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
    if SyncRecentJoins[UUID] and (now - SyncRecentJoins[UUID]) < JOIN_DEDUP then
        return
    end
    SyncRecentJoins[UUID] = now
    LOG("WCSYNC_JOIN:" .. Player:GetName() .. ":" .. UUID)
end

function WCSync_QuitNotify(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()
    if SyncRecentQuits[UUID] and (now - SyncRecentQuits[UUID]) < QUIT_DEDUP then
        return
    end
    SyncRecentQuits[UUID] = now
    LOG("WCSYNC_QUIT:" .. Player:GetName() .. ":" .. UUID)
end

function HandleWcReload(CmdSplit, EntireCommand)
    local name = CmdSplit[2]
    if not name or name == "" then return true end

    cRoot:Get():FindAndDoWithPlayer(name, function(Player)
        local UUID      = Player:GetUUID()
        local uuidClean = UUID:gsub("%-", "")
        
        -- DÜZELTME: Hem gameserver (/server/) hem de Hub modunun (/data/) dosyalarını tara.
        local paths     = {
            "/server/world/players/" .. UUID .. ".json",
            "/server/world/players/" .. uuidClean .. ".json",
            "/data/world/players/" .. UUID .. ".json",
            "/data/world/players/" .. uuidClean .. ".json"
        }
        local content = nil

        for _, path in ipairs(paths) do
            local f = io.open(path, "r")
            if f then
                content = f:read("*all")
                f:close()
                break
            end
        end

        if not content or content == "" then return end

        local ok, data = pcall(function()
            return cJson:Parse(content)
        end)
        if not ok or not data then
            LOGWARNING("[WCMaster] wcreload: JSON parse hatası (" .. name .. ")")
            return
        end

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
                    pcall(function()
                        inv:SetSlot(slot, cItem(itemID, count, damage))
                    end)
                end
            end
        end

        if data["Health"] then
            local hp = math.max(1, math.min(
                tonumber(data["Health"]) or 20,
                Player:GetMaxHealth()
            ))
            pcall(function() Player:SetHealth(hp) end)
        end
        if data["FoodLevel"] then
            local food = math.max(0, math.min(
                tonumber(data["FoodLevel"]) or 20, 20
            ))
            pcall(function() Player:SetFoodLevel(food) end)
        end
    end)
    return true
end

-- ========================================================
-- CLEARLAG
-- ========================================================
function TimerTick_ClearLag(World)
    TimeUntilClear = TimeUntilClear - 1

    for _, warnTime in ipairs(ClearLag_Config.Warnings) do
        if TimeUntilClear == warnTime then
            cRoot:Get():BroadcastChatWarning(
                "§8[§cClearLag§8] §eEşyalar §c" .. warnTime .. " §esaniye içinde silinecek!"
            )
        end
    end

    if TimeUntilClear <= 0 then
        PerformClear()
        TimeUntilClear = ClearLag_Config.Interval
    end
    World:ScheduleTask(20, TimerTick_ClearLag)
end

function PerformClear()
    local toDestroy    = {}
    local removedCount = 0

    cRoot:Get():ForEachWorld(function(TargetWorld)
        TargetWorld:ForEachEntity(function(Entity)
            local eType = Entity:GetEntityType()
            if (ClearLag_Config.ClearItems and eType == cEntity.etItem)
                    or (ClearLag_Config.ClearExpOrbs and eType == cEntity.etExpOrb)
                    or (ClearLag_Config.ClearProjectiles and eType == cEntity.etProjectile) then
                table.insert(toDestroy, Entity)
            end
        end)
        if ClearLag_Config.UnloadChunks then
            TargetWorld:QueueUnloadUnusedChunks()
        end
    end)

    for _, entity in ipairs(toDestroy) do
        pcall(function() entity:Destroy() end)
        removedCount = removedCount + 1
    end

    cRoot:Get():BroadcastChatSuccess(
        "§8[§cClearLag§8] §a" .. removedCount .. " §aobje dünyadan silindi!"
    )
end

function HandleClearLagCommand(Split, Player)
    Player:SendMessageInfo("§8[§cClearLag§8] §eManuel temizlik başlatılıyor...")
    PerformClear()
    TimeUntilClear = ClearLag_Config.Interval
    return true
end
