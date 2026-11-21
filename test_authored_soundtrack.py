from pathlib import Path
import tempfile
import unittest

from lupa.lua54 import LuaRuntime

from map_soundtracks import playlists


class AuthoredSoundtrackTest(unittest.TestCase):
    def test_route_targets_known_tracks_and_wraps_t1_playlist(self):
        routes = playlists()
        self.assertEqual(routes['t2_desert'], ('t2-desert.mp3',))
        self.assertEqual(routes['playlist_t1_8'][:4],
                         ('t1-08.mp3', 't1-09.mp3', 't1-10.mp3', 't1-01.mp3'))

    def test_warmup_prepares_music_and_countdown_allows_playback(self):
        text = Path(__file__).with_name('lua').joinpath('client.lua').read_text(encoding='utf-8')
        music = text.split('local update_match_music=', 1)[1].split('\nend)()', 1)[0] + '\nend)()'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            music = music.replace('@@MAP_SOUNDTRACK@@', '{directory=dir,routes={t2_desert=true}}')
            music = music.replace('@@MUSIC_SETTINGS@@', 'dir.."/settings.ini"')
            lua = LuaRuntime()
            lua.globals().dir = root.as_posix()
            lua.execute('''
world={}; now=1700; phase='GamePhase.Warmup'; volume=1
os.time=function() return now end
mapDefinitions={fixture={world='/Game/Fixture:',music_route='t2_desert'}}
function valid(value) return value~=nil end
function same_object(a,b) return a==b end
function signature() end
function report() end
function LoadAsset(path)
 return {GetFullName=function() return 'SoundSubmix '..path end,
         SetSubmixOutputVolume=function(self,player,gain) volume=gain end}
end
pc={GetWorld=function() return world end}
gs={GetFullName=function() return 'GameState /Game/Fixture:PersistentLevel.State' end,
    r_GameplayPhaseInfo={Phase={TagName={ToString=function() return phase end}}}}
''')
            lua.globals().tick = lua.execute('return ' + music)
            request = root / 'map-soundtrack-request'
            lua.execute('tick(pc,gs)')
            self.assertEqual(request.read_text(), 't2_desert 1000 0')
            (root / 'map-soundtrack-ready').write_text('t2_desert 1700')
            lua.execute('phase="GamePhase.GameplayStartPhase";tick(pc,gs)')
            self.assertEqual(request.read_text(), 't2_desert 1000 1')
            self.assertEqual(lua.globals().volume, 0)
            lua.execute('gs.GetFullName=function() return "Unmatched world" end; tick(pc,gs)')
            self.assertEqual(request.read_text(), '')
            self.assertEqual(lua.globals().volume, 1)
