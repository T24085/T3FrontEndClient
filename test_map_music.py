from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from lupa.lua54 import LuaRuntime

from client_entry import write_map_definitions
from community_maps import MapDefinition
from map_soundtracks import REMOTE_TRACKS, fetch_track
from tools.build_starter_update import soundtrack_entry


ROOT = Path(__file__).resolve().parent
MAP = MapDefinition('HildebrandT2', 'Hildebrand', 'HildebrandT2', 'Arena_HildebrandT2_P')
SOURCE = '/Game/Community/HildebrandT2/Audio/'
DESCRIPTOR = """
return {format=1,map_id="HildebrandT2", package="%s", world="%s",
        music={track="%s"}, sound_set="T2"}
"""
PLAYBACK = r'''

local function object(id)
 local o={id=id}
 function o:GetAddress() return self.id end
 return o
end
local busPath='/Game/Audio/Submixes/MUS_Game_Submix.MUS_Game_Submix'
local bus=object(1)
function bus:GetFullName() return 'SoundSubmix '..busPath end
function bus:SetSubmixOutputVolume(_,gain) bus.gain=gain end
local world=object(2)
pc=object(3)
function pc:GetWorld() return world end
gs=object(4)
local phase='GamePhase.GameplayStartPhase'
local ended=false
function set_phase(value) phase=value end
function end_match(value) ended=value end
function gs:HasMatchEnded() return ended end
gs.r_GameplayPhaseInfo={Phase={TagName={ToString=function() return phase end}}}
function gs:GetFullName() return '/Game/TestWorld.TestWorld:PersistentLevel.GameState' end
local function valid(x) return type(x)=='table' end
local function same_object(a,b) return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() end
local function signature() end
local reports={}
local function report(line) reports[#reports+1]=line end
local function wave(path, submix)
 local a={bEnableBaseSubmix=true,SoundSubmixObject=submix}
 function a:GetFullName() return 'SoundWave '..path end
 return a
end
local sounds={
 ['/Game/Community/Test/Override.Override']=wave('/Game/Community/Test/Override.Override', {}),
 ['/Game/Community/Test/Selected.Selected']=wave('/Game/Community/Test/Selected.Selected', bus),
 ['/Game/Community/Test/Default.Default']=wave('/Game/Community/Test/Default.Default',bus),
}
local scan_path='/Game/Community/Test/Selected.Selected'
local scan_count=0
local function LoadAsset(path)
 if path==scan_path and scan_count==0 then return nil,false end
 return path==busPath and bus or sounds[path]
end
local registry={}
function registry:ScanFilesSynchronous(paths,force)
 assert(#paths==1 and paths[1]=='/Game/Community/Test/Selected.uasset' and force==false)
 scan_count=scan_count+1
end
local helpers={}
function helpers:GetAssetRegistry() return registry end
function scanned_files() return scan_count end
local function component(id,sound)
 local c=object(id)
 c.active,c.Sound=true,sound
 function c:GetWorld() return world end
 function c:IsPlaying() return self.active end
 function c:Stop() self.active=false end
 function c:SetVolumeMultiplier(gain) self.gain=gain end
 function c:SetPaused(value) self.paused=value end
 return c
end
stock=component(5,wave('/Game/Audio/Stock.Stock',bus))
effect=component(6,wave('/Game/Audio/Effects.Effects',nil))
local function FindAllOf() return {stock,effect,last} end
local creates=0
playing={}
local statics={}
function statics:SpawnSound2D(context,sound,volume,pitch,start,concurrency,persist,destroy)
 assert(context==pc and volume>=0 and persist==false and destroy==true)
 creates=creates+1
 last=component(6+creates,sound)
 last.gain=volume
 playing[#playing+1]=last
 return last
end
local function loaded(path)
 if path=='/Script/AssetRegistry.Default__AssetRegistryHelpers' then return helpers end
 return statics
end
local mapDefinitions={test={world='/Game/TestWorld.TestWorld:',music_route='t2_desert',
 music_candidates={
   {asset='/Game/Community/Test/Override.Override',volume=0.4,pitch=1},
   {asset='/Game/Community/Test/Selected.Selected',volume=0.8,pitch=1},
   {asset='/Game/Community/Test/Default.Default',volume=1,pitch=1},
 } }}
function remove_declaration() mapDefinitions.test.music_route,mapDefinitions.test.music_candidates=nil,nil end
function mute_level() return bus.gain end
function use_legacy() mapDefinitions.test.music_candidates=nil end
function replace_world() world=object(19) end

'''


class MapMusicTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root/'lua').mkdir()
        self.run = self.root/'run'
        self.run.mkdir()
        shutil.copyfile(ROOT/'lua/community_maps.lua', self.root/'lua/community_maps.lua')

    def row(self, name, raw):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {'path': name, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}

    def test_verified_descriptor_layers_native_tracks(self):
        event = 'AUD_MUS.Level.Desert'
        selected = {
            'format': 1, 'kind': 'pack', 'set': 'T2',
            'events': [{'id': event, 'category': 'mus',
                        'graph': {'kind': 'looping', 'children': [
                            {'kind': 'wave', 'asset': SOURCE+'Selected'}]}}],
            'bindings': {'music.match': {'event': event, 'pitch': 0.9}},
        }
        default = {
            'format': 1, 'kind': 'pack', 'set': 'T3',
            'bindings': {'music.match': {'assets': [SOURCE+'Silent', SOURCE+'Default'],
                                         'weights': [0, 1]}},
        }
        override = {
            'format': 1, 'kind': 'map-override', 'set': 'T2', 'map_id': MAP.id,
            'bindings': {'music.match': {'asset': SOURCE+'Override.Override', 'volume': 0.4}},
        }
        world = f'{MAP.package}.{MAP.level}:'
        descriptor = DESCRIPTOR % (MAP.package, world, 'music.match')
        files = [
            self.row(f'lua/{MAP.id}/objectives.lua', descriptor.encode()),
            self.row('sound-packs/T2/pack.json', json.dumps(selected).encode()),
            self.row('sound-packs/T3/pack.json', json.dumps(default).encode()),
            self.row(f'sound-packs/maps/{MAP.id}/override.json', json.dumps(override).encode()),
        ]
        path = write_map_definitions(self.root, self.run, {MAP.id: MAP}, MAP, {'files': files})
        result = LuaRuntime().execute(path.read_text(encoding='utf-8'))[MAP.id]
        self.assertIsNone(result.music_route)
        self.assertEqual([result.music_candidates[i].asset for i in range(1, 4)],
                         [SOURCE+f'{name}.{name}' for name in ('Override', 'Selected', 'Default')])
        self.assertAlmostEqual(result.music_candidates[1].volume, 0.4)
        self.assertAlmostEqual(result.music_candidates[2].pitch, 0.9)

    def test_corrupt_map_override_preserves_verified_legacy_track(self):
        world = f'{MAP.package}.{MAP.level}:'
        descriptor = DESCRIPTOR % (MAP.package, world, 't2-desert')
        override = f'sound-packs/maps/{MAP.id}/override.json'
        files = [
            self.row(f'lua/{MAP.id}/objectives.lua', descriptor.encode()),
            self.row(override, b'{}'),
        ]
        (self.root/override).write_bytes(b'[]')
        path = write_map_definitions(self.root, self.run, {MAP.id: MAP}, MAP, {'files': files})
        result = LuaRuntime().execute(path.read_text(encoding='utf-8'))[MAP.id]
        self.assertEqual(result.music_route, 't2_desert')
        self.assertIsNone(result.music_candidates)

    def test_native_music_falls_through_incompatible_asset_and_cleans_up_at_match_end(self):
        config = self.root/'audio.ini'
        config.write_text('SavedSettingsConfig=("MusicSoundVolume","0.5"),("MasterSoundVolume","0.25")\n')
        source = (ROOT/'lua/client.lua').read_text(encoding='utf-8')
        start = source.index('local update_match_music=(function()')
        end = source.index('local shieldWallPreviewChecked', start)
        body = source[start:end].replace('@@MAP_SOUNDTRACK@@', '{routes={}}')
        body = body.replace('@@MUSIC_SETTINGS@@', json.dumps(config.as_posix()))
        lua = LuaRuntime()
        tick = lua.execute(PLAYBACK+body+'return update_match_music')
        env = lua.globals()
        tick(env.pc, env.gs)
        selected = env.playing[1]
        self.assertEqual(selected.Sound.GetFullName(selected.Sound), 'SoundWave /Game/Community/Test/Selected.Selected')
        self.assertAlmostEqual(selected.gain, .4)
        self.assertEqual(env.scanned_files(), 1)
        self.assertTrue(env.stock.paused)
        self.assertIsNone(env.effect.paused)
        self.assertIsNone(env.mute_level())
        env.end_match(True)
        tick(env.pc, env.gs)
        self.assertFalse(selected.active)
        self.assertFalse(env.stock.paused)
        env.end_match(False)
        env.remove_declaration()
        tick(env.pc, env.gs)
        self.assertIsNone(env.playing[2])

    def test_legacy_music_clears_before_restarting_same_track_in_a_new_world(self):
        config = self.root/'audio.ini'
        config.write_text('SavedSettingsConfig=("MusicSoundVolume","0.5"),("MasterSoundVolume","0.25")\n')
        source = (ROOT/'lua/client.lua').read_text(encoding='utf-8')
        start = source.index('local update_match_music=(function()')
        end = source.index('local shieldWallPreviewChecked', start)
        playback = '{directory='+json.dumps(self.run.as_posix())+',routes={t2_desert=true}}'
        body = source[start:end].replace('@@MAP_SOUNDTRACK@@', playback)
        body = body.replace('@@MUSIC_SETTINGS@@', json.dumps(config.as_posix()))
        lua = LuaRuntime()
        tick = lua.execute(PLAYBACK+body+'return update_match_music')
        env = lua.globals()
        env.use_legacy()
        request = self.run/'map-soundtrack-request'
        ready = self.run/'map-soundtrack-ready'
        tick(env.pc, env.gs)
        self.assertEqual(request.read_text(), 't2_desert 125 0')
        ready.write_text(f't2_desert {env.os.time()}')
        tick(env.pc, env.gs)
        self.assertEqual(request.read_text(), 't2_desert 125 1')
        env.replace_world()
        tick(env.pc, env.gs)
        self.assertEqual(request.read_text(), '')
        ready.unlink()
        tick(env.pc, env.gs)
        self.assertEqual(request.read_text(), 't2_desert 125 0')

    def test_signed_entry_embeds_the_same_legacy_track_pins(self):
        canonical = (ROOT/'client_entry.py').read_bytes()
        output = soundtrack_entry(canonical, ROOT)
        compile(output, 'client.py', 'exec')
        self.assertIn(b'_SIGNED_SOUNDTRACK_PLAYER = soundtrack_player', output)
        self.assertEqual(len(REMOTE_TRACKS), 16)
        raw = b'fixture'
        pin = sha256(raw).hexdigest()
        track = fetch_track(lambda name, size: raw, [(pin, len(raw))], pin)
        self.assertEqual(track, raw)
        with self.assertRaises(ValueError):
            fetch_track(lambda name, size: b'corrupt', [(pin, len(raw))], pin)
