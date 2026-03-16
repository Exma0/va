-- wchub.lua
-- Görev: Sunucu listesini göstermek ve /hub /sunucu /oyuncu komutlarını yönetmek.

local ProxyURL = "http://127.0.0.1:{PORT}"

-- Cooldown tablosu: Oyuncu UUID → son SendServerList zamanı (saniye)
local LastSentTime = {}
local COOLDOWN_SEC = 2.0  -- 2 saniyede bir kez listeyi göster

local function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function Initialize(Plugin)
    Plugin:SetName("WCHub")
    Plugin:SetVersion(13)

    -- HATA DÜZELTMESİ: HOOK_EXECUTE_COMMAND YERİNE BindCommand kullan.
    -- HOOK_EXECUTE_COMMAND sadece zaten BindCommand ile kayıtlı komutlar
    -- çalıştırıldığında tetiklenir. Kayıtsız bir komut için Cuberite hook'u
    -- hiç çağırmadan doğrudan "unknown command" mesajı verir.
    -- Bu hatanın kanıtı log'daki 19:27:34 satırıdır:
    --   "Player Ray issued an unknown command: '/hub'"
    -- /kurt'un hiç bu mesajı vermemesinin nedeni ise yaver.lua'da
    -- BindCommand ile kayıtlı olmasıdır.
    cPluginManager:BindCommand("/hub",    "", HandleHubCommand, "Sunucu listesini goster.")
    cPluginManager:BindCommand("/sunucu", "", HandleHubCommand, "Sunucu listesini goster.")
    cPluginManager:BindCommand("/oyuncu", "", HandleHubCommand, "Sunucu listesini goster.")

    -- /wc_transfer: proxy tarafından işlenir; "unknown command" çıkmaması için kayıt
    cPluginManager:BindCommand("/wc_transfer", "", HandleTransferCommand, "Sunucu transferi.")

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED, OnPlayerSpawned)

    LOG("[HUB] WCHub Saf Sohbet Sistemi Aktif!")
    return true
end

function OnPlayerSpawned(Player)
    Player:GetWorld():ScheduleTask(20, function()
        SendServerList(Player)
    end)
end

function HandleHubCommand(CmdSplit, Player)
    SendServerList(Player)
    return true
end

function HandleTransferCommand(CmdSplit, Player)
    -- Gerçek transfer proxy'de pipe_c2s içinde yapılır.
    -- Burada sadece "unknown command" mesajını bastırıyoruz.
    return true
end

function SendServerList(Player)
    -- HATA DÜZELTMESİ: Cooldown (hız sınırı).
    -- Önceki kodda sınır yoktu; /hub'a her basışta yeni bir async HTTP
    -- isteği açılıyor ve panel defalarca gönderiliyordu.
    -- Log: 19:28:42-54 arasında tam 16 kez /hub tetiklendi.
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
                TargetPlayer:SendMessageInfo("§7  Hızlı geçiş için hedefe tıklayın:")
                TargetPlayer:SendMessageInfo(" ")

                local servers = Split(Body, ";")
                for _, srv in ipairs(servers) do
                    local parts = Split(srv, ":")
                    if #parts == 2 then
                        local msg = cCompositeChat()
                        msg:ParseText("  §8▪ §b" .. parts[1] .. " §7(Aktif: §e" .. parts[2] .. "§7)   ")
                        msg:AddRunCommandPart("§a§n[BAĞLAN]", "/wc_transfer " .. parts[1])
                        TargetPlayer:SendMessage(msg)
                    end
                end

                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo(" ")
            end)
        end,
        OnError = function(Err)
            -- Proxy bağlantı hatası — sessizce yut
        end
    })
end
