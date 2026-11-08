-- Initialize a detached flag proxy from its first authoritative movement update.
return function(env)
 local valid,scope,signature,report=env.valid,env.scope,env.signature,env.report
 local attach='/Script/Engine.Actor:OnRep_AttachmentReplication'
 local move='/Script/Engine.Actor:OnRep_ReplicatedMovement'
 local flagClass='BlueprintGeneratedClass /Game/Topaz/Pickups/BP_TopazPickup_Flag.BP_TopazPickup_Flag_C'
 local world=env.world
 local active,reported=true,false
 local pending={}
 local function same(a,b)return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()end
 local function bounded_vector(v)
  return type(v.X)=='number' and math.abs(v.X)<1e8
   and type(v.Y)=='number' and math.abs(v.Y)<1e8
   and type(v.Z)=='number' and math.abs(v.Z)<1e8
 end
 signature(attach,{})
 signature(move,{})
 signature('/Script/Engine.Actor:K2_SetActorLocation',{{'NewLocation','StructProperty',0},{'bSweep','BoolProperty',24},
  {'SweepHitResult','StructProperty',32},{'bTeleport','BoolProperty',264},{'ReturnValue','BoolProperty',265}})
 signature('/Script/Engine.GameplayStatics:RebaseZeroOriginOntoLocal',{{'WorldContextObject','ObjectProperty',0},
  {'WorldLocation','StructProperty',8},{'ReturnValue','StructProperty',32}})
 signature('/Script/Engine.GameplayStatics:GetTimeSeconds',{{'WorldContextObject','ObjectProperty',0},{'ReturnValue','DoubleProperty',8}})
 local statics=StaticFindObject('/Script/Engine.Default__GameplayStatics')
 assert(valid(statics),'flag_release_native_world_rebase_required')
 local function before_attach(context)
  local flag=context:get()
  if not active or not valid(flag) or flag:GetClass():GetFullName()~=flagClass
     or flag:HasAuthority() or not same(flag:GetWorld(),world) then return end
  scope()
  local root,holder=flag.RootComponent,flag.r_HeldBy
  if not valid(root) or not same(root:GetOwner(),flag) or not valid(root:GetAttachParent())
     or not valid(holder) then return end
  pending[flag:GetAddress()]={flag=flag,root=root,at=statics:GetTimeSeconds(world)}
 end
 local function on_movement(context)
  local flag=context:get()
  if not active or not valid(flag) then return end
  local id=flag:GetAddress()
  local release=pending[id]
  if not release then return end
  pending[id]=nil
  if not same(flag,release.flag) or not same(flag.RootComponent,release.root)
     or valid(release.root:GetAttachParent()) or valid(flag:GetOwner())
     or statics:GetTimeSeconds(world)-release.at>0.20 then return end
  local location=flag.ReplicatedMovement.Location
  if not bounded_vector(location) then return end
  local to=statics:RebaseZeroOriginOntoLocal(flag,{X=location.X,Y=location.Y,Z=location.Z})
  if not bounded_vector(to) then return end
  local from=flag:K2_GetActorLocation()
  local distance=(to.X-from.X)^2+(to.Y-from.Y)^2+(to.Z-from.Z)^2
  if distance<1 or distance>300^2 then return end
  if flag:K2_SetActorLocation({X=to.X,Y=to.Y,Z=to.Z},false,{},true) and not reported then
   reported=true
   report('FLAG_RELEASE_POSITION_SEEDED|distanceCm='..string.format('%.1f',math.sqrt(distance)))
  end
 end
 local function guarded(fn)
  return function(...)
   local ok,why=pcall(fn,...)
   if not ok and active then
    active=false;pending={}
    report('FLAG_RELEASE_HANDOFF_UNAVAILABLE|'..tostring(why))
   end
  end
 end
 local pre,post=RegisterHook(attach,guarded(before_attach),function()end)
 local ok,mp,mq=pcall(RegisterHook,move,function()end,guarded(on_movement))
 if not ok then UnregisterHook(attach,pre,post);error(mp) end
 return {retire=function()
  active=false;pending={}
  local detach=pcall(UnregisterHook,attach,pre,post)
  local movement=pcall(UnregisterHook,move,mp,mq)
  return detach and movement
 end}
end
