"""Exercise the production minimap binding with generated community map rows."""

from pathlib import Path
import tempfile
import unittest

from lupa.lua54 import LuaRuntime

from community_maps import MapDefinition, lua_map_definitions


ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / 'lua/client.lua').read_text(encoding='utf-8')
MAPS = (
    ('KatabaticT22026', 'KatabaticT2', 'Arena_KatabaticT2_2026_P', 146000),
    ('MinotaurT22026', 'MinotaurT2', 'Arena_MinotaurT2_2026_P', 122000),
    ('BeggarsRunTWLT22026', 'BeggarsRunTWLT2', 'Arena_BeggarsRunTWLT2_2026_P', 132000),
    ('QuagmireTWLT22026', 'QuagmireTWLT2', 'Arena_QuagmireTWLT2_2026_P', 161000),
)


FIXTURE = '''
local f={captures={},radars={},managers={},meshes={},requests=0,spawns=0,reports={}}
local next_address=0
local function object(name)
    local actor={}
    next_address=next_address+1
    local address=next_address
    function actor:GetAddress() return address end
    function actor:GetFullName() return name end
    function actor:GetWorld() return self.world end
    return actor
end
local world, foreign=object('World'),object('Foreign world')
local gs=object(descriptor.world..'PersistentLevel.GameState');gs.world=world
function gs:GetMinimapManager() return self.r_MinimapManager end
local pc=object(descriptor.world..'PersistentLevel.PlayerController');pc.world=world
pc.PlayerState={r_TeamId=1}
function gs:HasAuthority() return false end
pc.HasAuthority=gs.HasAuthority
function pc:IsLocalPlayerController() return true end
local settings=object(descriptor.world..'PersistentLevel.WorldSettings');settings.world=world
f.settings_class='Class /Script/Valhalla.ValWorldSettings'
function settings:GetClass() return object(f.settings_class) end
setmetatable(settings,{__index=function(_,key) if key=='MapSize' then return authored end end,
    __newindex=function(t,key,value) assert(key~='MapSize','authored settings were changed');rawset(t,key,value) end})
local lib=object('UILibrary /Script/ValhallaUI.Default__UILibrary')
function lib:GetWorldSettings(context) assert(context==pc);return settings end
local target=object('TextureRenderTarget2D /Game/Maps/Game/CrossFire/Crossfire_RenderTarget2D.Crossfire_RenderTarget2D')
target.SizeX,target.SizeY=1024,1024
local api=object('GameplayStatics /Script/Engine.Default__GameplayStatics')
function api:BeginDeferredActorSpawnFromClass(context,klass,transform)
    assert(context==pc and klass:GetFullName():find('BP_MinimapCapture_C',1,true))
    f.spawns=f.spawns+1;f.height=transform.Translation.Z
    local capture=object('MinimapCapture');capture.world=world
    local component={ProjectionType=1,TextureTarget=target}
    function component:GetOwner() return capture end
    function component:CaptureScene() f.requests=f.requests+1 end
    capture.SceneCaptureComponent2D=component
    f.component=component
    f.captures[#f.captures+1]=capture
    return capture
end
function api:FinishSpawningActor(actor) return actor end
local contracts=releaseRadarBlueprintContracts
local radarWidgetClass=object('Radar widget class')
function StaticFindObject(path)
    if path=='/Game/UI/Components/Game/UI_Game_Minimap_Radar.UI_Game_Minimap_Radar_C' then return radarWidgetClass end
    if path=='/Script/ValhallaUI.Default__UILibrary' then return lib end
    if path=='/Script/Engine.Default__GameplayStatics' then return api end
    if path=='/Game/Common/Blueprints/Cameras/BP_MinimapCapture.BP_MinimapCapture_C' then
        return object('BlueprintGeneratedClass '..path)
    end
    for _,contract in pairs(contracts) do
        if contract.path==path then
            local fn=object('Function '..path)
            function fn:ForEachProperty(callback)
                for field,kind in pairs(contract.fields) do
                    local property=object(kind..' '..path..':'..field)
                    function property:GetFName() return {ToString=function()return field end} end
                    callback(property)
                end
            end
            return fn
        end
    end
end
local widget=object('UI_Game_Map');widget.world=world
widget.visibility=0
function widget:GetVisibility() return self.visibility end
function widget:SetVisibility(value) self.visibility=value end
widget.Material=object('Map material')
widget.MapTexture={Brush={ResourceObject=widget.Material}}
widget.CachedZoom,widget.TargetZoom=1,1
widget.DetectionRange=42500
widget.RadarSensors={children=0,GetChildrenCount=function(self) return self.children end}
function widget.RadarSensors:GetChildAt() return {GetClass=function()return radarWidgetClass end} end
function widget.RadarSensors:ClearChildren() self.children=0 end
function widget:GetOwningPlayer() return pc end
function widget:UpdateSublevel() self.CachedMapScale=1024/settings.MapSize;self.MapScale=self.CachedMapScale end
function widget:BindRadarSensors() self.RadarSensors.children=#f.radars;f.binds=(f.binds or 0)+1 end
function widget:BindMinimap() assert(gs:GetMinimapManager());f.data_binds=(f.data_binds or 0)+1 end
function widget:OnMinimapData() f.data_rows=gs:GetMinimapManager().r_MinimapPlayers:GetArrayNum() end
local foreignWidget=object('Foreign map widget');foreignWidget.world=foreign
foreignWidget.GetOwningPlayer=widget.GetOwningPlayer
function foreignWidget:SetVisibility() error('foreign minimap changed') end
local otherPlayerWidget=object('Other player map widget');otherPlayerWidget.world=world
function otherPlayerWidget:GetOwningPlayer() return otherPlayerWidget end
otherPlayerWidget.SetVisibility=foreignWidget.SetVisibility
local teams={}
local radarPost
function FindAllOf(klass)
    return ({BP_MinimapCapture_C=f.captures,StaticMeshActor=f.meshes,UI_Game_Map_C={widget,foreignWidget,otherPlayerWidget},
        BP_Objective_RadarSensor_C=f.radars,TeamState=teams,ValMinimapManager=f.managers})[klass]
end
function RegisterHook(path,_,post)
    assert(path=='/Script/Topaz.TopRadarSensor:SetRadarStatus' and not radarPost)
    radarPost=post
    return 1,2
end
function UnregisterHook(path,pre,post)
    assert(path=='/Script/Topaz.TopRadarSensor:SetRadarStatus' and pre==1 and post==2 and radarPost)
    radarPost=nil
end
function f.add_teams()
    for id=1,2 do
        local team=object('TeamState')
        team.world=world;team.r_bIsRadarOnline=true;team.notifications=0
        team.HasAuthority=gs.HasAuthority
        function team:GetTeamId()return id end
        function team:IsRadarOnline()return self.r_bIsRadarOnline end
        function team:OnRep_IsRadarOnline()self.notifications=self.notifications+1 end
        teams[id]=team
    end
end
function f.deactivate_sensor(index,downed)
    local sensor=f.radars[index]
    sensor.PoweredComp.r_bOwnerDowned=downed
    teams[sensor.r_TeamId].r_bIsRadarOnline=not downed
    if radarPost then radarPost({get=function()return sensor end}) end
end
function f.add_mesh(asset,x,z,half_z,elsewhere,hidden,collision)
    local actor=object('StaticMeshActor');actor.world=elsewhere and foreign or world;actor.bHidden=hidden
    actor.StaticMeshComponent={StaticMesh=object('StaticMesh '..asset)}
    local c=actor.StaticMeshComponent;c.world=actor.world
    function c:GetWorld() return self.world end
    function c:GetOwner() return actor end
    function c:GetCollisionEnabled() return collision or 3 end
    function c:GetCollisionObjectType() return 0 end
    function actor:GetActorBounds(colliding,origin,extent)
        assert(colliding==true)
        origin.X,origin.Y,origin.Z=x,0,z
        extent.X,extent.Y,extent.Z=1000,1000,half_z
    end
    f.meshes[#f.meshes+1]=actor
end
function f.add_map_capture()
    local capture=object('authored capture');capture.world=world;f.captures[1]=capture
end
function f.add_manager(rows,elsewhere)
    local manager=object('Minimap manager')
    manager.world=elsewhere and foreign or world
    manager.HasAuthority=gs.HasAuthority
    function manager:GetClass() return object('Class /Script/Valhalla.ValMinimapManager') end
    manager.r_MinimapPlayers={GetArrayNum=function()return rows end}
    f.managers[#f.managers+1]=manager
    return manager
end
function f.add_radars()
    for team=1,2 do
        local radar=object('Radar sensor');radar.world=world;radar.r_TeamId=team
        radar.HasAuthority=gs.HasAuthority
        radar.radius=team==1 and 20000 or 30000
        function radar:GetDetectionRadius() return self.radius end
        radar.PoweredComp={r_bGeneratorPowered=true,r_bOwnerDowned=false,GetOwner=function()return radar end}
        function radar:GetClass()
            return object('BlueprintGeneratedClass /Game/Topaz/Game/Objectives/BP_Objective_RadarSensor.BP_Objective_RadarSensor_C')
        end
        f.radars[#f.radars+1]=radar
    end
end
local runtime=releaseRadarRuntimeFactory({valid=function(v) return v~=nil end,scope=function() end,
    signature=function() end,report=function(value) f.reports[#f.reports+1]=value end,
    map_descriptors={descriptor},guard_factory=releaseRadarGuardFactory,helper_factory=releaseRadarHelperFactory,
    capture_bounds_factory=releaseRadarBoundsFactory,world_settings_guard_factory=releaseNativeWorldSettingsFactory,
    blueprint_contracts=contracts})
function f.tick() return runtime.tick(pc,gs) end
function f.retire()
    function gs:GetFullName() return 'a different remote level' end
    return runtime.tick(pc,gs)
end
f.teams=teams
f.widget=widget
f.player_state=pc.PlayerState
f.game_state=gs
return f
'''


class RadarProjectionTest(unittest.TestCase):
    def fixture(self, map_id, group, level, size, *, retail=False, radar_count=None, hide=False):
        lua = LuaRuntime()
        if retail:
            package = f'/Game/Maps/Active/{group}/{level}'
            row = lua.table(name=map_id, package=package, world=f'{package}.{level}:', native=True)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'lua').mkdir()
                (root / 'lua/community_maps.lua').write_text('return {}\n', encoding='utf-8')
                path = lua_map_definitions(root, root, MapDefinition(map_id, map_id, group, level))
                row = lua.execute(path.read_text(encoding='utf-8'))[map_id]
            self.assertTrue(row.native)
            self.assertIsNone(row.assembly_asset)
        row.radars_per_team = radar_count
        row.hide_minimap = hide
        lua.globals().descriptor = row
        lua.globals().authored = size
        start = SOURCE.index('local function community_radar_group(')
        end = SOURCE.index('local releaseRadarRuntime=releaseRadarRuntimeFactory(', start)
        return lua.execute(SOURCE[start:end] + FIXTURE)

    def test_generated_native_rows_use_own_cooked_meshes_and_authored_map_size(self):
        for map_id, group, level, size in MAPS:
            with self.subTest(map=map_id):
                f = self.fixture(map_id, group, level, size)
                f.add_mesh(f'/Game/Community/{group}/UnlistedAssembly.UnlistedAssembly', 0, 110000, 9000)
                f.add_mesh(f'/Game/Maps/Community/{group}/{level}.InLevelMesh', 1000, 120000, 5000)
                f.add_mesh(f'/Game/Community/{group}/OutsideTile.OutsideTile', size, 999000, 0)
                f.add_mesh(f'/Game/Community/{group}/ForeignActor.ForeignActor', 0, 998000, 0, True)
                f.add_mesh(f'/Game/Community/{group}/Hidden.H', 0, 888000, 0, False, True)
                f.add_mesh(f'/Game/Community/{group}/VisualEffect.V', 0, 889000, 0, False, False, 0)
                f.add_mesh('/Game/Community/OtherMap/Mesh.Mesh', 0, 500000, 0)
                self.assertTrue(f.tick())
                self.assertEqual(f.height, 136000)
                self.assertEqual(f.component.OrthoWidth, size)
                self.assertAlmostEqual(f.widget.CachedMapScale, 1024 / size)
                self.assertEqual((f.widget.CachedZoom, f.widget.TargetZoom), (1, 1))

    def test_background_captures_without_radars_and_late_radars_bind(self):
        f = self.fixture(*MAPS[-1])
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.RadarSensors.children, 0)
        self.assertEqual(f.requests, 1)
        f.add_radars()
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.RadarSensors.children, 2)
        self.assertEqual((f.requests, f.spawns), (1, 1))

    def test_single_sensor_range_uses_local_team_and_restores_native_default(self):
        f = self.fixture(*MAPS[-1])
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.DetectionRange, 42500)
        f.add_radars()
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.DetectionRange, 20000)
        f.player_state.r_TeamId = 2
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.DetectionRange, 30000)
        f.player_state.r_TeamId = 3
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.DetectionRange, 42500)

    def test_recovers_a_single_replicated_marker_feed_and_binds_once(self):
        f = self.fixture(*MAPS[-1])
        f.add_manager(2, True)
        self.assertTrue(f.tick())
        self.assertIsNone(f.game_state.r_MinimapManager)
        local_manager = f.add_manager(2)
        self.assertTrue(f.tick())
        self.assertTrue(f.tick())
        self.assertEqual(f.game_state.r_MinimapManager.GetAddress(), local_manager.GetAddress())
        self.assertEqual((f.data_binds, f.data_rows), (1, 2))

    def test_preserves_existing_manager_and_leaves_ambiguous_feed_alone(self):
        f = self.fixture(*MAPS[-1])
        f.add_manager(2)
        existing = f.add_manager(3)
        self.assertTrue(f.tick())
        self.assertIsNone(f.game_state.r_MinimapManager)
        f.game_state.r_MinimapManager = existing
        self.assertTrue(f.tick())
        self.assertEqual(f.game_state.r_MinimapManager.GetAddress(), existing.GetAddress())
        self.assertIsNone(f.data_binds)

    def test_two_radars_per_team_bind_once_after_both_pairs_arrive(self):
        f = self.fixture(*MAPS[-1], radar_count=2)
        f.add_radars()
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.RadarSensors.children, 0)
        # The native widget drew the first two replicated sensors between ticks.
        f.widget.RadarSensors.children = 2
        f.add_radars()
        self.assertTrue(f.tick())
        self.assertTrue(f.tick())
        self.assertEqual((f.widget.RadarSensors.children, f.binds), (4, 1))
        self.assertEqual(f.widget.DetectionRange, 42500)

    def test_client_team_radar_recovers_from_individual_replication_updates(self):
        f = self.fixture(*MAPS[-1], radar_count=2)
        f.add_teams()
        f.add_radars()
        self.assertTrue(f.tick())
        f.deactivate_sensor(1, True)
        self.assertFalse(f.teams[1].r_bIsRadarOnline)
        self.assertEqual(f.teams[1].notifications, 0)

        f.add_radars()
        self.assertTrue(f.tick())
        self.assertTrue(f.teams[1].r_bIsRadarOnline)
        self.assertEqual(f.teams[1].notifications, 1)
        f.deactivate_sensor(3, True)
        self.assertFalse(f.teams[1].r_bIsRadarOnline)
        f.deactivate_sensor(1, False)
        self.assertTrue(f.teams[1].r_bIsRadarOnline)
        f.deactivate_sensor(3, False)
        f.deactivate_sensor(3, True)
        self.assertTrue(f.teams[1].r_bIsRadarOnline)
        self.assertTrue(f.teams[2].r_bIsRadarOnline)
        self.assertEqual(f.teams[2].notifications, 0)
        self.assertEqual(f.teams[1].notifications, 2)

        f.radars[1].PoweredComp.r_bGeneratorPowered = False
        self.assertTrue(f.tick())
        self.assertFalse(f.teams[1].r_bIsRadarOnline)
        self.assertTrue(f.retire())
        f.deactivate_sensor(1, False)
        self.assertTrue(f.teams[1].r_bIsRadarOnline)

    def test_no_radar_map_keeps_the_minimap_by_default(self):
        f = self.fixture(*MAPS[-1], radar_count=0)
        f.add_radars()
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.visibility, 0)
        self.assertEqual(f.widget.RadarSensors.children, 0)
        self.assertEqual((f.requests, f.spawns), (1, 1))

    def test_only_local_minimap_is_collapsed_when_requested(self):
        f = self.fixture(*MAPS[-1], radar_count=0, hide=True)
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.visibility, 1)
        self.assertEqual((f.requests, f.spawns), (0, 0))
        f.widget.visibility = 0  # Native UI can reset the widget after initial setup.
        self.assertTrue(f.tick())
        self.assertEqual(f.widget.visibility, 1)

    def test_retail_and_map_owned_capture_keep_native_behavior(self):
        retail = self.fixture('Katabatic', 'Katabatic', 'Arena_Katabatic_P', 172000, retail=True)
        self.assertTrue(retail.tick())
        self.assertEqual(retail.spawns, 0)
        authored = self.fixture(*MAPS[1])
        authored.add_map_capture()
        self.assertTrue(authored.tick())
        self.assertEqual((authored.requests, authored.spawns), (0, 0))

    def test_waits_for_compatible_world_settings(self):
        f = self.fixture(*MAPS[2])
        f.settings_class = 'Class /Script/Engine.WorldSettings'
        self.assertFalse(f.tick())
        self.assertEqual(f.spawns, 0)
        f.settings_class = 'Class /Script/Valhalla.ValWorldSettings'
        self.assertTrue(f.tick())
        self.assertEqual(f.requests, 1)
