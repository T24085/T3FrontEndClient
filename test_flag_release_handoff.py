from pathlib import Path
import re
import unittest

from lupa.lua54 import LuaRuntime


class FlagReleaseHandoffTests(unittest.TestCase):
    def test_release_seeds_only_the_detached_network_flag(self):
        root = Path(__file__).resolve().parent
        module = (root / 'runtime-fixes/flag_release_handoff.lua').read_text()
        client = (root / 'lua/client.lua').read_text()
        self.assertIn('local flagReleaseFactory=(function()\n' + module + 'end)()', client)
        lua = LuaRuntime()
        lua.compile(re.sub(r'@@[A-Z0-9_]+@@', '"fixture"', client))
        exercise = lua.execute("""
            local function object()
                return {GetAddress = function(self) return self end}
            end
            local world, carrier, flag, parent, root = object(), object(), object(), object(), object()
            local wanted = {X = 94, Y = 0, Z = 30}
            local original = {X = 0, Y = 0, Z = 0}
            local movement = {Location = wanted}
            flag.ReplicatedMovement, flag.RootComponent, flag.r_HeldBy = movement, root, carrier
            flag.GetClass = function()
                return {GetFullName = function()
                    return 'BlueprintGeneratedClass /Game/Topaz/Pickups/BP_TopazPickup_Flag.BP_TopazPickup_Flag_C'
                end}
            end
            flag.GetWorld = function(self) return self.world end
            flag.HasAuthority = function(self) return self.authority end
            flag.GetOwner = function(self) return self.owner end
            flag.K2_GetActorLocation = function() return original end
            flag.world = world
            carrier.GetWorld = function() return nil end
            parent.GetOwner = function() return carrier end
            root.GetOwner = function() return flag end
            root.GetAttachParent = function(self) return self.parent end
            local writes = 0
            flag.K2_SetActorLocation = function(self, point, sweep, hit, teleport)
                assert(self == flag and point.X == wanted.X and point.Y == wanted.Y
                    and point.Z == wanted.Z and not sweep and teleport)
                writes = writes + 1
                return true
            end
            local time = 0
            function StaticFindObject()
                return {
                    GetTimeSeconds = function() return time end,
                    RebaseZeroOriginOntoLocal = function(_, actor, point)
                        assert(actor == flag)
                        return point
                    end,
                }
            end
            local attachment, movementUpdate
            function RegisterHook(path, before, after)
                if path:find('AttachmentReplication', 1, true) then attachment = before
                else movementUpdate = after end
                return 1, 2
            end
            function UnregisterHook() end
            local env = {
                world = world, valid = function(value) return value ~= nil end,
                scope = function() end, signature = function() end, report = function() end,
            }
            local context = {get = function() return flag end}
            local function receive(detach, delay)
                root.parent = parent
                attachment(context)
                if detach then root.parent = nil end
                time = time + (delay or 0)
                movementUpdate(context)
            end
            return function(factory)
                local service = factory(env)
                flag.owner = carrier; receive(true); flag.owner = nil
                flag.authority = true; receive(true); flag.authority = false
                flag.world = object(); receive(true); flag.world = world
                flag.r_HeldBy = nil; receive(true); flag.r_HeldBy = carrier
                receive(false)
                receive(true, 1)
                movement.Location = {X = 4000, Y = 0, Z = 0}
                receive(true)
                movement.Location = wanted
                assert(writes == 0)
                receive(true)
                movementUpdate(context)
                assert(writes == 1)
                assert(service.retire())
                receive(true)
                assert(writes == 1)
            end
        """)
        exercise(lua.execute(module))
