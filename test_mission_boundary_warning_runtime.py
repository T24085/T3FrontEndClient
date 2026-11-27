"""Behaviour tests for the boundary warning runtime, ported from Tribes3MapTool (T24085)."""
"""Run the warning service with a moving local player and game-shaped UI."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


class MissionBoundaryWarningTest(unittest.TestCase):
    def test_crossing_warns_locally_and_reentry_and_travel_clear_the_hud(self):
        runtime = LuaRuntime()
        source = Path(__file__).parent / "runtime-fixes/mission_boundary_warning.lua"
        factory = runtime.execute(source.read_text(encoding="utf-8"))
        runtime.execute(r"""
        return function(factory)
         local stamp, timer, reports = 10, nil, {}
         local world, foreign = {}, {}
         local function object(name, owner, tags)
          local row = {tags=tags or {}}
          row.GetFullName=function()return name end
          row.GetAddress=function()return row end
          row.GetWorld=function()return owner end
          row.ActorHasTag=function(_,tag)return row.tags[tag]==true end
          row.K2_GetActorLocation=function()return row.point end
          return row
         end
         world,foreign=object('World'),object('OtherWorld')
         local flag, panel = object('Flags',world), object('Canvas',world)
         flag.GetParent=function()return panel end
         local canvasClass, textClass = {}, {}
         panel.IsA=function(_,class)return class==canvasClass end
         local slot={}
         for _,fn in ipairs({'SetAnchors','SetAlignment','SetAutoSize','SetPosition','SetZOrder'})do
          slot[fn]=function()end
         end
         panel.AddChildToCanvas=function(_,label)label.parent=panel;return slot end
         local overlay=object('/Engine/Transient.HUD',world)
         overlay.Flags=flag
         local created,removed,current=0,0,nil
         StaticConstructObject=function(class,owner)
          assert(class==textClass and owner==overlay)
          created=created+1
          local row=object('Label',world)
          row.GetParent=function()return row.parent end
          row.RemoveFromParent=function()row.parent=nil;removed=removed+1;current=nil end
          row.SetText=function(_,text)current=text end
          for _,fn in ipairs({'SetShadowOffset','SetVisibility','SetColorAndOpacity','SetShadowColorAndOpacity'})do
           row[fn]=function()end
          end
          return row
         end
         local noticePath='/Script/Engine.PlayerController:ClientMessage'
         local characterClass,pawnClass,primitiveClass={},{},{}
         local nativeFields={
          [noticePath]={{'S','StrProperty',0},{'Type','NameProperty',16},{'MsgLifeTime','FloatProperty',24}},
          ['/Script/Engine.Actor:GetAttachParentActor']={{'ReturnValue','ObjectProperty',0}},
          ['/Script/Engine.PrimitiveComponent:GetCollisionObjectType']={{'ReturnValue','ByteProperty',0}},
         }
         StaticFindObject=function(path)
          if nativeFields[path] then
           local method=object('Function '..path,world)
           method.ForEachProperty=function(_,callback)
            for _,p in ipairs(nativeFields[path])do
             callback({GetFullName=function()return p[2]..' '..path..':'..p[1]end,
                       GetOffset_Internal=function()return p[3]end})
            end
           end
           return method
          end
          return ({['/Script/UMG.TextBlock']=textClass,['/Script/UMG.CanvasPanel']=canvasClass,
                   ['/Script/Valhalla.ValCharacter']=characterClass,['/Script/Engine.Pawn']=pawnClass,
                   ['/Script/Engine.PrimitiveComponent']=primitiveClass})[path]
         end
         local rpc
         RegisterHook=function(path,_,callback)
          assert(path==noticePath)
          rpc=callback
          return 1,2
         end
         FText=function(text)return text end
         FName=function(name)return name end
         local cue=object('Sound',world,{
          T3MissionWarningCue=true,T3MissionWarningCount8=true,T3MissionWarningCeiling=true,
         })
         local plays=0
         cue.AudioComponent={GetOwner=function()return cue end,Sound={},Play=function(_,offset)
          assert(offset==0);plays=plays+1
         end}
         local points={}
         for i,p in ipairs({{-10,-10},{10,-10},{10,10},{2,10},{2,0},{-2,0},{-2,10},{-10,10}}) do
          local marker=object('Vertex'..i,world,{T3MissionWarning=true,
                                                ['T3MissionWarningVertex'..i]=true})
          marker.point={X=p[1],Y=p[2],Z=0}
          points[i]=marker
         end
         local cap=object('Cap',world,{T3MissionWarning=true,T3MissionWarningCeiling=true})
         cap.point={X=0,Y=0,Z=10}
         points[#points+1]=cap
         local foreignCue=object('Foreign',foreign,{T3MissionWarningCue=true})
         FindAllOf=function(kind)
          return ({AmbientSound={cue,foreignCue},TargetPoint=points,UI_Game_Overlays_C={overlay}})[kind]
         end
         local ps,pawn,pc=object('PS',world),object('Pawn',world),object('PC',world)
         pc.PlayerState,pc.Pawn=ps,pawn
         pc.IsLocalPlayerController=function()return true end
         pawn.IsA=function(_,cls)return cls==characterClass or cls==pawnClass end
         pawn.GetAttachParentActor=function()return pawn.mount end
         ExecuteInGameThreadWithDelay=function(ms,fn)assert(ms==100 and not timer);timer=fn;return 1 end
         local function at(x,y,z)
          pawn.point={X=x,Y=y,Z=z}
          local fn=assert(timer,reports[#reports]);timer=nil;fn()
         end
         local service=factory({valid=function(value)return value~=nil end,scope=function()end,
                                report=function(event)reports[#reports+1]=event end,now=function()return stamp end})
         service(pc,ps)
         at(-5,0,0);at(5,0,0) -- Touching the notch edge is legal.
         assert(plays==0 and created==0)
         at(5,8,0);at(-5,8,0) -- Cross outside and back between samples.
         assert(plays==1 and created==1 and current:find('OUT OF BOUNDS',1,true))
         stamp=14
         at(-5,8,0)
         assert(removed==1)
         at(-5,8,11);at(-5,8,14)
         assert(plays==2 and created==2)
         at(-5,8,2)
         assert(removed==2)
         at(-5,8,14)
         ps.r_bDead=true;at(-5,8,14)
         assert(plays==3 and removed==3)
         ps.r_bDead=false;at(-5,8,14)
         assert(plays==3 and created==4) -- Outside on a new life is not a crossing.
         pc.GetWorld=function()return foreign end
         at(-5,8,14)
         assert(removed==4 and not timer)
         assert(#reports==4 and reports[1]=='MISSION_BOUNDARY_WARNING_READY')

         local flagMin=object('Flag limit',world,{T3MissionFlagMin=true})
         FindAllOf=function(kind)
          return ({AmbientSound={},TargetPoint={flagMin},UI_Game_Overlays_C={overlay}})[kind]
         end
         local nextPC=object('Next Controller',world)
         nextPC.PlayerState,nextPC.Pawn=ps,pawn
         nextPC.IsLocalPlayerController=pc.IsLocalPlayerController
         service(nextPC,ps)
         at(0,0,0)
         local function notice(target,tag)
          rpc({get=function()return target end},nil,{get=function()
           return {ToString=function()return tag end}
          end})
         end
         notice(pc,'T3FlagBoundaryDrop')
         notice(nextPC,'UnrelatedMessage')
         at(0,0,0)
         assert(not current and plays==3)
         notice(nextPC,'T3FlagBoundaryDrop')
         at(0,0,0)
         assert(current=='FLAG DROPPED AT THE MISSION BOUNDARY')
         notice(nextPC,'T3FlagBoundaryReturn')
         at(0,0,0)
         assert(current:find('FLAG RETURNED HOME',1,true)==1)
         stamp=19
         at(0,0,0)
         assert(not current and plays==3)
         notice(pc,'T3FlagBoundaryGrace')
         at(0,0,0)
         assert(not current)
         notice(nextPC,'T3FlagBoundaryGrace')
         at(0,0,0)
         assert(current and current:find('FLAG RETURN TIMER ACTIVE',1,true))
         notice(nextPC,'T3FlagBoundaryGraceCleared')
         at(0,0,0)
         assert(not current and plays==3)

         local vehicle, spectator=object('Vehicle',world),object('Spectator',world)
         vehicle.IsA=function(_,cls)return cls==pawnClass end
         spectator.IsA=vehicle.IsA
         vehicle.RootComponent={IsA=function(_,cls)return cls==primitiveClass end,
                                GetOwner=function()return vehicle end,GetCollisionObjectType=function()return 6 end}
         table.insert(points,flagMin)
         FindAllOf=function(kind)
          return ({AmbientSound={cue},TargetPoint=points,UI_Game_Overlays_C={overlay}})[kind]
         end
         cue.tags.T3MissionWarningCue=nil
         cue.tags.T3MissionWarningFilteredCue=true
         cue.tags.T3MissionWarningWarnVehicle=true
         local function change_controller(name)
          local controller=object(name,world)
          controller.PlayerState,controller.Pawn=ps,pawn
          controller.IsLocalPlayerController=pc.IsLocalPlayerController
          timer=nil -- Like travel, replace the old world's scheduled tick.
          service(controller,ps)
          return controller
         end
         local vehiclePC=change_controller('Vehicle PC')
         at(0,0,0);at(0,0,11)
         assert(not current and plays==3)
         pawn.mount=vehicle
         vehicle.point={X=0,Y=0,Z=0}
         at(0,0,11)
         assert(not current and plays==3) -- Uses the vehicle position rather than the attached pawn.
         vehicle.point.Z=11;at(0,0,0)
         assert(current and plays==4)
         pawn.mount=nil
         at(0,0,11)
         assert(not current and plays==4)
         vehiclePC.Pawn=vehicle
         at(0,0,0)
         assert(current and plays==4) -- Possessing an already-outside vehicle is not a crossing.
         vehicle.point.Z=0;at(0,0,0)
         vehicle.point.Z=11;at(0,0,0)
         assert(current and plays==5)
         vehiclePC.Pawn=spectator
         at(0,0,0)
         assert(not current and plays==5)

         cue.tags.T3MissionWarningWarnVehicle=nil
         cue.tags.T3MissionWarningWarnFoot=true
         change_controller('Foot PC')
         at(0,0,0);at(0,0,11)
         assert(current and plays==6)
         pawn.mount=vehicle
         at(0,0,11)
         assert(not current and plays==6)
         pawn.mount=nil
         at(0,0,11)
         assert(current and plays==6)

         cue.tags.T3MissionWarningWarnVehicle=true
         local flagPC=change_controller('Flag PC')
         assert(reports[#reports]:find('invalid_boundary_warning_audience',1,true))
         notice(flagPC,'T3FlagBoundaryDrop')
         at(0,0,11)
         assert(current=='FLAG DROPPED AT THE MISSION BOUNDARY' and plays==6)
        end
        """)(factory)
