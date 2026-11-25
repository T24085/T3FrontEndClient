"""Exercise the actual client startup and join callbacks without a Settings widget."""
from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = Path(__file__).with_name('lua').joinpath('client.lua').read_text(encoding='utf-8')


class StartupAudioTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        match = SOURCE[SOURCE.index('local function same_object('):].split('\nend', 1)[0] + '\nend'
        sound = SOURCE[SOURCE.index('local soundSettingsWorld'):SOURCE.index('local update_match_music=')]
        tick = SOURCE[SOURCE.index('local function client_tick('):SOURCE.index('\nlocal schedule\n')]
        tick = (tick.replace('@@SPECTATOR_RUNTIME@@', '"spectator fixture"')
                .replace('@@SPECTATOR_MATERIAL_RUNTIME@@', '"materials fixture"'))
        self.runtime = self.lua.execute('''
local observations = {calls=0, applied=0, joined=0, events={}, order={}, fail=false, master=1}
local function object(world)
    return {
        IsValid=function() return true end,
        GetAddress=function(self) return self end,
        GetWorld=function() return world end
    }
end
local function valid(o) return o ~= nil and o:IsValid() end
local function report(value) table.insert(observations.events,value) end
local MODE, DESTINATION, SPECTATOR_ROLE = 'expected CTF mode','local fixture','spectator'
local joined = false
local bootstrap = object(object())
bootstrap.GetClass = function() return {GetFullName=function() return MODE end} end
bootstrap.GetFullName = function() return '/Game/Maps/Active/Drydock/Arena_Drydock_P.Arena_Drydock_P:' end
bootstrap.HasAuthority = function() return true end
local world = object()
local gs, pc
local function travel()
    world = object()
    gs = object(world)
    gs.GetFullName = function() return 'fixture match' end
    gs.HasAuthority = function() return false end
    pc = object(world)
    pc.IsLocalPlayerController = function() return true end
    pc.HasAuthority = function() return false end
end
travel()
local function state() return gs end
local function FindAllOf(class)
    if class == 'TopGameMode_Topaz' then return {bootstrap} end
    if class == 'ValPlayerController' then return {pc} end
    error('unexpected class '..class)
end
local function signature() end
local class = object()
local settings = object()
settings.IsA = function(_, candidate) return candidate == class end
settings.ApplySoundSettings = function()
    observations.calls = observations.calls + 1
    assert(not observations.fail, 'audio device not ready')
    observations.applied = observations.applied + 1
    observations.master = .25
    table.insert(observations.order,'apply')
end
local function loaded(path)
    if path == '/Script/Engine.Default__GameUserSettings' then
        return {GetGameUserSettings=function() return settings end}
    elseif path == '/Script/Valhalla.ValGameUserSettings' then
        return class
    elseif path == '/Script/Engine.Default__GameplayStatics' then
        return {OpenLevel=function()
            observations.joined = observations.joined + 1
            table.insert(observations.order,'join')
        end}
    end
    error('unexpected object '..path)
end
local function FName(text) return {ToString=function() return text end} end
local function noop() end
local configure_perimeter = noop
local configure_geometry, configure_community_lighting, configure_stock_clouds = noop, noop, noop
local configure_weather, configure_base_lighting, configure_water = noop, noop, noop
local configure_draft_interior_lighting = noop
local spectatorRuntime = {tick=noop}
local sys = {IsStandalone=function() return true end}
''' + match + '\n' + sound + '\n' + tick + '''
return {
    tick=function() client_tick(sys) end,
    travel=travel,
    player_mode=function() SPECTATOR_ROLE='player' end,
    player_ready=function()
        pc.Pawn=object(world)
        pc.Pawn.bInitialized=true
        -- Simulate the native mixer returning to its default during spawn.
        observations.master=1
    end,
    spectator_ready=function() pc.PlayerState=object(world) end,
    lagging_controller=function() pc.GetWorld=function() return bootstrap:GetWorld() end end,
    observed=observations
}
''')

    def test_applies_before_travel_and_again_on_join_before_player_state_or_pawn(self):
        runtime = self.runtime
        runtime.tick()
        self.assertEqual(list(runtime.observed.order.values()), ['apply', 'join'])
        runtime.lagging_controller()
        runtime.tick()
        self.assertEqual(runtime.observed.calls, 1)
        runtime.travel()
        runtime.tick()
        self.assertEqual(runtime.observed.calls, 2)
        runtime.spectator_ready()
        runtime.tick()
        runtime.tick()
        self.assertEqual(runtime.observed.applied, 3)
        self.assertEqual(list(runtime.observed.events.values()).count('SAVED_SOUND_SETTINGS_APPLIED_READY'), 1)

    def test_player_ready_restores_saved_levels_after_native_spawn_resets_the_mix(self):
        runtime = self.runtime
        runtime.player_mode()
        runtime.tick()
        runtime.tick()
        self.assertEqual(runtime.observed.master, .25)

        runtime.player_ready()
        self.assertEqual(runtime.observed.master, 1)
        runtime.tick()
        self.assertEqual(runtime.observed.master, .25)

        runtime.tick()
        self.assertEqual(runtime.observed.calls, 3)

    def test_retries_failed_application_until_success_without_reapplying_afterward(self):
        runtime = self.runtime
        runtime.tick()
        runtime.observed.fail = True
        runtime.tick()
        self.assertEqual(runtime.observed.applied, 1)
        runtime.observed.fail = False
        runtime.tick()
        runtime.tick()
        self.assertEqual(runtime.observed.calls, 3)
        self.assertEqual(runtime.observed.applied, 2)

    def test_persistent_failure_is_bounded_and_new_world_gets_a_fresh_attempt(self):
        runtime = self.runtime
        runtime.tick()
        runtime.observed.fail = True
        for _ in range(20):
            runtime.tick()
        calls = runtime.observed.calls
        self.assertEqual(calls, 11)
        failures = [entry for entry in runtime.observed.events.values() if 'SAVED_SOUND_SETTINGS_UNAVAILABLE' in entry]
        self.assertEqual(len(failures), 1)
        runtime.observed.fail = False
        runtime.travel()
        runtime.tick()
        self.assertEqual(runtime.observed.calls, calls + 1)
        self.assertEqual(runtime.observed.applied, 2)
