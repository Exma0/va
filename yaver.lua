local ActiveWolves = {}
local OpenBackpacks = {}
local WolfTargets = {}
-- HATA DÜZELTMESİ: "Wrong window ID" uyarısını önlemek için backpack cooldown.
-- Oyuncu kısa sürede kurda iki kez tıklarsa GetBackpack() iki ayrı cLuaWindow
-- nesnesi oluşturur; sunucu ikincisini ID+1 ile açarken client hâlâ birincisinin
-- paketlerini gönderiyor → "Wrong window ID (exp N+1, got N)" uyarısı.
local BackpackLastOpen = {}   -- UUID → os.clock() zaman damgası
local BACKPACK_COOLDOWN = 0.5 -- saniye
local WolfAttackTick = {}  -- Saldırı cooldown takibi (kurt ID başına)
local Ini = nil

local ATTACK_COOLDOWN_TICKS = 20  -- Saldırılar arası minimum tick (~1 saniye)
local WOLF_SPEED = 6.0             -- Kurt hareket hızı (blok/saniye)

local function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

local function DoWithPlayer(UUID, Callback)
    cRoot:Get():ForEachPlayer(function(P)
        if P:GetUUID() == UUID then Callback(P) end
    end)
end

local function GetWolfType()
    if cMonster and cMonster.mtWolf then return cMonster.mtWolf end
    local wt = nil
    if cMonster and cMonster.StringToMobType then
        pcall(function() wt = cMonster.StringToMobType("wolf") end)
        if wt and wt ~= -1 then return wt end
        pcall(function() wt = cMonster.StringToMobType("Wolf") end)
        if wt and wt ~= -1 then return wt end
    end
    if mtWolf then return mtWolf end
    return 95
end

local function IsWolf(Entity)
    if not Entity or not Entity:IsMob() then return false end
    local t  = Entity:GetMobType()
    local wt = GetWolfType()
    return (t == wt) or (t == 95)
end

-- ===============================================================
-- Kurt Hareketi
-- MoveToPosition / SetTarget Cuberite Lua API'de YOKTUR.
-- Bunun yerine AddSpeedX/Z ile hız vektörü set ediyoruz.
-- ===============================================================
local function MoveWolfToward(Ent, tx, ty, tz)
    local dx   = tx - Ent:GetPosX()
    local dz   = tz - Ent:GetPosZ()
    local dist = math.sqrt(dx * dx + dz * dz)
    if dist < 0.1 then return end

    local vx = (dx / dist) * WOLF_SPEED
    local vz = (dz / dist) * WOLF_SPEED

    -- Önce SetSpeedX/Z dene; yoksa AddSpeed fallback
    local ok = pcall(function()
        Ent:SetSpeedX(vx)
        Ent:SetSpeedZ(vz)
    end)
    if not ok then
        pcall(function()
            Ent:AddSpeedX(vx - Ent:GetSpeedX())
            Ent:AddSpeedZ(vz - Ent:GetSpeedZ())
        end)
    end
end

function Initialize(Plugin)
    Plugin:SetName("yaver")
    Plugin:SetVersion(12)

    Ini = cIniFile()
    Ini:ReadFile("YaverData.ini")

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,               OnPlayerSpawned)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_DESTROYED,             OnPlayerDestroyed)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_RIGHT_CLICKING_ENTITY, OnRightClickingEntity)
    cPluginManager:AddHook(cPluginManager.HOOK_TAKE_DAMAGE,                  OnTakeDamage)
    cPluginManager:AddHook(cPluginManager.HOOK_KILLED,                       OnKilled)

    cPluginManager:BindCommand("/kurt", "", HandleKurtCommand, "Koruyucu kurdunu yanina cagirir.")

    cRoot:Get():GetDefaultWorld():ScheduleTask(10, PeriodicWolfTask)
    LOG("[YAVER] v12 - Canta + Hareket + Saldiri duzeltmeleri aktif!")
    return true
end

-- ================= XP ve Seviye =================
function GetWolfLevel(UUID) return Ini:GetValueI(UUID, "Level", 1) end
function GetWolfXP(UUID)    return Ini:GetValueI(UUID, "XP",    0) end

function AddWolfXP(UUID, Amount)
    local lvl = GetWolfLevel(UUID)
    local xp  = GetWolfXP(UUID) + Amount
    local req = lvl * 100

    if xp >= req then
        lvl = lvl + 1
        xp  = 0
        Ini:SetValueI(UUID, "Level", lvl)

        DoWithPlayer(UUID, function(Player)
            Player:SendMessageSuccess("§6[Yaver] §aKoruyucu Kurdun Seviye Atladi! Yeni Seviye: §e" .. lvl)
            local WolfID = ActiveWolves[UUID]
            if WolfID then
                Player:GetWorld():DoWithEntityByID(WolfID, function(Ent)
                    Ent:SetCustomName("§b" .. Player:GetName() .. " §7Kurdu §e[Lv " .. lvl .. "] §8| §a(Shift+Tık)")
                    local Monster = tolua.cast(Ent, "cMonster")
                    if Monster then
                        local maxHp = 20 + (lvl * 2)
                        Monster:SetMaxHealth(maxHp)
                        Monster:Heal(maxHp)
                    end
                    pcall(function() Player:GetWorld():BroadcastEntityAnimation(Ent, 18) end)
                end)
            end
        end)
    end
    Ini:SetValueI(UUID, "XP", xp)
    Ini:WriteFile("YaverData.ini")
end

-- ================= Kurt Cantasi =================
function GetBackpack(UUID)
    local Window = cLuaWindow(cWindow.wtChest, 9, 3, "§8Yaver Cantasi")

    -- DÜZELTME: Pencere açılmadan önce SetSlot(nil, ...) çalışmaz.
    -- Doğru yol: Window:GetContents() → cItemGrid üzerinden erişim.
    local Contents = Window:GetContents()
    local InvIni   = cIniFile()
    InvIni:ReadFile("YaverInv.ini")

    for i = 0, 26 do
        local str = InvIni:GetValue(UUID, "Slot_" .. i, "")
        if str ~= "" then
            local parts = Split(str, ";")
            local Itm = cItem(
                tonumber(parts[1] or 0),
                tonumber(parts[2] or 0),
                tonumber(parts[3] or 0)
            )
            -- cItemGrid:SetSlot(X, Y, Item) — X=sütun (0-8), Y=satır (0-2)
            Contents:SetSlot(i % 9, math.floor(i / 9), Itm)
        end
    end

    -- DÜZELTME: SetOnClosing doğru callback adıdır (SetOnClosed yoktur).
    -- İmza: function(Window, Player, CanRefuse) -> bool
    Window:SetOnClosing(function(a_Window, a_Player, a_CanRefuse)
        local P_UUID = a_Player:GetUUID()
        local Ini2   = cIniFile()
        Ini2:ReadFile("YaverInv.ini")

        local C = a_Window:GetContents()
        for i = 0, 26 do
            local Itm = C:GetSlot(i % 9, math.floor(i / 9))
            if not Itm:IsEmpty() then
                Ini2:SetValue(P_UUID, "Slot_" .. i,
                    Itm.m_ItemType .. ";" .. Itm.m_ItemCount .. ";" .. Itm.m_ItemDamage)
            else
                Ini2:SetValue(P_UUID, "Slot_" .. i, "")
            end
        end
        Ini2:WriteFile("YaverInv.ini")
        OpenBackpacks[P_UUID] = nil
        return false  -- Pencere kapansın
    end)

    return Window
end

-- ================= Kurt Çağırma =================
function SpawnWolfForPlayer(Player)
    local UUID  = Player:GetUUID()
    local World = Player:GetWorld()

    -- DÜZELTME: ActiveWolves[UUID] = nil ÖNCE ID'yi kaydet; aksi halde WolfTargets[nil] silinir
    if ActiveWolves[UUID] then
        local OldID = ActiveWolves[UUID]
        World:DoWithEntityByID(OldID, function(Ent) Ent:Destroy() end)
        ActiveWolves[UUID]      = nil
        WolfTargets[OldID]      = nil
        WolfAttackTick[OldID]   = nil
    end

    local WolfType = GetWolfType()
    local WolfID   = World:SpawnMob(
        Player:GetPosX(), Player:GetPosY() + 1.0, Player:GetPosZ(), WolfType
    )

    if WolfID and WolfID ~= cEntity.INVALID_ID then
        ActiveWolves[UUID] = WolfID

        World:DoWithEntityByID(WolfID, function(Ent)
            local lvl = GetWolfLevel(UUID)
            Ent:SetCustomName("§b" .. Player:GetName() .. " §7Kurdu §e[Lv " .. lvl .. "] §8| §a(Shift+Tık)")
            Ent:SetCustomNameAlwaysVisible(true)

            local Monster = tolua.cast(Ent, "cMonster")
            if Monster then
                local maxHp = 20 + (lvl * 2)
                Monster:SetMaxHealth(maxHp)
                Monster:SetHealth(maxHp)
                Monster:SetRelativeWalkSpeed(1.4)  -- %40 daha hızlı
            end
        end)
    else
        Player:SendMessageFailure("§cOyun motoru kurt uretemedi.")
    end
end

function HandleKurtCommand(Split, Player)
    local UUID = Player:GetUUID()
    if ActiveWolves[UUID] then
        Player:SendMessageWarning("§eKurdun zaten aktif! Yanina isinlaniyor...")
        Player:GetWorld():DoWithEntityByID(ActiveWolves[UUID], function(Ent)
            Ent:TeleportToEntity(Player)
            WolfTargets[Ent:GetUniqueID()] = nil
        end)
    else
        SpawnWolfForPlayer(Player)
        Player:SendMessageSuccess("§aSadik kurdun yanina cagirildi!")
    end
    return true
end

function OnPlayerSpawned(Player)
    local UUID = Player:GetUUID()
    if not ActiveWolves[UUID] then
        Player:GetWorld():ScheduleTask(40, function()
            DoWithPlayer(UUID, function(P) SpawnWolfForPlayer(P) end)
        end)
    end
end

function OnPlayerDestroyed(Player)
    local UUID   = Player:GetUUID()
    local WolfID = ActiveWolves[UUID]
    if WolfID then
        Player:GetWorld():DoWithEntityByID(WolfID, function(Ent) Ent:Destroy() end)
        ActiveWolves[UUID]     = nil
        WolfTargets[WolfID]    = nil
        WolfAttackTick[WolfID] = nil
    end
end

function OnRightClickingEntity(Player, Entity)
    if IsWolf(Entity) then
        local UUID = Player:GetUUID()
        if ActiveWolves[UUID] == Entity:GetUniqueID() then

            if Player:IsCrouched() then
                cPluginManager:Get():ExecuteCommand(Player, "/hub")
                return true
            end

            local Item    = Player:GetEquippedItem()
            local MeatIDs = {
                [319]=true,[320]=true,[363]=true,[364]=true,[365]=true,
                [366]=true,[367]=true,[423]=true,[424]=true,[411]=true,[412]=true
            }

            if MeatIDs[Item.m_ItemType] then
                Item.m_ItemCount = Item.m_ItemCount - 1
                if Item.m_ItemCount <= 0 then Item:Empty() end
                Player:GetInventory():SetEquippedItem(Item)

                local Monster = tolua.cast(Entity, "cMonster")
                if Monster then Monster:Heal(10) end

                pcall(function() Player:GetWorld():BroadcastEntityAnimation(Entity, 18) end)
                AddWolfXP(UUID, 50)
                Player:SendMessageInfo("§6[Yaver] §aKurdunu besledin! (+50 XP, +10 Can)")
            else
                -- Cooldown kontrolü: çift tıkta iki pencere açılmasın
                local now = os.clock()
                if BackpackLastOpen[UUID] and (now - BackpackLastOpen[UUID]) < BACKPACK_COOLDOWN then
                    return true  -- Çok hızlı, ikinci pencereyi engelle
                end
                -- Eğer zaten açık bir pencere varsa önce onu kapat
                if OpenBackpacks[UUID] then
                    return true  -- Açık pencere kapanmadan yenisini açma
                end
                BackpackLastOpen[UUID] = now
                local Win = GetBackpack(UUID)
                OpenBackpacks[UUID] = Win
                Player:OpenWindow(Win)
            end
            return true
        end
    end
    return false
end

-- ================= Savaş ve Hasar =================
function OnTakeDamage(Receiver, TCA)
    local Attacker = TCA.Attacker
    if not Attacker then return false end

    -- Dost ateşi: oyuncu kendi kurduna vuramasın
    if IsWolf(Receiver) and Attacker:IsPlayer() then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Receiver:GetUniqueID() and uuid == Attacker:GetUUID() then
                return true
            end
        end
    end

    -- Dost ateşi: kurt kendi sahibine vuramasın
    if Receiver:IsPlayer() and IsWolf(Attacker) then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Attacker:GetUniqueID() and uuid == Receiver:GetUUID() then
                return true
            end
        end
    end

    -- Kurt birine vurursa hasar bonusu (HOOK_TAKE_DAMAGE üzerinden)
    if IsWolf(Attacker) then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Attacker:GetUniqueID() then
                local lvl = GetWolfLevel(uuid)
                TCA.FinalDamage = TCA.FinalDamage + (lvl * 1.5)
                AddWolfXP(uuid, 5)
            end
        end
    end

    -- Oyuncuya saldırılırsa → kurda hedef göster
    if Receiver:IsPlayer() then
        local UUID   = Receiver:GetUUID()
        local WolfID = ActiveWolves[UUID]
        if WolfID and Attacker:GetUniqueID() ~= WolfID then
            WolfTargets[WolfID] = Attacker:GetUniqueID()
        end
    end

    -- Oyuncu birine saldırırsa → kurda hedef göster
    if Attacker:IsPlayer() then
        local UUID   = Attacker:GetUUID()
        local WolfID = ActiveWolves[UUID]
        if WolfID and Receiver:GetUniqueID() ~= WolfID then
            if Receiver:IsMob() or (Receiver:IsPlayer() and Receiver:GetUUID() ~= UUID) then
                WolfTargets[WolfID] = Receiver:GetUniqueID()
            end
        end
    end

    return false  -- Hasara devam et
end

function OnKilled(Victim, TCA, CustomDeathMessage)
    local Attacker = TCA.Attacker

    if IsWolf(Victim) then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Victim:GetUniqueID() then
                ActiveWolves[uuid]     = nil
                WolfTargets[wid]       = nil
                WolfAttackTick[wid]    = nil

                DoWithPlayer(uuid, function(P)
                    P:SendMessageWarning("§cKoruyucu kurdun ağır yaralandı! 30 saniye içinde iyileşip dönecek.")
                end)

                Victim:GetWorld():ScheduleTask(20 * 30, function()
                    DoWithPlayer(uuid, function(Player)
                        SpawnWolfForPlayer(Player)
                        Player:SendMessageSuccess("§aKoruyucu kurdun iyileşti ve yanına döndü!")
                    end)
                end)
                break
            end
        end
    end

    if Attacker and Attacker:IsPlayer() then
        local uuid = Attacker:GetUUID()
        if ActiveWolves[uuid] then AddWolfXP(uuid, 25) end
    end
end

-- ================= Periyodik Döngü (Savaş AI + Takip) =================
local GlobalTick = 0

function PeriodicWolfTask(World)
    GlobalTick = GlobalTick + 1

    World:ForEachPlayer(function(Player)
        local UUID   = Player:GetUUID()
        local WolfID = ActiveWolves[UUID]
        if not WolfID then return end

        World:DoWithEntityByID(WolfID, function(Ent)
            local Wolf = tolua.cast(Ent, "cMonster")
            if not Wolf then return end

            local TargetID       = WolfTargets[WolfID]
            local HasValidTarget = false

            -- ── Hedef takibi ──
            if TargetID then
                World:DoWithEntityByID(TargetID, function(TargetEnt)
                    if not ((TargetEnt:IsMob() or TargetEnt:IsPlayer()) and TargetEnt:GetHealth() > 0) then
                        return
                    end

                    local dx   = TargetEnt:GetPosX() - Ent:GetPosX()
                    local dz   = TargetEnt:GetPosZ() - Ent:GetPosZ()
                    local dist = math.sqrt(dx * dx + dz * dz)

                    if dist > 24 then
                        HasValidTarget = false  -- Çok uzak, bırak
                        return
                    end

                    HasValidTarget = true

                    if dist > 2.0 then
                        -- Hedefe koş
                        MoveWolfToward(Ent,
                            TargetEnt:GetPosX(),
                            TargetEnt:GetPosY(),
                            TargetEnt:GetPosZ()
                        )
                    else
                        -- Saldırı menzili — cooldown kontrolü
                        local lastAtk = WolfAttackTick[WolfID] or 0
                        if (GlobalTick - lastAtk) >= ATTACK_COOLDOWN_TICKS then
                            WolfAttackTick[WolfID] = GlobalTick
                            local lvl = GetWolfLevel(UUID)
                            local dmg = 4 + (lvl * 1.5)
                            pcall(function()
                                local dtType = cEntity.dtMobAttack or 3
                                -- TakeDamage(DamageType, Attacker, RawDamage, FinalDamage, KnockbackAmount)
                                TargetEnt:TakeDamage(dtType, Ent, dmg, dmg, 0.5)
                                World:BroadcastEntityAnimation(Ent, 0)
                            end)
                            AddWolfXP(UUID, 5)
                        end
                    end
                end)
            end

            -- ── Hedef yoksa sahibini takip et ──
            if not HasValidTarget then
                WolfTargets[WolfID] = nil

                local dx   = Player:GetPosX() - Ent:GetPosX()
                local dz   = Player:GetPosZ() - Ent:GetPosZ()
                local dist = math.sqrt(dx * dx + dz * dz)

                if dist > 20 then
                    Ent:TeleportToEntity(Player)
                elseif dist > 4 then
                    MoveWolfToward(Ent,
                        Player:GetPosX(),
                        Player:GetPosY(),
                        Player:GetPosZ()
                    )
                end
            end

            -- ── Seviye bufları ──
            local lvl = GetWolfLevel(UUID)
            if lvl >= 5  then Player:AddEntityEffect(cEntityEffect.effSpeed,       20, 0) end
            if lvl >= 10 then Player:AddEntityEffect(cEntityEffect.effStrength,    20, 0) end
            if lvl >= 20 then Player:AddEntityEffect(cEntityEffect.effRegeneration, 20, 0) end

            -- ── Kurt pasif can yenileme ──
            if Wolf:GetHealth() < Wolf:GetMaxHealth() then
                pcall(function() Wolf:Heal(1) end)
            end
        end)
    end)

    World:ScheduleTask(10, PeriodicWolfTask)
end
