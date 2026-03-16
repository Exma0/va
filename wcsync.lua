-- wcsync.lua  v3
-- Görev: Oyuncu envanterini sunucular arası senkronize eder.
-- engine.py bu eklentinin LOG() çıktılarını yakalar:
--   WCSYNC_JOIN:<isim>:<uuid>  → dosyayı hub'dan çek, diske yaz, wcreload gönder
--   WCSYNC_QUIT:<isim>:<uuid>  → dosyayı hub'a yükle

-- ─────────────────────────────────────────────────────────
-- HATA #1 DÜZELTMESİ: Çift WCSYNC_JOIN
-- Log'da aynı oyuncu için iki kez WCSYNC_JOIN tetikleniyor
-- (19:29:21 ve 19:29:22). Cuberite bazı durumlarda
-- HOOK_PLAYER_SPAWNED'ı iki kez ateşler (spawn + chunk yükü).
-- Çözüm: son JOIN zamanını kaydet, 5 sn içinde tekrar gelirse yoksay.
-- ─────────────────────────────────────────────────────────
local RecentJoins  = {}   -- UUID → os.time() damgası
local RecentQuits  = {}   -- UUID → os.time() damgası
local JOIN_DEDUP   = 5    -- saniye
local QUIT_DEDUP   = 3    -- saniye

-- Cuberite'ın gameserver modunda oyuncu dosyalarını kaydettiği dizin
-- (engine.py: persistent_world = "/server/world" for gameserver mode)
local PLAYER_DIR = "/server/world/players/"

function Initialize(Plugin)
    Plugin:SetName("WCSync")
    Plugin:SetVersion(3)

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,   OnPlayerSpawned)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    -- HATA #2 DÜZELTMESİ: wcreload konsol komutu kayıtlı değildi.
    -- engine.py dosyayı diske yazdıktan sonra "wcreload <isim>" gönderir.
    -- Kayıtsız olduğu için Cuberite "unknown command" veriyordu.
    cPluginManager:BindConsoleCommand("wcreload", HandleWcReload, "Oyuncu envanterini diskten yeniden yukler.")

    LOG("[WCSYNC] Oyuncu Veri Senkronizasyon Sistemi Aktif!")
    return true
end

function OnPlayerSpawned(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()

    -- Çift tetiklenmeyi önle
    if RecentJoins[UUID] and (now - RecentJoins[UUID]) < JOIN_DEDUP then
        return
    end
    RecentJoins[UUID] = now

    local name = Player:GetName()
    -- engine.py bu satırı yakalar: oyuncu dosyasını hub'dan çeker,
    -- PLAYER_DIR altına yazar ve "wcreload <name>" komutunu gönderir.
    LOG("WCSYNC_JOIN:" .. name .. ":" .. UUID)
end

function OnPlayerDestroyed(Player)
    local UUID = Player:GetUUID()
    local now  = os.time()

    -- Çift tetiklenmeyi önle
    if RecentQuits[UUID] and (now - RecentQuits[UUID]) < QUIT_DEDUP then
        return
    end
    RecentQuits[UUID] = now

    local name = Player:GetName()
    -- engine.py bu satırı yakalar: oyuncu dosyasını hub'a yükler.
    LOG("WCSYNC_QUIT:" .. name .. ":" .. UUID)
end

-- ─────────────────────────────────────────────────────────
-- HandleWcReload: engine.py dosyayı diske yazdıktan sonra bu
-- konsol komutunu çağırır. Oyuncu o an zaten varsayılan (boş)
-- envanter ile oyunda; biz JSON dosyasını okuyup envanteri
-- manuel olarak uyguluyoruz.
--
-- Cuberite player JSON formatı (Slot numaraları):
--   0-3  : Zırh (helmet=0, chestplate=1, leggings=2, boots=3)
--   9-17 : Hotbar
--   18-44: Ana envanter
-- ─────────────────────────────────────────────────────────
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

        -- Önce UUID ile, bulamazsa dash-free UUID ile dene
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

        -- JSON dosyasını ayrıştır
        local data, err = cJson:Parse(content)
        if not data then
            LOG("[WCSYNC] " .. name .. " JSON parse hatasi: " .. tostring(err))
            return
        end

        -- Envanteri sıfırla ve dosyadan yükle
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

        -- Sağlık ve açlık durumunu da yükle
        if data["Health"] then
            pcall(function() Player:SetHealth(tonumber(data["Health"])) end)
        end
        if data["FoodLevel"] then
            pcall(function() Player:SetFoodLevel(tonumber(data["FoodLevel"])) end)
        end

        LOG("[WCSYNC] " .. name .. " verisi basariyla yuklendi.")
    end)

    if not found then
        LOG("[WCSYNC] wcreload: '" .. name .. "' oyuncusu sunucuda bulunamadi.")
    end
    return true
end
