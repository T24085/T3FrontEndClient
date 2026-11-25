import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from lupa.lua54 import LuaRuntime

from client_entry import weather_runtime_path, write_map_definitions
from community_maps import BY_ID, MapDefinition


ROOT = Path(__file__).resolve().parent
KATA = MapDefinition('KatabaticT22026', 'Kata', 'KatabaticT2', 'Arena_KatabaticT2_2026_P')
BLIZZARD = BY_ID['SnowblindBlizzard2026']
DESCRIPTOR = '''
return {descriptor=function(row)
 row.weather={kind="snow",density=.5,speed=325,color={.2,.4,1},wind={125,-60},
              actors={{actor="Snow00",index=0},{actor="Snow01",index=1}}}
 row.objectives={server_only=true}
 return row
end}
'''


class PackagedMapWeatherTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.run = self.root / 'run'
        self.run.mkdir()
        (self.root / 'lua').mkdir()
        shutil.copyfile(ROOT / 'lua/community_maps.lua', self.root / 'lua/community_maps.lua')
        self.lua = LuaRuntime()
        self.definitions = {item.id: item for item in (KATA, BLIZZARD)}

    def add_adapter(self, source, definition=KATA):
        name = f'lua/{definition.id}/objectives.lua'
        path = self.root / name
        path.parent.mkdir(exist_ok=True)
        raw = source.encode()
        path.write_bytes(raw)
        return dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def catalog(self, rows, public=False):
        file = write_map_definitions(self.root, self.run, self.definitions, KATA, {'files': rows}, public=public)
        return self.lua.execute(file.read_text(encoding='utf-8'))

    def test_private_and_public_catalogs_use_the_packaged_descriptor(self):
        row = self.add_adapter(DESCRIPTOR)
        for public in (False, True):
            with self.subTest(public=public):
                self.run = self.root / str(public)
                self.run.mkdir()
                maps = self.catalog([row], public=public)
                kata = maps[KATA.id]
                self.assertEqual(kata.weather.kind, 'snow')
                self.assertEqual(kata.weather.density, .5)
                self.assertEqual(kata.weather.speed, 325)
                self.assertEqual(kata.weather.color[3], 1)
                self.assertIsNone(kata.objectives)
                self.assertEqual(maps[BLIZZARD.id].weather.kind, 'snow')

    def test_minimap_option_uses_the_same_verified_descriptors(self):
        for public in (False, True):
            with self.subTest(public=public):
                self.run = self.root / str(public)
                self.run.mkdir()
                if public:
                    source = f'''return {{format=1,map_id={KATA.id!r},package={KATA.package!r},
                      world={(KATA.package + '.' + KATA.level + ':')!r},
                      layout={{radars_per_team=0}},hide_minimap=true}}'''
                else:
                    source = '''return {descriptor=function(row)
                      row.base_layout={radars_per_team=0};row.hide_minimap=true;return row end}'''
                maps = self.catalog([self.add_adapter(source)], public=public)
                self.assertEqual(maps[KATA.id].radars_per_team, 0)
                self.assertTrue(maps[KATA.id].hide_minimap)
                self.assertIsNone(maps[BLIZZARD.id].hide_minimap)

    def test_private_and_public_catalogs_keep_authored_radar_counts(self):
        for public in (False, True):
            with self.subTest(public=public):
                self.run = self.root / str(public)
                self.run.mkdir()
                source = 'return {descriptor=function(row) row.base_layout={radars_per_team=2};return row end}'
                self.assertEqual(self.catalog([self.add_adapter(source)], public=public)[KATA.id].radars_per_team, 2)

    def test_hiding_is_ignored_when_descriptor_does_not_omit_radars(self):
        source = '''return {descriptor=function(row)
          row.base_layout={radars_per_team=1};row.hide_minimap=true;return row end}'''
        self.assertIsNone(self.catalog([self.add_adapter(source)])[KATA.id].hide_minimap)

    def test_uninventoried_adapter_is_ignored_and_changed_bytes_are_rejected(self):
        row = self.add_adapter(DESCRIPTOR)
        self.assertIsNone(self.catalog([])[KATA.id].weather)
        self.run = self.root / 'corrupt'
        self.run.mkdir()
        (self.root / row['path']).write_text('return {}')
        with self.assertRaisesRegex(ValueError, 'failed package verification'):
            self.catalog([row])

    def test_downloaded_objectives_override_bundled_and_signed_runtime_is_independent(self):
        module = (ROOT / 'lua/weather.lua').read_bytes()
        with patch('client_entry._SIGNED_WEATHER_MODULE', module):
            runtime = weather_runtime_path(self.root, self.run, {'files': []})
            self.assertEqual(runtime, self.run / 'weather.lua')
            self.assertEqual(runtime.read_bytes(), module)
            self.run = self.root / 'packaged'
            self.run.mkdir()
            authored_off = self.add_adapter(DESCRIPTOR.replace('row.objectives=', 'row.weather=false;row.objectives='))
            name = authored_off['path']
            path = self.run / 'downloaded-objectives' / name
            path.parent.mkdir(parents=True)
            raw = DESCRIPTOR.encode()
            path.write_bytes(raw)
            downloaded = dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            output = write_map_definitions(self.root, self.run, self.definitions, KATA,
                                           {'files': [authored_off]}, objectives=[downloaded])
            self.assertEqual(self.lua.execute(output.read_text())[KATA.id].weather.kind, 'snow')
            package = {'files': [{'path': 'lua/weather.lua'}]}
            replacement = weather_runtime_path(self.root, self.run, package)
            self.assertEqual(replacement, self.run / 'weather.lua')
            self.assertEqual(replacement.read_bytes(), module)
        self.assertEqual(weather_runtime_path(self.root, self.run, package), self.root / 'lua/weather.lua')

    def test_legacy_stub_loads_generic_runtime_and_options_affect_cooked_actors(self):
        for kind in ('snow', 'rain', 'ash', 'wind'):
            with self.subTest(kind=kind):
                self.run = self.root / kind
                self.run.mkdir()
                name = f'lua/{KATA.id}/objectives.lua'
                path = self.root / name
                path.parent.mkdir(exist_ok=True)
                raw = DESCRIPTOR.replace('kind="snow"', f'kind="{kind}"').replace('color=', 'tint=').encode()
                path.write_bytes(raw)
                self.check_weather_runtime(dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))

    def check_weather_runtime(self, adapter):
        maps = self.catalog([adapter])
        self.lua.globals().maps = maps
        self.lua.globals().stub = (ROOT / 'lua/snowblind_weather.lua').as_posix()
        self.lua.execute('''
          local world={GetAddress=function()return 1 end}
          local row=maps.KatabaticT22026
          local pc={GetWorld=function()return world end,IsLocalPlayerController=function()return true end}
          pc.PlayerCameraManager={GetCameraLocation=function()return {X=0,Y=0,Z=0}end}
          local gs={GetWorld=pc.GetWorld,HasAuthority=function()return false end,
                    GetFullName=function()return row.world.."PersistentLevel.State"end}
          local actors={}
          for i=1,2 do
            local body={}
            function body:GetCollisionEnabled()return 0 end
            function body:SetVectorParameterValueOnMaterials(name,tint)
              assert(name=="WeatherColor" and tint.X==.2 and tint.Z==1);self.tinted=true
            end
            local a={bReplicates=false,StaticMeshComponent=body,GetWorld=pc.GetWorld}
            function a:GetFullName()return "StaticMeshActor "..row.world.."PersistentLevel.Snow0"..(i-1)end
            function a:SetActorHiddenInGame(hidden)self.hidden=hidden end
            function a:K2_TeleportTo(p)self.position=p;return true end
            actors[i]=a
          end
          function FindAllOf()return actors end
          function FName(n)return n end
          local t=0
          function StaticFindObject()return {GetTimeSeconds=function()return t end}end
          local nextTick
          function ExecuteInGameThreadWithDelay(_,callback)nextTick=callback end
          local config=assert(loadfile(stub))()({descriptors=maps,valid=function(x)return x~=nil end,
                    scope=function()end,report=function(line)assert(not line:find("_ERROR"))end})
          config(gs,pc)
          assert(actors[1].hidden and actors[2].StaticMeshComponent.tinted)
          nextTick();local before=actors[2].position;t=1;nextTick()
          local after=actors[2].position
          assert(after.X-before.X==125 and after.Y-before.Y==-60)
          local fall=row.weather.kind=='wind' and 0 or 325*217/280
          assert(math.abs(before.Z-after.Z-fall)<.001)
        ''')

    def test_exclusion_material_setup_and_opt_in_camera_fade(self):
        self.lua.globals().runtime = (ROOT / 'lua/weather.lua').as_posix()
        for count, fade in ((0, 'true'), (1, 'false'), (16, 'true')):
            with self.subTest(count=count, fade=fade):
                self.run = self.root / str(count)
                self.run.mkdir()
                boxes = ['{center_cm={100,-200,250},half_cm={5,20,30},yaw=90}']
                boxes += ['{center_cm={10000,10000,10000},half_cm={1,2,3},yaw=0}'] * 15
                descriptor = DESCRIPTOR.replace('row.objectives=',
                    f'row.weather.exclusions={{{",".join(boxes[:count])}}};'
                    f'row.weather.fade_when_camera_inside={fade};row.objectives=')
                self.lua.globals().maps = self.catalog([self.add_adapter(descriptor)])
                self.lua.execute('''
          local row=maps.KatabaticT22026
          local world={GetAddress=function()return 1 end}
          local getWorld=function()return world end
          local gs={GetWorld=getWorld,HasAuthority=function()return false end,
                    GetFullName=function()return row.world..'PersistentLevel.GS' end}
          local position={X=100,Y=-185,Z=250}
          local pc={GetWorld=getWorld,IsLocalPlayerController=function()return true end,
                    PlayerCameraManager={GetCameraLocation=function()return position end}}
          local actors={}
          for i=0,1 do
            local body={vectors={},writes=0,opacity={}}
            function body:GetCollisionEnabled()return 0 end
            function body:SetVectorParameterValueOnMaterials(name,value)
              assert(not self.vectors[name]);self.vectors[name]=value;self.writes=self.writes+1
            end
            function body:SetScalarParameterValueOnMaterials(name,value)
              assert(name=='WeatherOpacity');self.opacity[#self.opacity+1]=value
            end
            local actor={StaticMeshComponent=body,GetWorld=getWorld,
                         GetFullName=function()return 'StaticMeshActor '..row.world..'PersistentLevel.Snow0'..i end}
            function actor:SetActorHiddenInGame(hidden)self.hidden=hidden end
            function actor:K2_TeleportTo()return true end
            actors[i+1]=actor
          end
          local t,nextTick=0,nil
          function FindAllOf()return actors end
          function FName(name)return name end
          function StaticFindObject()return {GetTimeSeconds=function()return t end} end
          function ExecuteInGameThreadWithDelay(_,callback)nextTick=callback end
          local function step(delta)t=t+delta;nextTick() end
          local scan=assert(loadfile(runtime))()({descriptors=maps,valid=function(x)return x~=nil end,
                      scope=function()end,report=function(line)assert(not line:find('_ERROR'),line)end})
          scan(gs,pc);scan(gs,pc)
          local disabled,active=actors[1].StaticMeshComponent,actors[2].StaticMeshComponent
          assert(actors[1].hidden and disabled.writes==0 and #disabled.opacity==0)
          local count=#row.weather.exclusions
          local expectedWrites=1+3*count
          assert(active.writes==expectedWrites and not active.vectors['WeatherBox'..(count+1)..'_Center'])
          assert(active.vectors.WeatherColor.Z==1)
          if count>0 then
            local center=active.vectors.WeatherBox1_Center
            local half=active.vectors.WeatherBox1_Half
            local axis=active.vectors.WeatherBox1_Axis
            assert(center.X==100 and center.Y==-200 and center.Z==250)
            assert(half.X==5 and half.Y==20 and half.Z==30)
            assert(math.abs(axis.X)<1e-12 and axis.Y==1 and axis.Z==0)
          end
          if count==16 then assert(active.vectors.WeatherBox16_Half.Z==3) end
          step(0);step(.25)
          position={X=115,Y=-200,Z=250};step(.25);step(.25);step(.25)
          position.Z=281;step(.25);step(.25);step(.25)
          assert(active.writes==expectedWrites and not actors[2].hidden)
          if count>0 and row.weather.fade_when_camera_inside then
            local expected={1,.5,0,.5,1}
            assert(#active.opacity==#expected)
            for i,value in ipairs(expected)do assert(active.opacity[i]==value) end
          else
            assert(#active.opacity==0)
          end
                ''')

    def test_exclusions_reject_malformed_values_before_actor_setup(self):
        self.lua.globals().runtime = (ROOT / 'lua/weather.lua').as_posix()
        self.lua.execute('''
          local world={GetAddress=function()return 1 end}
          local gs={GetWorld=function()return world end,HasAuthority=function()return false end,
                    GetFullName=function()return 'Test:PersistentLevel.GS' end}
          local pc={GetWorld=gs.GetWorld,IsLocalPlayerController=function()return true end}
          function FindAllOf()error('unexpected actor setup') end
          local weather={kind='snow',actors={{actor='Snow00',index=0}}}
          local env={descriptors={{world='Test:',weather=weather}},valid=function(value)return value~=nil end,
                     report=function()end}
          local scan=assert(loadfile(runtime))()(env)
          local box={center_cm={0,0,0},half_cm={1,2,3},yaw=0}
          local function rejects(exclusions,fade,message)
            weather.exclusions=exclusions;weather.fade_when_camera_inside=fade
            local ok,err=pcall(scan,gs,pc)
            assert(not ok and err:find(message,1,true),err)
          end
          rejects('room',nil,'ordered_boxes')
          rejects({box,[3]=box},nil,'ordered_boxes')
          local tooMany={};for i=1,17 do tooMany[i]=box end
          rejects(tooMany,nil,'ordered_boxes')
          rejects({{center_cm={0/0,0,0},half_cm={1,2,3},yaw=0}},nil,'center_xyz')
          rejects({{center_cm={0,0,0},half_cm={1,2},yaw=0}},nil,'half_xyz')
          rejects({{center_cm={0,0,0},half_cm={1,2,math.huge},yaw=0}},nil,'half_xyz')
          rejects({{center_cm={0,0,0},half_cm={1,0,3},yaw=0}},nil,'positive_half_extents')
          rejects({{center_cm={0,0,0},half_cm={1,2,3},yaw='90'}},nil,'requires_yaw')
          rejects({},1,'fade_requires_boolean')
        ''')

    def test_static_descriptor_can_own_lighting_without_precipitation(self):
        world = f'{KATA.package}.{KATA.level}:'
        data = f'''
return {{format=1,map_id="{KATA.id}",package="{KATA.package}",world="{world}",
         weather={{kind="lighting",lighting={{actors={{"StormLight"}},intensity=2500}}}}}}
'''
        self.lua.globals().maps = self.catalog([self.add_adapter(data)])
        self.lua.globals().runtime = (ROOT / 'lua/weather.lua').as_posix()
        self.lua.execute('''
          local world={GetAddress=function()return 1 end}
          local row=maps.KatabaticT22026
          local pc={GetWorld=function()return world end,IsLocalPlayerController=function()return true end}
          local gs={GetWorld=pc.GetWorld,HasAuthority=function()return false end,
                    GetFullName=function()return row.world.."PersistentLevel.State" end}
          local light={Mobility=2,SetIntensity=function(self,value) self.intensity=value end}
          local actor={bReplicates=false,LightComponent=light,GetWorld=pc.GetWorld,
                       GetFullName=function()return "PointLight "..row.world.."PersistentLevel.StormLight" end}
          function FindAllOf(kind) assert(kind=="PointLight");return {actor} end
          function ExecuteInGameThreadWithDelay() error("lighting-only must not schedule precipitation") end
          local tick=assert(loadfile(runtime))()({descriptors=maps,valid=function(x)return x~=nil end,
                    scope=function()end,report=function()end})
          tick(gs,pc)
          assert(light.intensity==2500)
          light.intensity=1000
          tick(gs,pc)
          assert(light.intensity==1000)
        ''')

    def test_adapter_has_no_engine_or_filesystem_globals(self):
        adapter = self.add_adapter('return io.open("unexpected")')
        maps = self.catalog([adapter])
        self.assertIsNone(maps[KATA.id].weather)
        self.assertEqual(maps[BLIZZARD.id].weather.kind, 'snow')

    def test_packaged_lighting_opt_out_without_weather(self):
        descriptor = '''return {descriptor=function(row)
            row.emergency_lighting=false
            return row
        end}'''
        maps = self.catalog([self.add_adapter(descriptor)])
        self.assertIs(maps[KATA.id].emergency_lighting, False)
        self.assertIsNone(maps[KATA.id].weather)
