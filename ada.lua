-- ╔══════════════════════════════════════════════════════╗
-- ║        SAFE SPAWN - Güvenli Kara Doğuş Sistemi       ║
-- ║        Okyanusta doğma sorununu çözer  v2            ║
-- ╚══════════════════════════════════════════════════════╝

local E_BLOCK_WATER = 8
local E_BLOCK_STATIONARY_WATER = 9
local E_BLOCK_LAVA = 10
local E_BLOCK_STATIONARY_LAVA = 11

function Initialize(Plugin)
    Plugin:SetName("SafeSpawn")
    Plugin:SetVersion(2)

    -- Oyuncu dünyaya katıldığında veya öldükten sonra canlandığında tetiklenir
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED, OnPlayerSpawned)

    LOG("[SafeSpawn] v2 Aktif - Okyanusta doğan oyuncular karaya kurtarılacak!")
    return true
end

-- ══════════════════════════════════════════════════════
--  YARDIMCI FONKSİYONLAR
-- ══════════════════════════════════════════════════════
local function IsWater(blockType)
    return blockType == E_BLOCK_WATER or blockType == E_BLOCK_STATIONARY_WATER
end

local function IsLava(blockType)
    return blockType == E_BLOCK_LAVA or blockType == E_BLOCK_STATIONARY_LAVA
end

-- ══════════════════════════════════════════════════════
--  KARA ARAMA MOTORU (Asenkron)
-- ══════════════════════════════════════════════════════
local function FindSafeLand(Player, World, startX, startZ, attempt)
    -- Sonsuz döngüyü ve sunucu çökmesini engellemek için sınır
    if attempt > 30 then
        Player:SendMessageFailure("§cÇok fazla okyanus var! Güvenli kara bulunamadı.")
        return
    end

    -- Başlangıç noktasının etrafında rastgele bir koordinat seç
    local searchX = startX + math.random(-800, 800)
    local searchZ = startZ + math.random(-800, 800)

    -- Cuberite Chunk koordinatlarına çevir
    local chunkX = math.floor(searchX / 16)
    local chunkZ = math.floor(searchZ / 16)

    -- ChunkStay: Chunk'ı sunucuyu dondurmadan asenkron olarak yükler
    World:ChunkStay({ {chunkX, chunkZ} }, nil, function()
        -- Chunk hazır! Artık en yüksek bloğu güvenle kontrol edebiliriz
        local y = World:GetHeight(searchX, searchZ)
        
        if y > 0 then
            local blockSurface = World:GetBlock(searchX, y - 1, searchZ)
            
            -- Eğer yüzey su veya lav değilse ve hava (0) değilse kara bulduk demektir!
            if not IsWater(blockSurface) and not IsLava(blockSurface) and blockSurface ~= 0 then
                Player:TeleportToCoords(searchX + 0.5, y + 1.0, searchZ + 0.5)
                
                -- Oyuncunun doğuş noktasını (BedPos) kalıcı olarak buraya ayarla!
                pcall(function()
                    Player:SetBedPos(Vector3i(math.floor(searchX), math.floor(y + 1), math.floor(searchZ)))
                end)

                Player:SendMessageSuccess("§aKuru topraklara ulaştın! Doğuş noktan güncellendi.")
            else
                -- Yine suya denk geldik, aramaya devam et
                FindSafeLand(Player, World, startX, startZ, attempt + 1)
            end
        else
            -- Yükseklik hatası, tekrar dene
            FindSafeLand(Player, World, startX, startZ, attempt + 1)
        end
    end)
end

-- ══════════════════════════════════════════════════════
--  EVENT HOOK
-- ══════════════════════════════════════════════════════
function OnPlayerSpawned(Player)
    local World = Player:GetWorld()
    local UUID = Player:GetUUID()
    
    -- Oyuncu "Yeniden Doğ" butonuna bastığında blokların yüklenmesi için 10 tick (0.5 saniye) bekliyoruz.
    World:ScheduleTask(10, function()
        -- Gecikme sonrası oyuncu hala sunucuda mı kontrol et (çökme koruması)
        cRoot:Get():DoWithPlayerByUUID(UUID, function(P)
            local px = math.floor(P:GetPosX())
            local py = math.floor(P:GetPosY())
            local pz = math.floor(P:GetPosZ())

            local blockAtFeet = World:GetBlock(px, py, pz)
            local blockBelow  = World:GetBlock(px, py - 1, pz)

            -- Eğer oyuncunun ayakları veya bir altındaki blok su ise aramayı başlat
            if IsWater(blockAtFeet) or IsWater(blockBelow) then
                P:SendMessageWarning("§eOkyanusta doğdun! Seni güvenli bir karaya taşıyorum, lütfen bekle...")
                FindSafeLand(P, World, px, pz, 1)
            end
        end)
    end)
end
