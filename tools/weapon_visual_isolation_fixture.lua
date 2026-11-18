local f={queue={},releases=0,events={},pressed=true}
local id=0
local function obj(name)
 id=id+1;local a={name=name,id=id}
 function a:IsValid()return true end
 function a:GetAddress()return self.id end
 function a:GetFullName()return self.name end
 function a:GetWorld()return f.world end
 return a
end
f.world=obj('World');f.pc=obj('PC');f.ps=obj('PS');f.pawn=obj('Pawn');f.asc=obj('ASC')
f.pc.Pawn=f.pawn;f.pawn.Controller=f.pc;f.pawn.PlayerState=f.ps;f.pawn.bInitialized=true;f.pawn.AbilitySystemComponent=f.asc
function f.pc:IsLocalPlayerController()return true end
function f.pc:HasAuthority()return false end
function f.asc:GetOwner()return f.pawn end
function f.pawn:GetActiveEquippedAbility()return{Handle=16}end
local master=obj('BlueprintGeneratedClass /Game/Abilities/Devices/Gun/GA_Gun_Master.GA_Gun_Master_C')
local reload=obj('BlueprintGeneratedClass /Game/Abilities/Devices/Gun/GA_Gun_Master_Reload.GA_Gun_Master_Reload_C')
function StaticFindObject(path)if path:find('_Reload',1,true)then return reload else return master end end
local ability=obj('Ability');function ability:IsA(c)return c==master end
local none={ForEach=function()end}
f.asc.ActivatableAbilities={Items={}}
function f.asc.ActivatableAbilities.Items:ForEach(cb)cb(1,{get=function()return{InputID=5,InputPressed=f.pressed,Ability=ability,Handle={Handle=16},ActiveCount=0,NonReplicatedInstances=none,ReplicatedInstances=none}end})end
function f.asc:ServerSetInputReleased(handle)assert(handle.Handle==16);f.releases=f.releases+1 end
function ExecuteInGameThreadWithDelay(ms,callback)assert(ms==25);f.queue[#f.queue+1]=callback end
f.env={valid=function(o)return o~=nil and o:IsValid()end,scope=function()end,signature=function()end,report=function(s)f.events[#f.events+1]=s end,
 observeVisuals=function()error('candidate_visual_failure')end}
function f.tick()local callback=table.remove(f.queue,1);assert(callback);callback()end
return f
