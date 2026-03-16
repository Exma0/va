-- wcsync.lua  v4
-- Görev: Oyuncu envanterini sunucular arası senkronize eder.
-- engine.py bu eklentinin LOG() çıktılarını yakalar:
--   WCSYNC_JOIN:<isim>:<uuid>  → dosyayı hub'dan çek, diske yaz, wcreload gönder
--   WCSYNC_QUIT:<isim>:<uuid>  → dosyayı hub'a yükle

local RecentJoins  = {}
local RecentQuits  = {}
local JOIN_DEDUP   = 5    -- saniye
local QUIT_DEDUP   = 3    -- saniye

local PLAYER_DIR = "/server/world/players/"

function Initialize(Plugin)
    Plugin:SetName("WCSync")
    Plugin:SetVersion(4)

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,   OnPlayerSpawned)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    cPluginManager:BindConsoleCommand("wcreload", HandleWcReload, "Oyuncu envanterini diskten yeniden yukler.")

    LOG("[WCSYNC] v4 - Sağlık/Açlık Değer Doğrulaması Eklendi!")
    return true
end

function OnPlayerSpawned(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()

    if RecentJoins[UUID] and (now - RecentJoins[UUID]) < JOIN_DEDUP then
        return
    end
    RecentJoins[UUID] = now

    local name = Player:GetName()
    LOG("WCSYNC_JOIN:" .. name .. ":" .. UUID)
end

function OnPlayerDestroyed(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()

    if RecentQuits[UUID] and (now - RecentQuits[UUID]) < QUIT_DEDUP then
        return
    end
    RecentQuits[UUID] = now

    local name = Player:GetName()
    LOG("WCSYNC_QUIT:" .. name .. ":" .. UUID)
end

function HandleWcReload(CmdSplit, EntireCommand)
    local name = CmdSplit[2]
    if not name or name == "" then
        LOG("[WCSYNC] Kullanim: wcreload <oyuncu_adi>")
        return true
    end

    local found = false
    cRoot:Get():FindAndDoWithPlayer(name, function(Player)
        found = true
        local UUID      = Player:GetUUID()
        local uuidClean = UUID:gsub("%-", "")

        local paths = {
            PLAYER_DIR .. UUID      .. ".json",
            PLAYER_DIR .. uuidClean .. ".json",
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

        if not content or content == "" then
            LOG("[WCSYNC] " .. name .. " dosyasi bulunamadi, envanter yuklenemedi.")
            return
        end

        local data, err = cJson:Parse(content)
        if not data then
            LOG("[WCSYNC] " .. name .. " JSON parse hatasi: " .. tostring(err))
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

        -- DÜZELTME #1: Sağlık ve açlık değerleri doğrulanmadan uygulanıyordu.
        -- JSON dosyasında geçersiz (negatif, sıfır veya aşırı yüksek) değer
        -- varsa oyuncu anında ölüyor veya açlık barı bozuluyordu.
        -- Sağlık en az 1, en fazla MaxHealth; açlık 0–20 arasına sıkıştırıldı.
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

        LOG("[WCSYNC] " .. name .. " verisi basariyla yuklendi.")
    end)

    if not found then
        LOG("[WCSYNC] wcreload: '" .. name .. "' oyuncusu sunucuda bulunamadi.")
    end
    return true
end
