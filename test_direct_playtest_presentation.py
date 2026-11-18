"""Exercise the production client presentation hooks with mocked Unreal objects."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


FIXTURE = r"""
local f={events={},widgets={},team1=0,team2=0}
local function object(name)
    local obj={name=name,alive=true}
    function obj:IsValid() return self.alive end
    function obj:GetAddress() return self end
    function obj:GetFullName() return self.name end
    return obj
end
local function valid(obj) return obj~=nil and obj:IsValid() end
f.world,f.otherWorld=object('world'),object('other world')
local function report(message) f.events[#f.events+1]=message end
local function array(values)
    return {
        GetArrayNum=function() return #values end,
        ForEach=function(_,callback)
            for i,value in ipairs(values) do callback(i,{get=function() return value end}) end
        end,
    }
end
f.pc=object('controller')
function f.pc:GetWorld() return f.world end
f.ps={r_TeamId=1}
f.gs=object('gamestate')
function f.gs:GetWorld() return f.world end
function f.setScores(one,two,duplicate)
    f.team1,f.team2=one,two
    local rows={{TeamNum=2,Score=two},{TeamNum=1,Score=one}}
    if duplicate then rows[#rows+1]=rows[1] end
    f.gs.r_CurrentTeamScores=array(rows)
end
f.setScores(0,0)
local class='WidgetBlueprintGeneratedClass /Game/UI/Components/Game/WBP_Game_ScoreBar_CTF.WBP_Game_ScoreBar_CTF_C'
function f.addWidget(world,controller)
    local bar=object('ScoreBar')
    bar.UI_Game_Scorebar_ScoreCount=object('Friendly')
    bar.UI_Game_Scorebar_ScoreCount_1=object('Enemy')
    bar.FriendlyScoreFill=object('FriendlyFill')
    bar.EnemyScoreFill=object('EnemyFill')
    for _,counter in ipairs({bar.UI_Game_Scorebar_ScoreCount,bar.UI_Game_Scorebar_ScoreCount_1}) do
        counter.CachedScore=0
        counter.ScoreText=object('ScoreText')
        counter.ScoreText.value='0'
        function counter.ScoreText:GetText() return {ToString=function() return self.value end} end
    end
    bar.calls=0
    function bar:GetClass() return object(class) end
    function bar:GetWorld() return world end
    function bar:GetOwningPlayer() return controller end
    function bar:IsVisible() return not self.hidden end
    function bar:UpdateScore(score,fill,counter)
        assert((fill==self.FriendlyScoreFill and counter==self.UI_Game_Scorebar_ScoreCount) or
               (fill==self.EnemyScoreFill and counter==self.UI_Game_Scorebar_ScoreCount_1))
        self.calls=self.calls+1
        counter.CachedScore=score
        counter.ScoreText.value=tostring(score)
    end
    f.widgets[#f.widgets+1]=bar
    return bar
end
local function FindAllOf(className)
    assert(className=='WBP_Game_ScoreBar_CTF_C')
    return f.widgets
end

local visualPath='/Game/Topaz/Abilities/Weapons/Shocklance/AV_Topaz_Shocklance.AV_Topaz_Shocklance'
local function effect(folder,name)
    return {
        ParticleSystem=object('NiagaraSystem /Game/VFX/Weapons/ShockLance/'..folder..'/'..name..'.'..name),
        SocketName={ToString=function() return 'MuzzleSocket' end},
    }
end
f.charge=effect('Ammo','NS_ShockLance_Standard_Ammo_1P')
f.worldCharge=effect('Ammo','NS_ShockLance_Standard_Ammo_3P')
f.reload=effect('Reload','NS_ShockLance_Standard_Reload_1P')
f.worldReload=effect('Reload','NS_ShockLance_Standard_Reload_3P')
f.visual=object('ValDeviceAudioVisual '..visualPath)
f.visual.RemainingAmmoActions=array({f.worldCharge,f.charge})
f.visual.ReloadActions=array({f.reload,f.worldReload})
f.visual.TracerFX1P=object('native tracer')
f.visual.FireActions=array({effect('MuzzleFlash','NS_ShockLance_Standard_MuzzleFlash_1P')})
f.visual.HitImpactFXList=array({effect('HitFX','NS_Shocklance_HitFX')})
local function StaticFindObject(path)
    assert(path==visualPath)
    if not f.unloaded then return f.visual end
end
"""


class DirectPlaytestPresentationTests(unittest.TestCase):
    def fixture(self):
        source = (Path(__file__).with_name('lua') / 'client.lua').read_text()
        block = source.split('-- BEGIN_DIRECT_PLAYTEST_PRESENTATION', 1)[1]
        block = block.split('-- END_DIRECT_PLAYTEST_PRESENTATION', 1)[0]
        lua = LuaRuntime(max_memory=8 * 1024 * 1024)
        return lua.execute(FIXTURE + block + """
            f.refresh=function() refresh_ctf_score_bar(f.pc,f.ps,f.gs) end
            f.configure=configure_shock_lance
            return f
        """)

    def test_both_team_views_follow_the_same_replicated_scores(self):
        f = self.fixture()
        bar = f.addWidget(f.world, f.pc)
        f.refresh()
        self.assertEqual(bar.calls, 0)
        f.setScores(1, 2)
        f.refresh()
        f.refresh()
        self.assertEqual(bar.calls, 2)
        self.assertEqual(bar.UI_Game_Scorebar_ScoreCount.CachedScore, 1)
        self.assertEqual(bar.UI_Game_Scorebar_ScoreCount_1.CachedScore, 2)
        f.ps.r_TeamId = 2
        f.refresh()
        self.assertEqual(bar.UI_Game_Scorebar_ScoreCount.CachedScore, 2)
        self.assertEqual(bar.UI_Game_Scorebar_ScoreCount_1.CachedScore, 1)

    def test_enemy_score_text_recovers_even_when_its_cached_score_is_current(self):
        f = self.fixture()
        bar = f.addWidget(f.world, f.pc)
        f.setScores(0, 2)
        bar.UI_Game_Scorebar_ScoreCount_1.CachedScore = 2
        f.refresh()
        f.refresh()
        self.assertEqual(bar.UI_Game_Scorebar_ScoreCount_1.ScoreText.value, '2')
        self.assertEqual(bar.calls, 1)

    def test_late_bar_refreshes_and_foreign_or_hidden_bars_are_excluded(self):
        f = self.fixture()
        f.setScores(1, 0)
        f.refresh()
        foreign = f.addWidget(f.otherWorld, f.pc)
        hidden = f.addWidget(f.world, f.pc)
        hidden.hidden = True
        local = f.addWidget(f.world, f.pc)
        for _ in range(3):
            f.refresh()
        self.assertEqual((local.calls, foreign.calls, hidden.calls), (1, 0, 0))
        f.setScores(9, 0, True)
        f.refresh()
        self.assertEqual(local.calls, 1)

    def test_only_the_two_camera_lightning_slots_change(self):
        f = self.fixture()
        f.unloaded = True
        f.configure()
        self.assertIsNotNone(f.charge.ParticleSystem)
        f.unloaded = False
        f.configure()
        f.configure()
        self.assertIsNone(f.charge.ParticleSystem)
        self.assertIsNone(f.reload.ParticleSystem)
        for kept in (f.worldCharge.ParticleSystem, f.worldReload.ParticleSystem,
                     f.visual.TracerFX1P, f.visual.FireActions, f.visual.HitImpactFXList):
            self.assertIsNotNone(kept)
        self.assertEqual(len(f.events), 1)

    def test_unknown_reload_system_leaves_both_slots_intact(self):
        f = self.fixture()
        f.reload.ParticleSystem.name = 'Unrecognized effect'
        f.configure()
        self.assertIsNotNone(f.charge.ParticleSystem)
        self.assertIsNotNone(f.reload.ParticleSystem)
