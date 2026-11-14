import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from lupa.lua54 import LuaError, LuaRuntime

from client_entry import write_map_definitions
from community_maps import BY_ID, MapDefinition


ROOT = Path(__file__).resolve().parent
KATA = MapDefinition('KatabaticT22026', 'Kata', 'KatabaticT2', 'Arena_KatabaticT2_2026_P')
BLIZZARD = BY_ID['SnowblindBlizzard2026']
DESCRIPTOR = '''
return {descriptor=function(row)
 row.weather={kind="snow",density=.5,speed=325,color={.2,.4,1},
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
        path.parent.mkdir()
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

    def test_uninventoried_adapter_is_ignored_and_changed_bytes_are_rejected(self):
        row = self.add_adapter(DESCRIPTOR)
        self.assertIsNone(self.catalog([])[KATA.id].weather)
        self.run = self.root / 'corrupt'
        self.run.mkdir()
        (self.root / row['path']).write_text('return {}')
        with self.assertRaisesRegex(ValueError, 'failed package verification'):
            self.catalog([row])

    def test_legacy_stub_loads_generic_runtime_and_options_affect_cooked_actors(self):
        for kind in ('snow', 'rain', 'ash'):
            with self.subTest(kind=kind):
                self.run = self.root / kind
                self.run.mkdir()
                name = f'lua/{KATA.id}/objectives.lua'
                path = self.root / name
                path.parent.mkdir(exist_ok=True)
                raw = DESCRIPTOR.replace('kind="snow"', f'kind="{kind}"').encode()
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
            function a:K2_TeleportTo(p)self.z=p.Z;return true end
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
          nextTick();local before=actors[2].z;t=1;nextTick()
          assert(math.abs(before-actors[2].z - 325*217/280)<.001)
        ''')

    def test_adapter_has_no_engine_or_filesystem_globals(self):
        with self.assertRaises(LuaError):
            self.catalog([self.add_adapter('return io.open("unexpected")')])
