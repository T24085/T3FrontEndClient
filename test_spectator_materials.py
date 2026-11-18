"""Exercise late armor changes through the spectator presentation module."""
from pathlib import Path
import unittest

try:
    from lupa.lua54 import LuaRuntime
except ImportError:
    LuaRuntime = None


@unittest.skipUnless(LuaRuntime, "requires Lua 5.4 via lupa")
class SpectatorMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute("""
        local nextAddress=0
        local function object()
          nextAddress=nextAddress+1
          return {address=nextAddress, live=true,
                  IsValid=function(self) return self.live end,
                  GetAddress=function(self) return self.address end,
                  GetFullName=function(self) return 'Object '..self.address end,
                  IsA=function(self,cls) return self.Parent~=nil and cls=='/Script/Engine.MaterialInstanceDynamic' end}
        end
        local world=object()
        local function getWorld() return world end
        local function yes() return true end
        local function no() return false end
        local function component(owner)
          local o=object()
          o.GetOwner=function() return owner end
          o.GetWorld=getWorld
          o.slots={}
          o.GetNumMaterials=function(self) return self.count or #self.slots end
          o.GetMaterial=function(self,index) return self.slots[index+1] end
          o.SetMaterial=function(self,index,value) self.slots[index+1]=value end
          return o
        end
        local function material(parent,texture)
          local o=object()
          o.Parent=parent
          o.texture=texture
          o.scalar=1
          o.CopyParameterOverrides=function(self,source)
            self.scalar=source.scalar
            self.texture=source.texture
          end
          o.K2_GetScalarParameterValue=function(self) return self.scalar end
          o.SetScalarParameterValue=function(self,_,value) self.scalar=value end
          return o
        end
        local function field(name,fullName,offset)
          return {ForEachProperty=function(_,visit)
            visit({GetFName=function() return {ToString=function() return name end} end,
                   GetFullName=function() return fullName end,
                   GetOffset_Internal=function() return offset end,
                   GetPropertyClass=function() return {GetFullName=function() return 'Class /Script/Engine.MaterialInterface' end} end})
          end}
        end
        local library=object()
        library.CreateDynamicMaterialInstance=function(_,_,parent,name)
          assert(type(name)=='userdata')
          return material(parent)
        end
        local objects={
          ['/Script/Valhalla.ValCharacter']=field('IsLocallyViewed1pParam','NameProperty /Script/Valhalla.ValCharacter:IsLocallyViewed1pParam',1896),
          ['/Script/Engine.PrimitiveComponent']=field('bOwnerNoSee','BoolProperty /Script/Engine.PrimitiveComponent:bOwnerNoSee',724),
          ['/Script/Engine.MaterialInstance']=field('Parent','ObjectProperty /Script/Engine.MaterialInstance:Parent'),
          ['/Script/Engine.Default__KismetMaterialLibrary']=library
        }
        local nameHandle=assert(io.tmpfile())
        function FName() return nameHandle end
        function StaticFindObject(path) return objects[path] or path end

        target=object()
        target.PlayerState=object()
        target.PlayerState.PawnPrivate=target
        target.GetWorld=getWorld
        target.HasAuthority=no
        target.GetMesh3P=function() return mesh end
        target.GetGunMesh3P=function() return nil end
        target.UpdateMeshVisibility=function() end
        target.IsLocallyViewed1pParam={ToString=function() return 'ViewMode' end}
        mesh=component(target)
        original=material(object(),'default')
        replacement=material(object(),'selected')
        mesh.slots={original,original}
        mesh.count=2
        local pc=object()
        pc.PlayerState=object()
        pc.PlayerState.GetWorld=getWorld
        pc.PlayerState.IsOnlyASpectator=yes
        pc.IsLocalPlayerController=yes
        pc.HasAuthority=no
        pc.GetWorld=getWorld
        pc.GetViewTarget=function() return target end
        local pawn=component(pc)
        pawn.Controller=pc
        pc.GetSpectatorPawn=function() return pawn end
        keepers={}
        pawn.AddComponentByClass=function()
          local keeper=component(pawn)
          keeper.K2_DestroyComponent=function(self) self.live=false end
          keepers[#keepers+1]=keeper
          return keeper
        end
        function replaceMesh()
          mesh.live=false
          mesh=component(target)
          mesh.slots={replacement}
        end
        clock=1
        env={pc=pc,valid=function(o) return type(o)=='table' and o:IsValid() end,
             scope=function() end,signature=function() end,report=function() end,
             now=function() return clock end}
        """)
        path = Path(__file__).resolve().parent / "lua/spectator_materials.lua"
        self.lua.globals().factory = self.lua.execute(path.read_text(encoding="utf-8"))
        self.lua.execute("policy=factory(env)")

    def test_native_replacement_while_watching_preserves_selected_skin(self):
        self.lua.execute("""
        policy.apply(target,true)
        assert(mesh.slots[1]~=original and mesh.slots[2]~=original)
        mesh.slots[1]=replacement
        policy.poll(target,true)
        assert(not keepers[1].live and keepers[2].live)
        assert(mesh.slots[1].Parent==replacement.Parent and mesh.slots[1].texture=='selected')
        assert(mesh.slots[1].scalar==0 and mesh.slots[2].scalar==0)
        assert(policy.retire())
        assert(mesh.slots[1]==replacement and mesh.slots[2]==original and not keepers[2].live)
        """)

    def test_late_texture_override_keeps_chase_presentation(self):
        self.lua.execute("""
        policy.apply(target,true)
        local clone=mesh.slots[1]
        original.texture='selected later'
        clock=2
        policy.poll(target,true)
        assert(mesh.slots[1]==clone and clone.texture=='selected later')
        assert(clone.scalar==0 and original.scalar==1)
        policy.apply(target,false)
        assert(clone.scalar==1)
        """)

    def test_wait_for_missing_slot_and_rebind_after_mesh_replacement(self):
        self.lua.execute("""
        mesh.slots[2]=nil
        policy.apply(target,true)
        assert(#keepers==0 and mesh.slots[1]==original)
        mesh.slots[2]=original
        policy.poll(target,true)
        assert(#keepers==1 and keepers[1].live)
        replaceMesh()
        policy.poll(target,true)
        assert(#keepers==2 and not keepers[1].live and keepers[2].live)
        assert(mesh.slots[1].texture=='selected' and mesh.slots[1].scalar==0)
        assert(policy.retire() and mesh.slots[1]==replacement)
        """)
