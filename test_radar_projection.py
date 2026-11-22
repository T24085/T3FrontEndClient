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
local f={captures={},radars={},meshes={},requests=0,spawns=0,updates=0,reports={}}
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
f.target=target
local function capture_component(capture,width)
    local component={ProjectionType=1,TextureTarget=target,OrthoWidth=width}
    function component:GetOwner() return capture end
    function component:CaptureScene() f.requests=f.requests+1 end
    function component:K2_GetComponentLocation() return {X=150,Y=300,Z=100000} end
    return component
end
local api=object('GameplayStatics /Script/Engine.Default__GameplayStatics')
function api:BeginDeferredActorSpawnFromClass(context,klass,transform)
    assert(context==pc and klass:GetFullName():find('BP_MinimapCapture_C',1,true))
    f.spawns=f.spawns+1;f.height=transform.Translation.Z;f.origin=transform.Translation
    local capture=object('MinimapCapture');capture.world=world
    local component=capture_component(capture)
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
    if path=='/Script/Engine.Default__KismetRenderingLibrary' then
        local renderer=object('KismetRenderingLibrary '..path)
        function renderer:ImportFileAsTexture2D(context,name)
            assert(context==pc)
            if name=='valid.png' then f.png=object(name);return f.png end
        end
        return renderer
    end
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
local function slot()
    local s={position={X=0,Y=0},size={X=150,Y=150},alignment={X=0,Y=0},
             anchors={Minimum={X=0,Y=0},Maximum={X=0,Y=0}},automatic=true,writes=0}
    function s:SetPosition(value) self.position=value;self.writes=self.writes+1 end
    function s:SetSize(value) self.size=value;self.writes=self.writes+1 end
    function s:SetAlignment(value) self.alignment=value;self.writes=self.writes+1 end
    function s:SetAnchors(value) self.anchors=value;self.writes=self.writes+1 end
    function s:SetAutoSize(value) self.automatic=value;self.writes=self.writes+1 end
    function s:GetSize() return self.size end
    function s:GetAutoSize() return self.automatic end
    function s:GetLayout()
        return {Anchors=self.anchors,Alignment=self.alignment,
                Offsets={Left=self.position.X,Top=self.position.Y,Right=self.size.X,Bottom=self.size.Y}}
    end
    return s
end
widget.MapTexture={Brush={ResourceObject=widget.Material},Slot=slot(),visibility=4}
function widget.MapTexture:SetBrushFromTexture(texture,matchSize)
    assert(not matchSize)
    if f.reject_png_brush then return end
    self.Brush.ResourceObject=texture
end
function widget.MapTexture:SetVisibility(value) self.visibility=value end
function widget.MapTexture:GetVisibility() return self.visibility end
widget.EmptyTexture={SetVisibility=widget.MapTexture.SetVisibility,GetVisibility=widget.MapTexture.GetVisibility,visibility=1}
f.frame=slot()
local wrapper=object('minimap root')
function wrapper:GetClass()
    return object('WidgetBlueprintGeneratedClass /Game/UI/Components/Game/UI_Game_MiniMap.UI_Game_MiniMap_C')
end
wrapper.RetainerBox_0={Slot=f.frame}
f.retainer=wrapper.RetainerBox_0
function widget:GetOuter() return {GetOuter=function()return wrapper end} end
widget.CachedZoom,widget.TargetZoom=1,1
widget.DefaultMinZoom,widget.DefaultMaxZoom,widget.DefaultZoom=1,3,1
widget.CachedMapRotationAngle=0
function widget:RotateMapToVector(v)
    self.CachedMapRotationAngle=(math.deg(math.atan(v.Y,v.X))-90)%360
end
function widget:UpdateScale(delta)
    assert(delta==0)
    self.MapScale=self.DefaultZoom*self.CachedMapScale
end
function widget:UpdateTranslation(delta,interpolate)
    assert(delta==0 and not interpolate)
    self.CachedMapTranslation=self.TargetTranslation
end
function f.vector(x,y) return {X=x,Y=y} end
function widget:UpdateTexture()
    f.updates=f.updates+1
    if f.delayed_material then return end
    assert(self.MinimapCapture)
    self.MapTexture.Brush.ResourceObject=self.Material
    self.MapTexture:SetVisibility(4)
    self.EmptyTexture:SetVisibility(1)
end
widget.RadarSensors={children=0,GetChildrenCount=function(self) return self.children end}
function widget.RadarSensors:GetChildAt() return {GetClass=function()return radarWidgetClass end} end
function widget.RadarSensors:ClearChildren() self.children=0 end
function widget:GetOwningPlayer() return pc end
function widget:UpdateSublevel() self.CachedMapScale=1024/settings.MapSize;self.MapScale=self.CachedMapScale end
function widget:BindRadarSensors() self.RadarSensors.children=#f.radars;f.binds=(f.binds or 0)+1 end
local foreignWidget=object('Foreign map widget');foreignWidget.world=foreign
foreignWidget.GetOwningPlayer=widget.GetOwningPlayer
function foreignWidget:SetVisibility() error('foreign minimap changed') end
local otherPlayerWidget=object('Other player map widget');otherPlayerWidget.world=world
function otherPlayerWidget:GetOwningPlayer() return otherPlayerWidget end
otherPlayerWidget.SetVisibility=foreignWidget.SetVisibility
function FindAllOf(klass)
    return ({BP_MinimapCapture_C=f.captures,StaticMeshActor=f.meshes,UI_Game_Map_C={widget,foreignWidget,otherPlayerWidget},
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
function f.add_map_capture(width)
    local capture=object('authored capture');capture.world=world;f.captures[1]=capture
    f.component=capture_component(capture,width or authored)
    capture.SceneCaptureComponent2D=f.component
    if not width then f.component.TextureTarget=object('Alternate native capture target') end
end
function f.blank(clear_brush)
    widget.MapTexture:SetVisibility(1)
    widget.EmptyTexture:SetVisibility(4)
    if clear_brush then widget.MapTexture.Brush.ResourceObject=nil end
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
    def fixture(self, map_id, group, level, size, *, retail=False, radar_count=None, hide=False, minimap=None):
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
        if minimap:
            row.minimap = lua.execute("return " + minimap)
        lua.globals().descriptor = row
        lua.globals().authored = size
        start = SOURCE.index('local function community_radar_group(')
        end = SOURCE.index('local releaseRadarRuntime=releaseRadarRuntimeFactory(', start)
        return lua.execute(SOURCE[start:end] + FIXTURE)

    def test_authored_frame_and_png_share_the_native_world_projection(self):
        f = self.fixture(*MAPS[-1], minimap=(
            "{center={1500,-4000},extent={90000,60000},scale=1.5,rotation_deg=35,"
            "zoom={min=.5,max=2,default=1.4},frame={width=420,height=260},"
            "image_file='valid.png',image_bounds={{-1000,-3000},{60000,21000}}}"
        ))
        self.assertTrue(f.tick())
        self.assertEqual((f.origin.X, f.origin.Y), (1500, -4000))
        self.assertEqual(f.component.OrthoWidth, 60000)
        world_to_canvas = 1024 / 60000
        self.assertAlmostEqual(f.widget.MapScale, world_to_canvas)
        self.assertAlmostEqual(f.widget.CachedZoom, 1.7)
        self.assertAlmostEqual(f.widget.DefaultMinZoom, 1.25)
        self.assertAlmostEqual(f.widget.DefaultMaxZoom, 2)
        self.assertAlmostEqual(f.widget.CachedMapRotationAngle, 35)
        self.assertEqual((f.frame.size.X, f.frame.size.Y), (420, 260))
        art = f.widget.MapTexture.Slot
        self.assertAlmostEqual(art.size.X, 61000 * world_to_canvas)
        self.assertAlmostEqual(art.size.Y, 24000 * world_to_canvas)
        self.assertAlmostEqual(art.position.X, 29500 * world_to_canvas)
        self.assertAlmostEqual(art.position.Y, 9000 * world_to_canvas)
        self.assertAlmostEqual(f.widget.TargetTranslation.X, -1500 * world_to_canvas)
        self.assertEqual(f.widget.MapTexture.Brush.ResourceObject.GetFullName(f.widget.MapTexture.Brush.ResourceObject), 'valid.png')
        f.widget.TargetZoom = 1.8
        self.assertTrue(f.tick())
        self.assertAlmostEqual(f.widget.TargetZoom, 1.8)

    def test_png_import_failure_uses_the_aligned_live_capture(self):
        f = self.fixture(*MAPS[-1], minimap=(
            "{center={1000,2000},extent={60000,70000},image_file='unavailable.png',"
            "image_bounds={{0,0},{1000,1000}}}"
        ))
        self.assertTrue(f.tick())
        self.assertEqual(f.requests, 1)
        self.assertEqual(f.component.OrthoWidth, 70000)
        self.assertEqual(f.widget.MapTexture.Brush.ResourceObject.GetFullName(f.widget.MapTexture.Brush.ResourceObject), 'Map material')
        self.assertAlmostEqual(f.widget.MapTexture.Slot.size.X, 1024)
        self.assertAlmostEqual(f.widget.MapTexture.Slot.position.Y, 2000 * 1024 / 70000)
        self.assertTrue(any(line.startswith('MINIMAP_PNG_FALLBACK|') for line in f.reports.values()))

    def test_retries_late_slots_and_repairs_native_layout_resets_at_the_same_scale(self):
        f = self.fixture(*MAPS[-1], minimap=(
            "{frame={width=430,height=250},image_file='valid.png',"
            "image_bounds={{1000,-2000},{51000,18000}}}"
        ))
        art = f.widget.MapTexture.Slot
        f.widget.MapTexture.Slot, f.retainer.Slot = None, None
        self.assertFalse(f.tick())
        self.assertEqual((f.requests, f.frame.writes, art.writes), (0, 0, 0))
        f.widget.MapTexture.Slot, f.retainer.Slot = art, f.frame
        self.assertTrue(f.tick())
        scale = f.widget.MapScale
        self.assertEqual(f.requests, 1)
        self.assertEqual((f.frame.size.X, f.frame.size.Y), (430, 250))
        self.assertAlmostEqual(art.size.X, 50000 * scale)
        self.assertAlmostEqual(art.size.Y, 20000 * scale)
        self.assertAlmostEqual(art.position.X, 26000 * scale)
        self.assertAlmostEqual(art.position.Y, 8000 * scale)

        f.frame.size.X, f.frame.automatic = 310, True
        art.anchors.Maximum.X, art.position.Y = 1, -55
        art.automatic = True
        f.blank(True)
        self.assertTrue(f.tick())
        self.assertEqual((f.frame.size.X, f.frame.size.Y, f.frame.automatic), (430, 250, False))
        self.assertEqual((art.anchors.Minimum.X, art.anchors.Maximum.X, art.automatic), (.5, .5, False))
        self.assertAlmostEqual(art.position.Y, 8000 * scale)
        writes = (f.frame.writes, art.writes)
        self.assertTrue(f.tick())
        self.assertEqual((f.frame.writes, art.writes), writes)

    def test_authored_center_recovers_without_overwriting_manual_pan(self):
        f = self.fixture(*MAPS[-1], minimap="{center={1500,-4000}}")
        f.widget.DefaultRadar = True
        f.widget.TargetTranslation = f.vector(12, 25)
        self.assertTrue(f.tick())
        self.assertEqual((f.widget.TargetTranslation.X, f.widget.TargetTranslation.Y), (12, 25))

        f.widget.DefaultRadar = False
        self.assertTrue(f.tick())
        offset = (-1500 * f.widget.MapScale, 4000 * f.widget.MapScale)
        self.assertEqual((f.widget.TargetTranslation.X, f.widget.TargetTranslation.Y), offset)

        f.widget.DefaultMapTranslation = f.vector(0, 0)
        f.widget.TargetTranslation = f.vector(0, 0)
        self.assertTrue(f.tick())
        self.assertEqual((f.widget.TargetTranslation.X, f.widget.TargetTranslation.Y), offset)

        f.widget.DefaultMapTranslation = f.vector(0, 0)
        f.widget.TargetTranslation = f.vector(33, 77)
        self.assertTrue(f.tick())
        self.assertEqual((f.widget.TargetTranslation.X, f.widget.TargetTranslation.Y), (33, 77))
        self.assertEqual((f.widget.DefaultMapTranslation.X, f.widget.DefaultMapTranslation.Y), offset)

    def test_png_brush_rejection_clears_the_placeholder_using_the_native_capture(self):
        f = self.fixture(*MAPS[-1], minimap="{image_file='valid.png',image_bounds={{0,0},{1000,1000}}}")
        self.assertTrue(f.tick())
        self.assertAlmostEqual(f.widget.MapTexture.Slot.size.X, 1000 * 1024 / MAPS[-1][-1])
        f.blank(True)
        f.reject_png_brush = True
        self.assertTrue(f.tick())
        self.assertEqual((f.requests, f.updates), (1, 1))
        self.assertEqual(f.widget.MapTexture.Brush.ResourceObject.GetFullName(f.widget.MapTexture.Brush.ResourceObject),
                         'Map material')
        self.assertAlmostEqual(f.widget.MapTexture.Slot.size.X, 1024)
        self.assertTrue(any(line.startswith('MINIMAP_BRUSH_FALLBACK|') for line in f.reports.values()))

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

    def test_live_background_repairs_the_native_placeholder_and_retries_delayed_material(self):
        f = self.fixture(*MAPS[-1])
        f.blank(True)
        f.delayed_material = True
        self.assertFalse(f.tick())
        self.assertEqual((f.spawns, f.requests, f.updates), (1, 0, 1))
        f.delayed_material = False
        self.assertTrue(f.tick())
        self.assertEqual((f.spawns, f.requests, f.updates), (1, 1, 2))
        self.assertEqual((f.widget.MapTexture.visibility, f.widget.EmptyTexture.visibility), (4, 1))
        f.blank(False)
        f.widget.MinimapCapture = None
        self.assertTrue(f.tick())
        self.assertEqual((f.requests, f.updates), (1, 3))
        self.assertEqual((f.widget.MapTexture.visibility, f.widget.EmptyTexture.visibility), (4, 1))

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

    def test_existing_capture_refreshes_native_material_without_changing_authored_framing(self):
        f = self.fixture(*MAPS[1])
        f.add_map_capture(125000)
        f.blank(True)
        f.component.TextureTarget = None
        self.assertFalse(f.tick())
        self.assertEqual((f.requests, f.spawns, f.updates), (0, 0, 0))
        f.component.TextureTarget = f.target
        self.assertTrue(f.tick())
        self.assertEqual((f.requests, f.spawns, f.updates), (1, 0, 1))
        self.assertEqual(f.component.OrthoWidth, 125000)
        self.assertAlmostEqual(f.widget.CachedMapScale, 1024 / MAPS[1][-1])
        self.assertEqual((f.widget.MapTexture.visibility, f.widget.EmptyTexture.visibility), (4, 1))

    def test_waits_for_compatible_world_settings(self):
        f = self.fixture(*MAPS[2])
        f.settings_class = 'Class /Script/Engine.WorldSettings'
        self.assertFalse(f.tick())
        self.assertEqual(f.spawns, 0)
        f.settings_class = 'Class /Script/Valhalla.ValWorldSettings'
        self.assertTrue(f.tick())
        self.assertEqual(f.requests, 1)
