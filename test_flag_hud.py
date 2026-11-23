"""Exercise late flag replication in the native CTF score and minimap widgets."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = Path(__file__).with_name('lua') / 'client.lua'
FIXTURE = r'''
local ui='/Game/UI/Components/Game/'
local function object(class, world)
    local o={world=world}
    function o:GetAddress() return self end
    function o:GetWorld() return self.world end
    function o:GetClass()
        return {GetFullName=function()
            return 'WidgetBlueprintGeneratedClass '..ui..class..'.'..class..'_C'
        end}
    end
    return o
end
local function panel()
    local p={children={}}
    function p:GetChildrenCount() return #self.children end
    function p:GetChildAt(i) return self.children[i+1] end
    function p:RemoveChildAt(i) table.remove(self.children,i+1) end
    function p:add(child)
        child.parent=self
        self.children[#self.children+1]=child
    end
    return p
end
local function label()
    return {
        value='',
        GetText=function(self) return {ToString=function()return self.value end} end,
        SetText=function(self,new) self.value=new end,
    }
end
local world,elsewhere=object(),object()
local pc,other=object('controller',world),object('other player',world)
local flags,widgets={},{}
local f={pc=pc,world=world,now=0}
local function FindAllOf(class)
    if class=='TopPickup_Flag' then return flags end
    if class=='UI_Game_Map_C' then return widgets end
    error(class)
end
local function valid(o) return o~=nil and not o.invalid end
local function same_object(a,b)
    return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()
end
local function FText(text) return text end
local function reconcile_score_bar(_,update) update() end
local borderClass={GetFullName=function()return 'Class /Script/UMG.Border' end}
local function StaticFindObject(path)
    assert(path=='/Script/UMG.Border')
    return borderClass
end
local function StaticConstructObject(class,tree)
    assert(class==borderClass and tree.RootWidget)
    local border={}
    function border:SetBrush(brush)
        assert(brush.DrawAs==4 and brush.TintColor.SpecifiedColor.A==0)
        assert(brush.OutlineSettings.Width>0 and brush.OutlineSettings.Color.SpecifiedColor.R==1)
    end
    function border:SetPadding(padding) assert(padding.Left==0) end
    function border:SetVisibility(state) self.state=state end
    return border
end

function f.flag(team,foreign)
    local flag=object('flag',foreign and elsewhere or world)
    flag.r_TeamId=team
    flag.info={bReturned=true}
    flag.position=team*100
    flag.RootComponent={GetAttachParent=function()return flag.attachment end}
    function flag:GetHeldBy()return self.info end
    function flag:GetOwner()return self.holder end
    function flag:attach(pawn)
        self.holder=pawn
        self.attachment={GetOwner=function()return pawn end}
    end
    function flag:replicate_holder(pawn)
        self.info={Holder=pawn,bReturned=false}
    end
    function flag:take(pawn)
        self:attach(pawn)
        self:replicate_holder(pawn)
    end
    function flag:drop(position,lag)
        self.position=position
        self.holder,self.attachment=nil,nil
        if not lag then self.info={bReturned=false} end
    end
    function flag:reset()
        self.position=team*100
        self.holder,self.attachment=nil,nil
        self.info={bReturned=true}
    end
    flags[#flags+1]=flag
    return flag
end
function f.pawn()
    local pawn=object('pawn',world)
    function pawn:setName(name)
        self.PlayerState={GetPlayerName=function()return name end}
    end
    return pawn
end
local function icon(class,flag)
    local w=object(class,world)
    w.CachedActor=flag
    w.CachedHolderInfo={bReturned=false}
    function w:GetParent() return self.parent end
    if class=='WBP_Game_ScoreBar_CTF_FlagIcon' then
        local root,overlay=panel(),panel()
        overlay.GetClass=function() return {GetFullName=function()return 'Class /Script/UMG.Overlay' end} end
        function overlay:AddChildToOverlay(child)
            self:add(child)
            return {SetHorizontalAlignment=function(_,v)assert(v==0)end,
                    SetVerticalAlignment=function(_,v)assert(v==0)end}
        end
        overlay:add({GetClass=function()return {GetFullName=function()return 'Class /Script/UMG.Image' end}end})
        root:add({GetClass=function()return {GetFullName=function()return 'Class /Script/UMG.CanvasPanel' end}end})
        root:add(overlay)
        w.WidgetTree={RootWidget=root}
    end
    w.Text=label()
    w.visible=false
    function w:IsVisible()return self.visible end
    function w:OnFlagHeldChanged(actor,info,_)
        assert(actor==self.CachedActor)
        self.CachedHolderInfo=info
        self.ShouldUpdateLocation=info.bReturned or info.Holder==nil
        self.visible=self.ShouldUpdateLocation
        if info.bReturned then
            self.Text.value=''
        elseif info.Holder then
            if info.Holder.PlayerState then self.Text.value=info.Holder.PlayerState:GetPlayerName() end
        else
            self.Text.value='DROPPED'
        end
    end
    function w:RemoveFromParent()
        for i,child in ipairs(self.parent.children) do
            if child==self then table.remove(self.parent.children,i);return end
        end
    end
    return w
end
function f.score(team)
    local score=object('WBP_Game_ScoreBar_CTF',world)
    score.FriendlyObjectives,score.EnemyObjectives=panel(),panel()
    score.binds=0
    function score:add(flag)
        local w=icon('WBP_Game_ScoreBar_CTF_FlagIcon',flag)
        local p=flag.r_TeamId==team and self.FriendlyObjectives or self.EnemyObjectives
        p:add(w)
        return w
    end
    function score:BindFlags()
        self.binds=self.binds+1
        for _,flag in ipairs(flags) do
            if valid(flag) and flag.world==world then self:add(flag) end
        end
    end
    return score
end
function f.map(foreign,nonOwner,hidden)
    local map=object('UI_Game_Map',foreign and elsewhere or world)
    map.Flags=panel()
    map.MapScale=0.01
    map.binds=0
    map.updates=0
    function map:GetOwningPlayer()return nonOwner and other or pc end
    function map:GetVisibility()return hidden and 1 or 0 end
    function map:BindFlags()
        self.binds=self.binds+1
        self.Flags.children={}
        for _,flag in ipairs(flags) do
            if valid(flag) and flag.world==world then
                local marker=object('UI_Game_Minimap_Flag',world)
                marker.CachedActor=flag
                marker.WBP_Game_MinimapFlagIcon=icon('WBP_Game_MinimapFlagIcon',flag)
                self.Flags:add(marker)
            end
        end
    end
    function map:UpdateFlags()
        self.updates=self.updates+1
        for _,marker in ipairs(self.Flags.children) do
            local w=marker.WBP_Game_MinimapFlagIcon
            if w and w.ShouldUpdateLocation then
                marker.location=marker.CachedActor.position*self.MapScale
            end
        end
    end
    widgets[#widgets+1]=map
    return map
end
function f.unrelated() return object('OtherWidget',world) end
'''


class FlagHudTest(unittest.TestCase):
    def run_lua(self, checks):
        source = SOURCE.read_text(encoding='utf-8')
        block = source.split('local ctfFlagHud=', 1)[1]
        block = block.split('local function refresh_ctf_score_bar', 1)[0]
        lua = LuaRuntime()
        self.assertTrue(lua.execute(FIXTURE + '\nlocal hud=' + block + checks))

    def test_score_uses_native_icons_and_recovers_late_names_for_both_teams(self):
        self.run_lua(r'''
local own=f.flag(1)
local blue,red=f.score(1),f.score(2)
local generator=f.unrelated()
blue.FriendlyObjectives:add(generator)
blue:add(own)
assert(hud.prepare(f.pc,f.world)==nil and blue.binds==0)
local enemy=f.flag(2)
f.flag(2,true)
local hunter,runner=f.pawn(),f.pawn()
hunter:setName('Hunter')
own:take(hunter)
enemy:take(runner)
local function update(now)
    local flags=assert(hud.prepare(f.pc,f.world))
    hud.score(blue,flags,1,now)
    hud.score(red,flags,2,now)
end
update(1)
assert(blue.binds==1 and red.binds==1)
assert(blue.FriendlyObjectives:GetChildAt(0)==generator)
local blueHome,redHome=blue.FriendlyObjectives:GetChildAt(1),red.EnemyObjectives:GetChildAt(0)
local blueAway,redAway=blue.EnemyObjectives:GetChildAt(0),red.FriendlyObjectives:GetChildAt(0)
update(2)
assert(blueHome.Text.value=='Hunter' and redHome.Text.value=='Hunter')
assert(blueAway.Text.value=='' and redAway.Text.value=='')
runner:setName('Runner')
update(3)
assert(blueAway.Text.value=='Runner' and redAway.Text.value=='Runner')
enemy:drop(500,true)
update(4)
assert(blueAway.Text.value=='DROPPED' and redAway.Text.value=='DROPPED')
assert(enemy.info.Holder==runner)
blueAway.Text.value=''
update(4.5)
assert(blueAway.Text.value=='DROPPED')
enemy:take(hunter)
update(5)
assert(blueAway.Text.value=='Hunter' and redAway.Text.value=='Hunter')
enemy:reset()
own:reset()
update(6)
assert(blueAway.Text.value=='' and redAway.Text.value=='')
assert(blueHome.Text.value=='' and redHome.Text.value=='')
assert(blue.binds==1 and red.binds==1)
return true
''')

    def test_red_outline_marks_only_the_local_teams_stolen_flag_and_clears_on_drop(self):
        self.run_lua(r'''
local blueFlag,redFlag=f.flag(1),f.flag(2)
local blue,red=f.score(1),f.score(2)
local blueRunner,redRunner=f.pawn(),f.pawn()
blueRunner:setName('Blue runner')
blueRunner.PlayerState.r_TeamId=1
redRunner:setName('Red runner')
redRunner.PlayerState.r_TeamId=2
local function update(now)
    local flags=assert(hud.prepare(f.pc,f.world))
    hud.score(blue,flags,1,now)
    hud.score(red,flags,2,now)
end
local function overlay(panel)
    return panel:GetChildAt(0).WidgetTree.RootWidget:GetChildAt(1)
end
update(1)
local blueHome,redHome=overlay(blue.FriendlyObjectives),overlay(red.FriendlyObjectives)
local blueAway,redAway=overlay(blue.EnemyObjectives),overlay(red.EnemyObjectives)
blueFlag:take(redRunner);redFlag:take(blueRunner)
update(2)
assert(blueHome:GetChildAt(1).state==4 and redHome:GetChildAt(1).state==4)
assert(blueAway:GetChildrenCount()==1 and redAway:GetChildrenCount()==1)
blueFlag:drop(500,true);redFlag:reset()
update(3)
assert(blueHome:GetChildAt(1).state==1 and redHome:GetChildAt(1).state==1)
blueFlag:take(redRunner)
update(4)
assert(blueHome:GetChildrenCount()==2 and blueHome:GetChildAt(1).state==4)
return true
''')

    def test_minimap_rebinds_loose_flags_and_preserves_carried_and_hidden_paths(self):
        self.run_lua(r'''
local own,enemy=f.flag(1),f.flag(2)
local map=f.map()
local foreign,otherPlayer,hidden=f.map(true),f.map(false,true),f.map(false,false,true)
local runner=f.pawn()
local function update(now)
    hud.minimap(f.pc,f.world,assert(hud.prepare(f.pc,f.world)),now)
end
update(1)
local home,away=map.Flags:GetChildAt(0),map.Flags:GetChildAt(1)
assert(home.location==1 and away.location==2)
assert(home.WBP_Game_MinimapFlagIcon.visible and away.WBP_Game_MinimapFlagIcon.visible)
enemy:take(runner)
update(2)
assert(not away.WBP_Game_MinimapFlagIcon.visible and not away.WBP_Game_MinimapFlagIcon.ShouldUpdateLocation)
enemy:drop(750,true)
update(3)
assert(away.WBP_Game_MinimapFlagIcon.visible and away.location==7.5)
assert(away.WBP_Game_MinimapFlagIcon.Text.value=='DROPPED')
enemy:reset()
update(4)
assert(away.WBP_Game_MinimapFlagIcon.Text.value=='' and away.location==2)
table.remove(map.Flags.children,2)
update(5)
assert(map.binds==2 and map.Flags:GetChildrenCount()==2)
local unknown=f.unrelated()
table.remove(map.Flags.children,2)
map.Flags:add(unknown)
update(10)
assert(map.binds==2 and map.Flags:GetChildAt(1)==unknown)
for _,skip in ipairs({foreign,otherPlayer,hidden}) do assert(skip.binds==0 and skip.updates==0) end
return true
''')

    def test_defers_score_and_minimap_refresh_when_a_team_has_two_live_flag_actors(self):
        self.run_lua(r'''
local friendly,enemy=f.flag(1),f.flag(2)
local expired=f.flag(2)
assert(hud.prepare(f.pc,f.world)==nil)
expired.invalid=true
local flags=assert(hud.prepare(f.pc,f.world))
assert(flags[friendly] and flags[enemy] and not flags[expired])
return true
''')

    def test_late_join_and_handoff_wait_for_attachment_before_inferring_drop(self):
        self.run_lua(r'''
local own,enemy=f.flag(1),f.flag(2)
local blue,map=f.score(1),f.map()
local first,next=f.pawn(),f.pawn()
first:setName('First runner')
next:setName('Next runner')
enemy:replicate_holder(first)
local function update(now)
    local flags=assert(hud.prepare(f.pc,f.world))
    hud.score(blue,flags,1,now)
    hud.minimap(f.pc,f.world,flags,now)
end
update(1)
update(2)
local score=blue.EnemyObjectives:GetChildAt(0)
local marker=map.Flags:GetChildAt(1)
local icon=marker.WBP_Game_MinimapFlagIcon
assert(score.Text.value=='First runner' and not icon.visible)

enemy:attach(first)
update(3)
local root=enemy.RootComponent
enemy.RootComponent=nil
enemy:drop(500,true)
update(4)
assert(score.Text.value=='First runner' and not icon.visible)
enemy.RootComponent=root
update(5)
assert(score.Text.value=='DROPPED' and icon.visible and marker.location==5)
assert(enemy.info.Holder==first)

enemy:replicate_holder(next)
update(6)
assert(score.Text.value=='Next runner' and not icon.visible)
enemy:attach(next)
update(7)
enemy:drop(750,true)
update(8)
assert(score.Text.value=='DROPPED' and icon.visible and marker.location==7.5)

enemy:reset()
update(9)
enemy:replicate_holder(next)
update(10)
assert(score.Text.value=='Next runner' and not icon.visible)
return true
''')
