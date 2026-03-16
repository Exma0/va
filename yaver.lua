-- ╔══════════════════════════════════════════════════════╗
-- ║        YAVER - Koruyucu Kurt Sistemi  v21            ║
-- ║        Zırh • Parıldama • Görev • Gelişmiş AI        ║
-- ╚══════════════════════════════════════════════════════╝

local ActiveWolves    = {}   -- UUID → WolfID
local WolfTargets     = {}   -- WolfID → TargetID
local WolfAttackTick  = {}   -- WolfID → son saldırı tick'i
local OpenBackpacks   = {}   -- UUID → Window
local BackpackLastOpen= {}   -- UUID → os.clock()

local Ini = nil

-- ══════════════════════════════════════════════════════
--  SABİTLER
-- ══════════════════════════════════════════════════════
local ATTACK_CD    = 20    -- tick; ~1 sn
local WOLF_SPEED   = 7.0
local BACKPACK_CD  = 0.5   -- sn (çift tıklama koruması)

-- ══════════════════════════════════════════════════════
--  SEVİYE TABLOSU
-- ══════════════════════════════════════════════════════
local LEVEL_TABLE = {
    [1]  = { hp=20,  dmg=1.0,  spd=1.0, bag=1, sym="",    col="§7"  },
    [2]  = { hp=24,  dmg=1.5,  spd=1.1, bag=1, sym="",    col="§7"  },
    [3]  = { hp=28,  dmg=2.0,  spd=1.1, bag=1, sym="⚔",   col="§f"  },
    [4]  = { hp=32,  dmg=2.5,  spd=1.2, bag=1, sym="⚔",   col="§f"  },
    [5]  = { hp=38,  dmg=3.5,  spd=1.2, bag=2, sym="⚔✦",  col="§a"  },
    [6]  = { hp=44,  dmg=4.0,  spd=1.3, bag=2, sym="⚔✦",  col="§a"  },
    [7]  = { hp=52,  dmg=5.0,  spd=1.3, bag=2, sym="⚔✦✦", col="§2"  },
    [8]  = { hp=60,  dmg=6.0,  spd=1.4, bag=3, sym="⚔✦✦", col="§2"  },
    [9]  = { hp=70,  dmg=7.5,  spd=1.4, bag=3, sym="★✦✦", col="§b"  },
    [10] = { hp=82,  dmg=9.0,  spd=1.5, bag=3, sym="★★✦", col="§b"  },
    [11] = { hp=96,  dmg=10.5, spd=1.5, bag=4, sym="★★✦", col="§3"  },
    [12] = { hp=112, dmg=12.0, spd=1.6, bag=4, sym="★★★", col="§3"  },
    [13] = { hp=130, dmg=14.0, spd=1.6, bag=4, sym="★★★", col="§9"  },
    [14] = { hp=150, dmg=16.0, spd=1.7, bag=5, sym="♦★★", col="§9"  },
    [15] = { hp=172, dmg=18.5, spd=1.7, bag=5, sym="♦♦★", col="§5"  },
    [16] = { hp=196, dmg=21.0, spd=1.8, bag=5, sym="♦♦★", col="§5"  },
    [17] = { hp=224, dmg=24.0, spd=1.8, bag=6, sym="♦♦♦", col="§d"  },
    [18] = { hp=256, dmg=27.0, spd=1.9, bag=6, sym="♦♦♦", col="§d"  },
    [19] = { hp=290, dmg=30.0, spd=1.9, bag=6, sym="♦♦♦", col="§6"  },
    [20] = { hp=330, dmg=35.0, spd=2.0, bag=6, sym="⚡♦♦", col="§6"  },
    [21] = { hp=380, dmg=40.0, spd=2.0, bag=6, sym="⚡⚡♦", col="§e" },
    [22] = { hp=440, dmg=46.0, spd=2.1, bag=6, sym="⚡⚡♦", col="§e" },
    [23] = { hp=510, dmg=52.0, spd=2.1, bag=6, sym="⚡⚡⚡", col="§c" },
    [24] = { hp=590, dmg=59.0, spd=2.2, bag=6, sym="⚡⚡⚡", col="§c" },
    [25] = { hp=680, dmg=67.0, spd=2.3, bag=6, sym="☆⚡⚡⚡", col="§4"},
}

local function GetLvlData(lvl)
    return LEVEL_TABLE[math.min(lvl, 25)] or LEVEL_TABLE[25]
end

-- ══════════════════════════════════════════════════════
--  XP EŞİKLERİ
-- ══════════════════════════════════════════════════════
local function XPRequired(lvl)
    return math.floor(100 * (1.2 ^ (lvl - 1)))
end

-- ══════════════════════════════════════════════════════
--  GÖREV SİSTEMİ
-- ══════════════════════════════════════════════════════
local QUEST_DEFS = {
    { id="q_kill5",    name="§eİlk Av",          desc="5 mob öldür",         type="kill",  req=5,   xp=200  },
    { id="q_kill20",   name="§6Savaşçı",          desc="20 mob öldür",        type="kill",  req=20,  xp=500  },
    { id="q_kill50",   name="§cKan Banyosu",      desc="50 mob öldür",        type="kill",  req=50,  xp=1200 },
    { id="q_feed10",   name="§aŞefkatli Sahip",   desc="Kurdu 10 kez besle",  type="feed",  req=10,  xp=300  },
    { id="q_dmg500",   name="§dYıkım",            desc="500 toplam hasar ver",type="damage",req=500, xp=800  },
    { id="q_lv10",     name="§5Efsane Hayvan",    desc="Kurdu 10. seviyeye",  type="level", req=10,  xp=1000 },
    { id="q_lv20",     name="§4Tanrısal Varlık",  desc="Kurdu 20. seviyeye",  type="level", req=20,  xp=3000 },
    { id="q_lv25",     name="§6☆ Efsane ☆",      desc="Maksimum seviyeye",   type="level", req=25,  xp=8000 },
}

local QuestStats = {}

local function GetQuestStats(UUID)
    if not QuestStats[UUID] then
        QuestStats[UUID] = {
            kill   = Ini:GetValueI(UUID.."_qst", "kill",   0),
            feed   = Ini:GetValueI(UUID.."_qst", "feed",   0),
            damage = Ini:GetValueI(UUID.."_qst", "damage", 0),
        }
    end
    return QuestStats[UUID]
end

local function SaveQuestStats(UUID)
    local s = QuestStats[UUID]
    if not s then return end
    Ini:SetValueI(UUID.."_qst", "kill",   s.kill)
    Ini:SetValueI(UUID.."_qst", "feed",   s.feed)
    Ini:SetValueI(UUID.."_qst", "damage", s.damage)
    Ini:WriteFile("YaverData.ini")
end

local function GetCompletedQuests(UUID)
    local str = Ini:GetValue(UUID, "done_quests", "")
    local done = {}
    for id in string.gmatch(str, "([^,]+)") do done[id] = true end
    return done
end

local function MarkQuestDone(UUID, qid)
    local str = Ini:GetValue(UUID, "done_quests", "")
    Ini:SetValue(UUID, "done_quests", str == "" and qid or str..","..qid)
    Ini:WriteFile("YaverData.ini")
end

local function CheckQuests(UUID, type_key, value_add)
    local stats = GetQuestStats(UUID)
    stats[type_key] = (stats[type_key] or 0) + value_add
    SaveQuestStats(UUID)

    local done = GetCompletedQuests(UUID)
    local lvl  = Ini:GetValueI(UUID, "Level", 1)

    for _, qdef in ipairs(QUEST_DEFS) do
        if qdef.type == type_key and not done[qdef.id] then
            local progress = stats[type_key] or 0
            if type_key == "level" then
                progress = lvl
            end
            if progress >= qdef.req then
                MarkQuestDone(UUID, qdef.id)
                local curXP = Ini:GetValueI(UUID, "XP", 0)
                Ini:SetValueI(UUID, "XP", curXP + qdef.xp)
                Ini:WriteFile("YaverData.ini")
                DoWithPlayer(UUID, function(P)
                    P:SendMessageSuccess("§6[GÖREV TAMAMLANDI] "..qdef.name)
                    P:SendMessageSuccess("§7  "..qdef.desc.." → §e+"..qdef.xp.." XP")
                    pcall(function()
                        P:AddEntityEffect(cEntityEffect.effRegeneration, 20*5, 2)
                        P:AddEntityEffect(cEntityEffect.effAbsorption,   20*10, 1)
                    end)
                end)
            end
        end
    end
end

-- ══════════════════════════════════════════════════════
--  YARDIMCI FONKSİYONLAR
-- ══════════════════════════════════════════════════════
function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function DoWithPlayer(UUID, Callback)
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
    end
    if mtWolf then return mtWolf end
    return 95
end

local function IsWolf(Entity)
    if not Entity or not Entity:IsMob() then return false end
    local t = Entity:GetMobType()
    local w = GetWolfType()
    return (t == w) or (t == 95)
end

local function MoveToward(Ent, tx, tz, speed)
    local dx   = tx - Ent:GetPosX()
    local dz   = tz - Ent:GetPosZ()
    local dist = math.sqrt(dx*dx + dz*dz)
    if dist < 0.1 then return end
    local vx = (dx/dist) * speed
    local vz = (dz/dist) * speed
    local ok  = pcall(function() Ent:SetSpeedX(vx); Ent:SetSpeedZ(vz) end)
    if not ok then
        pcall(function()
            Ent:AddSpeedX(vx - Ent:GetSpeedX())
            Ent:AddSpeedZ(vz - Ent:GetSpeedZ())
        end)
    end
end

-- ══════════════════════════════════════════════════════
--  İSİM GÜNCELLEMESİ
-- ══════════════════════════════════════════════════════
local function UpdateWolfName(Player, WolfID)
    local UUID = Player:GetUUID()
    local lvl  = Ini:GetValueI(UUID, "Level", 1)
    local ld   = GetLvlData(lvl)

    local name = ld.col.."§l" .. Player:GetName() ..
                 " §r§7Kurdu §e[Lv"..lvl.."] " ..
                 ld.col..ld.sym

    Player:GetWorld():DoWithEntityByID(WolfID, function(Ent)
        Ent:SetCustomName(name)
        Ent:SetCustomNameAlwaysVisible(true)
    end)
end

-- ══════════════════════════════════════════════════════
--  PARTİKEL EFEKTLERİ
-- ══════════════════════════════════════════════════════
local PARTICLE_BY_TIER = {
    { min=5,  name="heart",            count=2,  ox=0.3, oy=0.5, oz=0.3 },
    { min=10, name="enchantmenttable", count=4,  ox=0.5, oy=0.8, oz=0.5 },
    { min=15, name="fireworksSpark",   count=6,  ox=0.6, oy=1.0, oz=0.6 },
    { min=20, name="flame",            count=8,  ox=0.7, oy=1.2, oz=0.7 },
    { min=23, name="portal",           count=12, ox=0.8, oy=1.4, oz=0.8 },
}

local function SpawnWolfParticles(World, Ent, lvl)
    if lvl < 5 then return end
    for i = #PARTICLE_BY_TIER, 1, -1 do
        local pt = PARTICLE_BY_TIER[i]
        if lvl >= pt.min then
            local pos = Vector3f(Ent:GetPosX(), Ent:GetPosY() + 0.5, Ent:GetPosZ())
            local off = Vector3f(pt.ox, pt.oy, pt.oz)
            pcall(function()
                World:BroadcastParticleEffect(pt.name, pos, off, 0, pt.count)
            end)
            break
        end
    end
end

-- ══════════════════════════════════════════════════════
--  SAHİBE SAĞLANAN İKSİR GÜÇLERI
-- ══════════════════════════════════════════════════════
local function ApplyOwnerBuffs(Player, lvl)
    local eff = cEntityEffect
    if lvl >= 5 then
        pcall(function() Player:AddEntityEffect(eff.effSpeed, 20, math.min(math.floor((lvl-5)/5), 2)) end)
    end
    if lvl >= 10 then
        pcall(function() Player:AddEntityEffect(eff.effStrength, 20, math.min(math.floor((lvl-10)/5), 2)) end)
    end
    if lvl >= 15 then
        pcall(function() Player:AddEntityEffect(eff.effJumpBoost, 20, math.min(math.floor((lvl-15)/5), 1)) end)
    end
    if lvl >= 20 then
        pcall(function() Player:AddEntityEffect(eff.effRegeneration, 20, 0) end)
    end
    if lvl >= 23 then
        pcall(function() Player:AddEntityEffect(eff.effFireResistance, 20, 0) end)
    end
    if lvl >= 25 then
        pcall(function() Player:AddEntityEffect(eff.effAbsorption, 20, 1) end)
    end
end

-- ══════════════════════════════════════════════════════
--  XP VE SEVİYE
-- ══════════════════════════════════════════════════════
local function GetWolfLevel(UUID) return Ini:GetValueI(UUID, "Level", 1) end
local function GetWolfXP(UUID)    return Ini:GetValueI(UUID, "XP",    0) end

local function AddWolfXP(UUID, Amount)
    local lvl = GetWolfLevel(UUID)
    if lvl >= 25 then return end

    local xp  = GetWolfXP(UUID) + Amount
    local req = XPRequired(lvl)

    while xp >= req and lvl < 25 do
        xp  = xp - req
        lvl = lvl + 1
        req = XPRequired(lvl)

        local ld = GetLvlData(lvl)
        Ini:SetValueI(UUID, "Level", lvl)

        DoWithPlayer(UUID, function(Player)
            Player:SendMessageSuccess(ld.col.."§l[⬆ SEVİYE ATLADI] "..
                "§r§eKurdun artık §l"..lvl..". §r§eseviyede!")
            Player:SendMessageInfo("§7  ❤ Can: "..ld.hp.." | ⚔ Hasar: +"..ld.dmg..
                " | 🎒 Depo: "..ld.bag.." satır | "..ld.col..ld.sym)

            pcall(function()
                Player:AddEntityEffect(cEntityEffect.effRegeneration, 20*3, 1)
            end)

            local WolfID = ActiveWolves[UUID]
            if WolfID then
                Player:GetWorld():DoWithEntityByID(WolfID, function(Ent)
                    local Mon = tolua.cast(Ent, "cMonster")
                    if Mon then
                        Mon:SetMaxHealth(ld.hp)
                        Mon:SetHealth(ld.hp)
                        Mon:SetRelativeWalkSpeed(ld.spd)
                    end
                    local pos = Vector3f(Ent:GetPosX(), Ent:GetPosY()+1, Ent:GetPosZ())
                    local off = Vector3f(0.8, 1.0, 0.8)
                    pcall(function()
                        Player:GetWorld():BroadcastParticleEffect(
                            "fireworksSpark", pos, off, 0, 20)
                    end)
                end)
                UpdateWolfName(Player, WolfID)
            end

            CheckQuests(UUID, "level", 0)
        end)
    end

    Ini:SetValueI(UUID, "Level", lvl)
    Ini:SetValueI(UUID, "XP", xp)
    Ini:WriteFile("YaverData.ini")
end

-- ══════════════════════════════════════════════════════
--  CANTA
-- ══════════════════════════════════════════════════════
local function GetBackpack(UUID)
    local lvl  = GetWolfLevel(UUID)
    local ld   = GetLvlData(lvl)
    local rows = ld.bag

    local Window = cLuaWindow(cWindow.wtChest, 9, rows,
        "§8Yaver Cantasi §7[Lv" .. lvl .. "] §e(" .. (rows * 9) .. " slot)")

    local Contents = Window:GetContents()
    local InvIni   = cIniFile()
    InvIni:ReadFile("YaverInv.ini")

    local maxSlot = rows * 9 - 1
    for i = 0, maxSlot do
        local str = InvIni:GetValue(UUID, "Slot_"..i, "")
        if str ~= "" then
            local parts = Split(str, ";")
            local Itm = cItem(
                tonumber(parts[1] or 0),
                tonumber(parts[2] or 0),
                tonumber(parts[3] or 0)
            )
            Contents:SetSlot(i % 9, math.floor(i / 9), Itm)
        end
    end

    Window:SetOnClosing(function(a_Window, a_Player, a_CanRefuse)
        local P_UUID  = a_Player:GetUUID()
        local Ini2    = cIniFile()
        Ini2:ReadFile("YaverInv.ini")
        local C = a_Window:GetContents()
        for i = 0, maxSlot do
            local Itm = C:GetSlot(i % 9, math.floor(i / 9))
            if not Itm:IsEmpty() then
                Ini2:SetValue(P_UUID, "Slot_"..i,
                    Itm.m_ItemType..";"..Itm.m_ItemCount..";"..Itm.m_ItemDamage)
            else
                Ini2:SetValue(P_UUID, "Slot_"..i, "")
            end
        end
        Ini2:WriteFile("YaverInv.ini")
        OpenBackpacks[P_UUID] = nil
        return false
    end)

    return Window
end

-- ══════════════════════════════════════════════════════
--  KURT OLUŞTURMA
-- ══════════════════════════════════════════════════════
local function SpawnWolfForPlayer(Player)
    local UUID  = Player:GetUUID()
    local World = Player:GetWorld()

    if ActiveWolves[UUID] then
        local OldID = ActiveWolves[UUID]
        World:DoWithEntityByID(OldID, function(Ent) Ent:Destroy() end)
        WolfTargets[OldID]    = nil
        WolfAttackTick[OldID] = nil
        ActiveWolves[UUID]    = nil
    end

    local WolfID = World:SpawnMob(
        Player:GetPosX(), Player:GetPosY() + 1.0, Player:GetPosZ(), GetWolfType()
    )

    if not WolfID or WolfID == cEntity.INVALID_ID then
        Player:SendMessageFailure("§cOyun motoru kurt üretemedi.")
        return
    end

    ActiveWolves[UUID] = WolfID

    World:DoWithEntityByID(WolfID, function(Ent)
        local lvl = GetWolfLevel(UUID)
        local ld  = GetLvlData(lvl)

        Ent:SetCustomNameAlwaysVisible(true)

        local Mon = tolua.cast(Ent, "cMonster")
        if Mon then
            Mon:SetMaxHealth(ld.hp)
            Mon:SetHealth(ld.hp)
            Mon:SetRelativeWalkSpeed(ld.spd)
        end

        local pos = Vector3f(Ent:GetPosX(), Ent:GetPosY()+0.5, Ent:GetPosZ())
        pcall(function()
            World:BroadcastParticleEffect("smoke", pos, Vector3f(0.3,0.5,0.3), 0, 8)
        end)
    end)

    UpdateWolfName(Player, WolfID)
end

-- ══════════════════════════════════════════════════════
--  INITIALIZE
-- ══════════════════════════════════════════════════════
function Initialize(Plugin)
    Plugin:SetName("yaver")
    Plugin:SetVersion(21)

    Ini = cIniFile()
    Ini:ReadFile("YaverData.ini")

    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED,               OnPlayerSpawned)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_DESTROYED,             OnPlayerDestroyed)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_RIGHT_CLICKING_ENTITY, OnRightClickingEntity)
    cPluginManager:AddHook(cPluginManager.HOOK_TAKE_DAMAGE,                  OnTakeDamage)
    cPluginManager:AddHook(cPluginManager.HOOK_KILLED,                       OnKilled)

    cPluginManager:BindCommand("/kurt",     "", HandleKurtCommand,    "Kurt yönetimi.")
    cPluginManager:BindCommand("/kurtgorev","", HandleQuestCommand,   "Görevleri göster.")
    cPluginManager:BindCommand("/kurtstats","", HandleStatsCommand,   "Kurt istatistikleri.")

    cRoot:Get():GetDefaultWorld():ScheduleTask(10, PeriodicWolfTask)

    LOG("[YAVER] v21 - Binme Özelliği Kaldırıldı • Zırh•Görev•Parıldama•GelişmişAI Aktif!")
    return true
end

-- ══════════════════════════════════════════════════════
--  KOMUTLAR
-- ══════════════════════════════════════════════════════
function HandleKurtCommand(CmdSplit, Player)
    local UUID = Player:GetUUID()
    local sub  = CmdSplit[2] and string.lower(CmdSplit[2]) or ""

    if sub == "cag" or sub == "" then
        if ActiveWolves[UUID] then
            Player:SendMessageWarning("§eKurdun yanına ışınlanıyor...")
            Player:GetWorld():DoWithEntityByID(ActiveWolves[UUID], function(Ent)
                Ent:TeleportToEntity(Player)
                WolfTargets[Ent:GetUniqueID()] = nil
            end)
        else
            SpawnWolfForPlayer(Player)
            Player:SendMessageSuccess("§aKoruyucu kurdun çağrıldı!")
        end

    elseif sub == "gonder" then
        if ActiveWolves[UUID] then
            Player:GetWorld():DoWithEntityByID(ActiveWolves[UUID], function(Ent)
                Ent:Destroy()
            end)
            WolfTargets[ActiveWolves[UUID]]    = nil
            WolfAttackTick[ActiveWolves[UUID]] = nil
            ActiveWolves[UUID]  = nil
            Player:SendMessageInfo("§7Kurdun gönderildi.")
        end

    elseif sub == "yardim" then
        Player:SendMessageInfo("§6── Kurt Komutları ──")
        Player:SendMessageInfo("§e/kurt       §7- Kurt çağır/ışınla")
        Player:SendMessageInfo("§e/kurt gonder§7- Kurdu geri gönder")
        Player:SendMessageInfo("§e/kurtgorev  §7- Görev listesi")
        Player:SendMessageInfo("§e/kurtstats  §7- İstatistikler")
        Player:SendMessageInfo("§e§nKurda sağ tık§r§7 = Çanta / Et = Besle")
    end
    return true
end

function HandleQuestCommand(CmdSplit, Player)
    local UUID  = Player:GetUUID()
    local done  = GetCompletedQuests(UUID)
    local stats = GetQuestStats(UUID)
    local lvl   = GetWolfLevel(UUID)

    Player:SendMessageInfo("§6§l══ GÖREVLER ══")
    for _, qdef in ipairs(QUEST_DEFS) do
        if done[qdef.id] then
            Player:SendMessageInfo("§a✔ "..qdef.name.." §7- "..qdef.desc.." §8[TAMAM]")
        else
            local prog = 0
            if qdef.type == "level" then
                prog = lvl
            else
                prog = stats[qdef.type] or 0
            end
            local pct = math.min(100, math.floor(prog/qdef.req*100))
            local bar = ""
            for i=1,10 do
                bar = bar .. (i <= math.floor(pct/10) and "§a█" or "§8░")
            end
            Player:SendMessageInfo("§e○ "..qdef.name.." §7- "..qdef.desc)
            Player:SendMessageInfo("  "..bar.." §7"..prog.."/"..qdef.req.." §e+"..qdef.xp.."XP")
        end
    end
    return true
end

function HandleStatsCommand(CmdSplit, Player)
    local UUID = Player:GetUUID()
    local lvl  = GetWolfLevel(UUID)
    local xp   = GetWolfXP(UUID)
    local req  = XPRequired(lvl)
    local ld   = GetLvlData(lvl)
    local done = GetCompletedQuests(UUID)
    local doneCount = 0
    for _ in pairs(done) do doneCount = doneCount + 1 end

    Player:SendMessageInfo("§6§l══ KURT İSTATİSTİKLERİ ══")
    Player:SendMessageInfo(ld.col.."  Seviye: §l"..lvl.."/25 "..ld.col..ld.sym)
    Player:SendMessageInfo("§e  XP: "..xp.."/"..req)
    Player:SendMessageInfo("§c  Max Can: "..ld.hp)
    Player:SendMessageInfo("§4  Hasar Bonusu: +"..ld.dmg)
    Player:SendMessageInfo("§b  Hız: x"..ld.spd)
    Player:SendMessageInfo("§d  Canta: " .. ld.bag .. " satir (" .. (ld.bag * 9) .. " slot)")
    Player:SendMessageInfo("§a  Tamamlanan Görev: "..doneCount.."/"..#QUEST_DEFS)
    return true
end

-- ══════════════════════════════════════════════════════
--  HOOK'LAR
-- ══════════════════════════════════════════════════════
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
        WolfTargets[WolfID]    = nil
        WolfAttackTick[WolfID] = nil
        ActiveWolves[UUID]     = nil
    end
    QuestStats[UUID] = nil
end

function OnRightClickingEntity(Player, Entity)
    if not IsWolf(Entity) then return false end
    local UUID = Player:GetUUID()
    if ActiveWolves[UUID] ~= Entity:GetUniqueID() then return false end

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

        local Mon = tolua.cast(Entity, "cMonster")
        if Mon then Mon:Heal(10) end

        pcall(function() Player:GetWorld():BroadcastEntityAnimation(Entity, 18) end)
        AddWolfXP(UUID, 50)
        Player:SendMessageInfo("§6[Yaver] §aKurdunu besledin! +50 XP, +10 Can")

        CheckQuests(UUID, "feed", 1)

    else
        local now = os.clock()
        if OpenBackpacks[UUID] then return true end
        if BackpackLastOpen[UUID] and (now - BackpackLastOpen[UUID]) < BACKPACK_CD then
            return true
        end
        BackpackLastOpen[UUID] = now

        local Win = GetBackpack(UUID)
        OpenBackpacks[UUID] = Win
        Player:OpenWindow(Win)
    end
    return true
end

function OnTakeDamage(Receiver, TCA)
    local Attacker = TCA.Attacker
    if not Attacker then return false end

    if IsWolf(Receiver) and Attacker:IsPlayer() then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Receiver:GetUniqueID() and uuid == Attacker:GetUUID() then
                return true
            end
        end
    end
    if Receiver:IsPlayer() and IsWolf(Attacker) then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Attacker:GetUniqueID() and uuid == Receiver:GetUUID() then
                return true
            end
        end
    end

    if IsWolf(Attacker) then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Attacker:GetUniqueID() then
                local ld = GetLvlData(GetWolfLevel(uuid))
                TCA.FinalDamage = TCA.FinalDamage + ld.dmg
                AddWolfXP(uuid, 5)
                CheckQuests(uuid, "damage", ld.dmg)
            end
        end
    end

    if Receiver:IsPlayer() then
        local WolfID = ActiveWolves[Receiver:GetUUID()]
        if WolfID and Attacker:GetUniqueID() ~= WolfID then
            WolfTargets[WolfID] = Attacker:GetUniqueID()
        end
    end

    if Attacker:IsPlayer() then
        local WolfID = ActiveWolves[Attacker:GetUUID()]
        if WolfID and Receiver:GetUniqueID() ~= WolfID then
            if Receiver:IsMob() or (Receiver:IsPlayer() and Receiver:GetUUID() ~= Attacker:GetUUID()) then
                WolfTargets[WolfID] = Receiver:GetUniqueID()
            end
        end
    end

    return false
end

function OnKilled(Victim, TCA, CustomDeathMessage)
    local Attacker = TCA.Attacker

    if IsWolf(Victim) then
        for uuid, wid in pairs(ActiveWolves) do
            if wid == Victim:GetUniqueID() then
                ActiveWolves[uuid]    = nil
                WolfTargets[wid]      = nil
                WolfAttackTick[wid]   = nil

                DoWithPlayer(uuid, function(P)
                    P:SendMessageWarning("§cKoruyucu kurdun yaralandı! 30 sn içinde döner.")
                end)
                Victim:GetWorld():ScheduleTask(20*30, function()
                    DoWithPlayer(uuid, function(P)
                        SpawnWolfForPlayer(P)
                        P:SendMessageSuccess("§aKoruyucu kurdun iyileşti ve döndü!")
                    end)
                end)
                break
            end
        end
    end

    if Attacker and Attacker:IsPlayer() then
        local uuid = Attacker:GetUUID()
        if ActiveWolves[uuid] then
            AddWolfXP(uuid, 25)
            CheckQuests(uuid, "kill", 1)
        end
    end
end

-- ══════════════════════════════════════════════════════
--  PERİYODİK AI SİMÜLASYONU
-- ══════════════════════════════════════════════════════
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

            local lvl = GetWolfLevel(UUID)
            local ld  = GetLvlData(lvl)

            -- ────────────────────────────
            -- SAVAŞ AI
            -- ────────────────────────────
            local TargetID       = WolfTargets[WolfID]
            local HasValidTarget = false

            if TargetID then
                World:DoWithEntityByID(TargetID, function(TargetEnt)
                    if not ((TargetEnt:IsMob() or TargetEnt:IsPlayer())
                            and TargetEnt:GetHealth() > 0) then
                        return
                    end

                    local dx   = TargetEnt:GetPosX() - Ent:GetPosX()
                    local dz   = TargetEnt:GetPosZ() - Ent:GetPosZ()
                    local dist = math.sqrt(dx*dx + dz*dz)

                    local chaseRange = 20 + lvl
                    if dist > chaseRange then return end

                    HasValidTarget = true

                    if dist > 2.2 then
                        MoveToward(Ent,
                            TargetEnt:GetPosX(),
                            TargetEnt:GetPosZ(),
                            ld.spd * WOLF_SPEED
                        )
                    else
                        local lastAtk = WolfAttackTick[WolfID] or 0
                        if (GlobalTick - lastAtk) >= ATTACK_CD then
                            WolfAttackTick[WolfID] = GlobalTick
                            local rawDmg = 4 + ld.dmg
                            pcall(function()
                                TargetEnt:TakeDamage(
                                    cEntity.dtMobAttack or 3,
                                    Ent, rawDmg, rawDmg, 0.5
                                )
                                World:BroadcastEntityAnimation(Ent, 0)
                            end)
                            AddWolfXP(UUID, 5)
                            CheckQuests(UUID, "damage", rawDmg)
                        end
                    end
                end)
            end

            -- Hedef yoksa sahibi takip et
            if not HasValidTarget then
                WolfTargets[WolfID] = nil
                local dx   = Player:GetPosX() - Ent:GetPosX()
                local dz   = Player:GetPosZ() - Ent:GetPosZ()
                local dist = math.sqrt(dx*dx + dz*dz)

                if dist > 20 then
                    Ent:TeleportToEntity(Player)
                elseif dist > 4 then
                    MoveToward(Ent,
                        Player:GetPosX(), Player:GetPosZ(),
                        ld.spd * WOLF_SPEED * 0.8
                    )
                end
            end

            -- ────────────────────────────
            -- PARTİKEL EFEKTLERİ
            -- ────────────────────────────
            if GlobalTick % 4 == 0 then
                SpawnWolfParticles(World, Ent, lvl)
            end

            -- ────────────────────────────
            -- SAHİBE BUFF
            -- ────────────────────────────
            ApplyOwnerBuffs(Player, lvl)

            -- ────────────────────────────
            -- KURT PASİF CAN YENİLEME
            -- ────────────────────────────
            if Wolf:GetHealth() < Wolf:GetMaxHealth() then
                pcall(function() Wolf:Heal(1) end)
            end
        end)
    end)

    World:ScheduleTask(10, PeriodicWolfTask)
end
