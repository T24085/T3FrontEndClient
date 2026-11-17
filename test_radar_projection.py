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
local f={captures={},radars={},meshes={},requests=0,spawns=0,reports={}}
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
local pc=object(descriptor.world..'PersistentLevel.PlayerController');pc.world=world
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
function StaticFindObject(path)
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
widget.Material=object('Map material')
widget.MapTexture={Brush={ResourceObject=widget.Material}}
widget.CachedZoom,widget.TargetZoom=1,1
widget.RadarSensors={children=0,GetChildrenCount=function(self) return self.children end}
function widget:GetOwningPlayer() return pc end
function widget:UpdateSublevel() self.CachedMapScale=1024/settings.MapSize;self.MapScale=self.CachedMapScale end
function widget:BindRadarSensors() self.RadarSensors.children=2 end
function FindAllOf(klass)
    return ({BP_MinimapCapture_C=f.captures,StaticMeshActor=f.meshes,UI_Game_Map_C={widget},
        BP_Objective_RadarSensor_C=f.radars})[klass]
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
function f.add_radars()
    for team=1,2 do
        local radar=object('Radar sensor');radar.world=world;radar.r_TeamId=team
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
f.widget=widget
return f
'''


class RadarProjectionTest(unittest.TestCase):
    def fixture(self, map_id, group, level, size, *, retail=False):
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
