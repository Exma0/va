-- ╔══════════════════════════════════════════════════════╗
-- ║        CLEARLAG ADVANCED - Otomatik Lag Temizleyici  ║
-- ║        Eşya Silme • Chunk Boşaltma • Geri Sayım      ║
-- ╚══════════════════════════════════════════════════════╝

-- ══════════════════════════════════════════════════════
--  AYARLAR (Burayı dilediğin gibi değiştirebilirsin)
-- ══════════════════════════════════════════════════════
local Config = {
    Interval       = 300, -- Kaç saniyede bir temizlik yapılsın? (300 saniye = 5 dakika)
    Warnings       = {60, 30, 10, 5, 3, 2, 1}, -- Temizlik öncesi hangi saniyelerde uyarı verilsin?
    
    ClearItems     = true,  -- Yerdeki eşyalar silinsin mi?
    ClearExpOrbs   = true,  -- Yerdeki XP küreleri silinsin mi?
    ClearProjectiles= true, -- Yere düşen ok, kartopu vb. silinsin mi?
    
    UnloadChunks   = true   -- Kullanılmayan harita parçaları RAM'den temizlensin mi?
}

local TimeUntilClear = Config.Interval

-- ══════════════════════════════════════════════════════
--  BAŞLANGIÇ
-- ══════════════════════════════════════════════════════
function Initialize(Plugin)
    Plugin:SetName("ClearLagAdvanced")
    Plugin:SetVersion(1)

    -- Yönetici komutu ekle
    cPluginManager:BindCommand("/clearlag", "clearlag.admin", HandleClearLagCommand, "Yerlerdeki eşyaları siler ve lagı azaltır.")

    -- Zamanlayıcıyı başlat (Saniyede 1 kez çalışır = 20 tick)
    cRoot:Get():GetDefaultWorld():ScheduleTask(20, TimerTick)

    LOG("[ClearLag Advanced] v1 - Tamamen Otomatik Lag Temizleyici Aktif!")
    return true
end

-- ══════════════════════════════════════════════════════
--  OTOMATİK ZAMANLAYICI
-- ══════════════════════════════════════════════════════
function TimerTick(World)
    TimeUntilClear = TimeUntilClear - 1

    -- Uyarı mesajlarını kontrol et
    for _, warnTime in ipairs(Config.Warnings) do
        if TimeUntilClear == warnTime then
            cRoot:Get():BroadcastChatWarning("§8[§cClearLag§8] §eYerlerdeki eşyalar §c" .. warnTime .. " §esaniye içinde silinecek!")
        end
    end

    -- Süre dolduğunda temizliği başlat
    if TimeUntilClear <= 0 then
        PerformClear()
        TimeUntilClear = Config.Interval -- Zamanlayıcıyı başa sar
    end

    -- Bir sonraki saniye için kendini tekrar çağır
    World:ScheduleTask(20, TimerTick)
end

-- ══════════════════════════════════════════════════════
--  TEMİZLİK MOTORU
-- ══════════════════════════════════════════════════════
function PerformClear()
    local removedCount = 0

    -- Sunucudaki tüm dünyaları (Normal, Nether, End) tarar
    cRoot:Get():ForEachWorld(function(TargetWorld)
        
        -- Dünyadaki tüm varlıkları (Entity) kontrol et
        TargetWorld:ForEachEntity(function(Entity)
            local eType = Entity:GetEntityType()

            if Config.ClearItems and eType == cEntity.etItem then
                Entity:Destroy()
                removedCount = removedCount + 1
            elseif Config.ClearExpOrbs and eType == cEntity.etExpOrb then
                Entity:Destroy()
                removedCount = removedCount + 1
            elseif Config.ClearProjectiles and eType == cEntity.etProjectile then
                Entity:Destroy()
                removedCount = removedCount + 1
            end
        end)

        -- RAM Optimizasyonu: Kullanılmayan Chunk'ları Boşalt
        if Config.UnloadChunks then
            TargetWorld:QueueUnloadUnusedChunks()
        end
    end)

    -- Temizlik bittikten sonra herkese duyur
    cRoot:Get():BroadcastChatSuccess("§8[§cClearLag§8] §aBaşarıyla §2" .. removedCount .. " §aobje dünyadan silindi!")
    
    if Config.UnloadChunks then
        cRoot:Get():BroadcastChatInfo("§8[§cClearLag§8] §7Kullanılmayan harita parçaları bellekten (RAM) temizlendi.")
    end
end

-- ══════════════════════════════════════════════════════
--  MANUEL KOMUT KONTROLÜ
-- ══════════════════════════════════════════════════════
function HandleClearLagCommand(Split, Player)
    Player:SendMessageInfo("§8[§cClearLag§8] §eManuel temizlik başlatılıyor...")
    
    PerformClear()
    
    -- Zamanlayıcıyı sıfırla ki komut girildikten hemen sonra otomatik sistem bir daha silmesin
    TimeUntilClear = Config.Interval 
    
    return true
end
