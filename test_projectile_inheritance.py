from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lupa.lua54 import LuaRuntime

from client_entry import install_projectile_runtime
from community_transport import (PROJECTILE_INHERITANCE_CLASSES, projectile_runtime_lua,
                                 projectile_settings_payload)
from player_profile import load_projectile_settings, update_projectile_settings
from tools.build_starter_update import client_entry_payload


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT/'runtime-fixes/projectile_inheritance.lua'
LUA_FIXTURE = r"""
local function object(addr)
 local o={address=addr}
 function o:GetAddress() return self.address end
 function o:GetWorld() return self.world end
 return o
end
world, other_world=object(100),object(101)
local function shooter(address,addr,local_player)
 local pc,pawn,ps=object(addr),object(addr+1),object(addr+2)
 pc.Pawn, pc.PlayerState=pawn,ps
 function pc:IsLocalPlayerController() return local_player end
 ps.PawnPrivate,ps.SavedNetworkAddress=pawn,address
 pawn.world,pawn.Controller=world,pc
 return pc
end
owner=shooter('127.0.0.2',10,true)
remote=shooter('127.0.0.2',20,false)
other=shooter('127.0.0.3',30,false)
function valid(o) return o~=nil end
function scope() end
function signature(path,fields)
 assert(path:match('FinishSpawningProjectile$') and fields[3][3]==112)
end
local events={}
function report(line) events[#events+1]=line end
function RegisterHook(_,pre,post) invoke, finish=pre, post end
function shot(pc, class_name, selected, authority, over_limit)
 local actor=object(200)
 actor.world,actor.Instigator=selected or world,pc.Pawn
 actor.ProjectileVelocityInheritanceCategory=42
 actor.InheritForwardVelocityPercent,actor.InheritLateralVelocityPercent=.9,.8
 function actor:HasAuthority() return authority~=false end
 function actor:GetClass() return {GetFullName=function() return class_name end} end
 actor.ProjectileMovement={MaxSpeed=100,Velocity={X=120,Y=90,Z=0}}
 local arg={get=function() return actor end}
 invoke(nil,arg)
 finish(nil,arg)
 if over_limit then
  local v=actor.ProjectileMovement.Velocity
  return v.X,v.Y,v.Z,#events
 end
 return actor.ProjectileVelocityInheritanceCategory,actor.InheritForwardVelocityPercent,actor.InheritLateralVelocityPercent,#events
end
"""

def class_name(weapon):
    return 'BlueprintGeneratedClass ' + PROJECTILE_INHERITANCE_CLASSES[weapon]


class ProjectileRuntimeTests(unittest.TestCase):
    def test_only_configured_projectile_instances_change_for_the_admitted_remote_or_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'127.0.0.2.txt'
            preferences = {'lightspinfusor': [25, 10], 'spinfusor': [80, 30],
                           'grenadelauncher': [0, 100]}
            path.write_bytes(projectile_settings_payload(preferences))
            runtime = RUNTIME.read_text(encoding='utf-8')
            for options, binding, player, unowned in (
                ({'directory': root.as_posix()}, "world,nil,{['127.0.0.2']=1}", 'remote', 'other'),
                ({'file': path.as_posix()}, 'world,owner', 'owner', 'remote'),
            ):
                lua = LuaRuntime(unpack_returned_tuples=True)
                lua.execute(LUA_FIXTURE)
                lua.execute(projectile_runtime_lua(runtime, **options)
                            + f'applyProjectileInheritance({binding})')
                env = lua.globals()
                stock = (42, .9, .8, 0)
                for weapon, (forward, lateral) in preferences.items():
                    self.assertEqual(env.shot(env[player], class_name(weapon)),
                                     (0, forward / 100, lateral / 100, 0))
                self.assertEqual(env.shot(env[unowned], class_name('lightspinfusor')), stock)
                self.assertEqual(env.shot(env[player], class_name('thumper')), stock)
                self.assertEqual(env.shot(env[player], class_name('thumper'), env.world, True, True), (120, 90, 0, 0))
                expected_velocity = (80, 60, 0, 0) if player == 'owner' else (120, 90, 0, 0)
                result = env.shot(env[player], class_name('lightspinfusor'), env.world, True, True)
                for actual, expected in zip(result, expected_velocity):
                    self.assertAlmostEqual(actual, expected)
                self.assertEqual(env.shot(env[player], class_name('lightspinfusor'), env.other_world), stock)
                self.assertEqual(env.shot(env[player], class_name('lightspinfusor'), env.world, False), stock)

    def test_full_template_and_existing_signed_updater_entry_receive_the_same_runtime(self):
        source = (ROOT/'client_entry.py').read_bytes()
        payload = client_entry_payload(source, ROOT)
        namespace = {}
        exec(compile(payload, 'client.py', 'exec'), namespace)
        self.assertEqual(namespace['_SIGNED_PROJECTILE_INHERITANCE_MODULE'], RUNTIME.read_text(encoding='utf-8'))
        raw = (ROOT/'lua/client.lua').read_text(encoding='utf-8')
        settings = {'grenadelauncher': [0, 100]}
        for render in (install_projectile_runtime, namespace['install_projectile_runtime']):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                result = render(raw, root, settings)
                self.assertIn('applyProjectileInheritance(gs:GetWorld(),pc)', result)
                self.assertEqual((root/'projectile-inheritance.txt').read_bytes(),
                                 b'T3PROJECTILE1\ngrenadelauncher|0|100\n')

    def test_settings_reopen_and_reset_without_touching_the_retail_options(self):
        with tempfile.TemporaryDirectory() as folder, patch('player_profile.user_profile_root', return_value=Path(folder)):
            self.assertEqual(load_projectile_settings(), {})
            previous = {'spinfusor': [30, 70]}
            update_projectile_settings('spinfusor', [30, 70])
            self.assertEqual(load_projectile_settings(), previous)
            with self.assertRaises(ValueError):
                update_projectile_settings('spinfusor', [-1, 70])
            self.assertEqual(load_projectile_settings(), previous)
            update_projectile_settings('grenadelauncher', [40, 15])
            update_projectile_settings('spinfusor', None)
            self.assertEqual(load_projectile_settings(), {'grenadelauncher': [40, 15]})
