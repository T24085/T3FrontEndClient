"""Exercise the carried-flag border against the native score-bar widget shape."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = (Path(__file__).resolve().parent / "lua/client.lua").read_text(encoding="utf-8")
START = SOURCE.index("local carriedFlagBorder=(function()")
END = SOURCE.index("local function refresh_ctf_score_bar(", START)
FIXTURE = """
local function valid(object) return object~=nil and object:IsValid() end
local function same_object(a,b) return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() end
local fixture={created=0}
local nextAddress=0
local function object(name)
    nextAddress=nextAddress+1
    local address=nextAddress
    return {
        IsValid=function(self) return not self.invalid end,
        GetAddress=function() return address end,
        GetClass=function() return {GetFullName=function() return name end} end,
    }
end
local function panel(name)
    local widget=object(name)
    widget.children={}
    function widget:GetChildrenCount() return #self.children end
    function widget:GetChildAt(index) return self.children[index+1] end
    function widget:add(child)
        self.children[#self.children+1]=child
        child.parent=self
    end
    return widget
end
local types={
    ['/Script/UMG.CanvasPanel']=object('canvas'),
    ['/Script/UMG.Border']=object('border'),
}
function StaticFindObject(path) return types[path] end
function StaticConstructObject(class)
    if class==types['/Script/UMG.Border'] then
        local line=object('Class /Script/UMG.Border')
        function line:SetBrushColor(color) self.color=color end
        return line
    end
    fixture.created=fixture.created+1
    local frame=panel('Class /Script/UMG.CanvasPanel')
    function frame:SetVisibility(value) self.visibility=value end
    function frame:GetVisibility() return self.visibility end
    function frame:GetParent() return self.parent end
    function frame:RemoveFromParent()
        for index,widget in ipairs(self.parent.children) do
            if widget==self then table.remove(self.parent.children,index);break end
        end
        self.parent=nil
    end
    function frame:AddChildToCanvas(child)
        self:add(child)
        local slot=object('canvas slot')
        child.slot=slot
        function slot:SetAnchors(anchors) self.anchors=anchors end
        function slot:SetOffsets(offsets) self.offsets=offsets end
        return slot
    end
    return frame
end
fixture.world=object('world')
fixture.bar={FriendlyObjectives=panel('friendly'),EnemyObjectives=panel('enemy')}
function fixture.bar:IsValid() return true end
local function flag_icon(team)
    local flag=object('flag')
    flag.r_TeamId=team
    flag.info={bReturned=true}
    flag.RootComponent=object('root')
    function flag.RootComponent:GetAttachParent() return self.attached end
    function flag:GetWorld() return fixture.world end
    function flag:GetHeldBy() return self.info end
    local carrier=object('carrier')
    carrier.PlayerState=object('player state')
    carrier.PlayerState.r_TeamId=3-team
    function carrier:GetWorld() return fixture.world end
    function carrier:IsAlive() return not self.dead end
    local mesh=object('mesh')
    function mesh:GetOwner() return carrier end

    local icon=object('WidgetBlueprintGeneratedClass /Game/UI/Components/Game/WBP_Game_ScoreBar_CTF_FlagIcon.WBP_Game_ScoreBar_CTF_FlagIcon_C')
    icon.CachedActor,icon.WidgetTree=flag,object('widget tree')
    icon.overlay=panel('Class /Script/UMG.Overlay')
    function icon.overlay:AddChildToOverlay(child)
        self:add(child)
        local slot=object('overlay slot')
        function slot:SetHorizontalAlignment(value) assert(value==0) end
        function slot:SetVerticalAlignment(value) assert(value==0) end
        return slot
    end
    icon.Icon=object('image')
    function icon.Icon:GetParent() return icon.overlay end
    icon.overlay:add(icon.Icon)

    local row={icon=icon,flag=flag,carrier=carrier}
    function row.take()
        flag.info={bReturned=false,Holder=carrier}
        flag.RootComponent.attached=mesh
    end
    function row.drop()
        -- The attachment can clear before the replicated holder.
        flag.RootComponent.attached=nil
    end
    function row.return_home()
        flag.info={bReturned=true,Holder=carrier}
    end
    function row.frame() return icon.overlay:GetChildAt(1) end
    return row
end
fixture.flags={flag_icon(1),flag_icon(2)}
function fixture.team(team)
    fixture.bar.FriendlyObjectives.children={fixture.flags[team].icon}
    fixture.bar.EnemyObjectives.children={fixture.flags[3-team].icon}
end
"""


class CarriedFlagBorderTest(unittest.TestCase):
    def setUp(self):
        self.fixture = LuaRuntime().execute(
            FIXTURE + SOURCE[START:END]
            + """
function fixture.tick(team)
    carriedFlagBorder({fixture.bar},team,fixture.world)
end
return fixture
"""
        )

    def test_each_team_gets_one_border_only_around_its_own_carried_flag(self):
        f = self.fixture
        for team in (1, 2):
            with self.subTest(team=team):
                f.team(team)
                row, enemy = f.flags[team], f.flags[3 - team]
                row.return_home()
                enemy.take()
                f.tick(team)
                self.assertIsNone(row.frame())
                self.assertIsNone(enemy.frame())
                row.take()
                f.tick(team)
                f.tick(team)
                frame = row.frame()
                self.assertEqual((frame.visibility, len(frame.children)), (3, 4))
                self.assertEqual(f.created, team)
                self.assertGreater(frame.children[1].color.R, 0.8)
                self.assertEqual(frame.children[1].slot.offsets.Bottom, 2)
                row.drop()
                f.tick(team)
                self.assertEqual(row.frame().visibility, 1)
                row.return_home()
                f.tick(team)
                self.assertEqual(row.frame().visibility, 1)

    def test_friendly_carrier_and_dead_carrier_clear_the_border(self):
        f = self.fixture
        f.team(1)
        row = f.flags[1]
        row.take()
        row.carrier.PlayerState.r_TeamId = 1
        f.tick(1)
        self.assertIsNone(row.frame())
        row.carrier.PlayerState.r_TeamId = 2
        f.tick(1)
        self.assertEqual(row.frame().visibility, 3)
        row.carrier.dead = True
        f.tick(1)
        self.assertEqual(row.frame().visibility, 1)

    def test_rebuilt_hud_removes_its_old_border(self):
        f = self.fixture
        f.team(1)
        row = f.flags[1]
        row.take()
        f.tick(1)
        f.bar.FriendlyObjectives.children[1] = None
        f.tick(1)
        self.assertIsNone(row.frame())
        f.team(1)
        f.tick(1)
        self.assertEqual(row.frame().visibility, 3)
        self.assertEqual(f.created, 2)
