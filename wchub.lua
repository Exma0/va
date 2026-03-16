-- wchub.lua  v4
-- Görev: /hub /sunucu /oyuncu komutları + sunucu listesi GUI.

local ProxyURL = "http://127.0.0.1:{PORT}"

local LastSentTime = {}  -- UUID → os.time() damgası
local COOLDOWN_SEC = 2

local function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function Initialize(Plugin)
    Plugin:SetName("WCHub")
    Plugin:SetVersion(4)

    cPluginManager:BindCommand("/hub",         "", HandleHubCommand,      "Sunucu listesini goster.")
    cPluginManager:BindCommand("/sunucu",      "", HandleHubCommand,      "Sunucu listesini goster.")
    cPluginManager:BindCommand("/oyuncu",      "", HandleHubCommand,      "Sunucu listesini goster.")
    cPluginManager:BindCommand("/wc_transfer", "", HandleTransferCommand, "Sunucu transferi (proxy).")

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,   OnPlayerSpawned)

    -- DÜZELTME #1: LastSentTime tablosunda UUID girişleri birikiyordu.
    -- Oyuncu ayrıldığında kaydı temizle (bellek sızıntısını önler).
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    LOG("[HUB] WCHub v4 - Bellek Sızıntısı Giderildi!")
    return true
end

function OnPlayerSpawned(Player)
    Player:GetWorld():ScheduleTask(20, function()
        SendServerList(Player)
    end)
end

-- DÜZELTME #1: Ayrılan oyuncunun cooldown kaydını temizle.
function OnPlayerDestroyed(Player)
    LastSentTime[Player:GetUUID()] = nil
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
