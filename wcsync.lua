-- wcsync.lua
-- Görev: Oyuncu veri senkronizasyonu (engine.py ile köprü)
-- engine.py, bu eklentinin LOG() çıktılarını yakalar ve oyuncu
-- dosyalarını hub proxy üzerinden indirip/yükler.

local ProxyURL = "http://127.0.0.1:{PORT}"

local function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function Initialize(Plugin)
    -- HATA #1 DÜZELTMESİ: Plugin adı "WCHub" değil "WCSync" olmalı.
    -- Aynı isim Cuberite'ın eklenti yükleyicisinde çakışmaya yol açar.
    Plugin:SetName("WCSync")
    Plugin:SetVersion(12)

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,   OnPlayerSpawned)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    -- HATA #2 DÜZELTMESİ: "wcreload" konsol komutu kaydedilmiyordu.
    -- engine.py, oyuncu dosyası indirildikten sonra Cuberite'ın stdin'ine
    -- "wcreload <oyuncu_adı>" yazar. Bu komut burada karşılanmazsa
    -- "Unknown command" hatası verilir ve envanter asla yüklenmez.
    -- BindConsoleCommand callback imzası: function(Split, EntireCommand)
    cPluginManager:BindConsoleCommand("wcreload", HandleWcReload, "Oyuncu verilerini yeniden yukler.")

    LOG("[WCSYNC] Oyuncu Veri Senkronizasyon Sistemi Aktif!")
    return true
end

-- ================================================================
-- HATA #3 DÜZELTMESİ: Bu iki hook tamamen eksikti.
-- engine.py'deki _pipe_output() bu LOG çıktılarını arar:
--   "WCSYNC_JOIN:<isim>:<uuid>"  → oyuncu dosyasını indir, sonra wcreload gönder
--   "WCSYNC_QUIT:<isim>:<uuid>"  → oyuncu dosyasını hub'a yükle
-- Bu LOG'lar olmadan oyuncu verisi HİÇ senkronize edilmez.
-- ================================================================

function OnPlayerSpawned(Player)
    local name = Player:GetName()
    local uuid = Player:GetUUID()
    -- engine.py bu LOG çıktısını yakalar: oyuncu dosyasını proxy'den indirir,
    -- /server/world/players/ altına yazar, ardından "wcreload <name>" gönderir.
    LOG("WCSYNC_JOIN:" .. name .. ":" .. uuid)
end

function OnPlayerDestroyed(Player)
    local name = Player:GetName()
    local uuid = Player:GetUUID()
    -- engine.py bu LOG çıktısını yakalar: oyuncu dosyasını proxy'ye yükler.
    LOG("WCSYNC_QUIT:" .. name .. ":" .. uuid)
end

-- ================================================================
-- wcreload: engine.py dosyayı diske yazdıktan sonra bu komutu çağırır.
-- Oyuncunun envanterini ve konumunu sunucudan yeniden yükler.
-- ================================================================
function HandleWcReload(CmdSplit, EntireCommand)
    local name = CmdSplit[2]
    if not name or name == "" then
        LOG("[WCSYNC] Kullanim: wcreload <oyuncu_adi>")
        return true
    end

    local found = false
    cRoot:Get():FindAndDoWithPlayer(name, function(Player)
        found = true
        -- Envanteri sunucudan yeniden gönder
        Player:GetInventory():SendWholeInventory(Player)
        -- Konumu sıfırla (görünmez zıplamayı önler)
        Player:TeleportToCoords(
            Player:GetPosX(),
            Player:GetPosY(),
            Player:GetPosZ()
        )
        LOG("[WCSYNC] " .. name .. " verisi basariyla yeniden yuklendi.")
    end)

    if not found then
        LOG("[WCSYNC] wcreload: '" .. name .. "' oyuncusu sunucuda bulunamadi.")
    end
    return true
end
