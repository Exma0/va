-- wchub.lua  v3
-- Görev: /hub /sunucu /oyuncu komutları + sunucu listesi GUI.

local ProxyURL = "http://127.0.0.1:{PORT}"

-- ─────────────────────────────────────────────────────────
-- HATA #1 DÜZELTMESİ: /hub ve /oyuncu "unknown command" veriyordu.
-- Neden: HOOK_EXECUTE_COMMAND yalnızca BindCommand ile kayıtlı
-- komutlar için tetiklenir. Kayıtsız komutlar için hook hiç
-- çalışmaz, Cuberite doğrudan "unknown command" verir.
-- Kanıt: Log 19:27:34 → "Player Ray issued an unknown command: '/hub'"
--        Log 19:27:39 → "Player Ray issued an unknown command: '/oyuncu'"
-- Düzeltme: Tüm komutlar BindCommand ile kayıt altına alındı.
-- ─────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────
-- HATA #2 DÜZELTMESİ: /hub spam → cooldown.
-- Önceki kodda hız sınırı yoktu; kısa sürede 16 kez /hub tetiklendi
-- (log 19:28:42-19:28:54), her çağrı yeni bir async HTTP isteği açıyor
-- ve panel defalarca gönderiliyordu.
-- ─────────────────────────────────────────────────────────
local LastSentTime = {}  -- UUID → os.time() damgası
local COOLDOWN_SEC = 2

local function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function Initialize(Plugin)
    Plugin:SetName("WCHub")
    Plugin:SetVersion(3)

    -- Tüm komutları BindCommand ile kayıt et (HOOK_EXECUTE_COMMAND kaldırıldı)
    cPluginManager:BindCommand("/hub",         "", HandleHubCommand,      "Sunucu listesini goster.")
    cPluginManager:BindCommand("/sunucu",      "", HandleHubCommand,      "Sunucu listesini goster.")
    cPluginManager:BindCommand("/oyuncu",      "", HandleHubCommand,      "Sunucu listesini goster.")
    -- /wc_transfer: proxy tarafından ÖNCE yakalanır, Cuberite'e ulaşmaz.
    -- Yine de kayıtlı olması "unknown command" logunu temizler.
    cPluginManager:BindCommand("/wc_transfer", "", HandleTransferCommand, "Sunucu transferi (proxy).")

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED, OnPlayerSpawned)

    LOG("[HUB] WCHub Saf Sohbet Sistemi Aktif!")
    return true
end

function OnPlayerSpawned(Player)
    -- Oyuncu giriş yaptığında 1 saniye bekle, sonra listeyi göster
    Player:GetWorld():ScheduleTask(20, function()
        SendServerList(Player)
    end)
end

-- BindCommand callback imzası: function(CmdSplit, Player) → bool
function HandleHubCommand(CmdSplit, Player)
    SendServerList(Player)
    return true
end

function HandleTransferCommand(CmdSplit, Player)
    -- Gerçek transfer proxy'de yapılır. Burada sadece logu temizleriz.
    return true
end

function SendServerList(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()

    -- Cooldown: aynı oyuncuya 2 saniyede bir listeden fazla gönderme
    if LastSentTime[UUID] and (now - LastSentTime[UUID]) < COOLDOWN_SEC then
        return
    end
    LastSentTime[UUID] = now

    local PlayerName = Player:GetName()
    local World      = Player:GetWorld()

    if not cUrlClient then return end

    cUrlClient:Get(ProxyURL .. "/api/servers", {
        OnSuccess = function(Body)
            World:ScheduleTask(0, function()
                -- Oyuncu hâlâ bağlı mı?
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

                local servers = Split(Body, ";")
                local count = 0
                for _, srv in ipairs(servers) do
                    local parts = Split(srv, ":")
                    if #parts == 2 then
                        count = count + 1
                        local msg = cCompositeChat()
                        msg:ParseText("  §8" .. count .. ". §b" .. parts[1] ..
                                      " §7(§e" .. parts[2] .. " §7oyuncu)   ")
                        msg:AddRunCommandPart("§a§n[BAĞLAN]", "/wc_transfer " .. parts[1])
                        TargetPlayer:SendMessage(msg)
                    end
                end

                if count == 0 then
                    TargetPlayer:SendMessageInfo("§c  Şu an aktif sunucu yok.")
                end

                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo(" ")
            end)
        end,
        OnError = function(Err)
            -- Sessizce yut; proxy geçici olarak ulaşılamıyor olabilir
        end
    })
end
