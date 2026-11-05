-- Isolated normal-input diagnostic. Never writes a projectile or weapon stat.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 local role=assert(env.role);local world,pc,pawn,asc;local readyAt;local stopped=false;local hooks={};local count=0;local taps=0;local movingCount=0;local lastTap
 local path='/Game/Topaz/Abilities/Weapons/LightSpinfusor/BP_Projectile_Topaz_LightSpinfusor.BP_Projectile_Topaz_LightSpinfusor_C'
 local clock=StaticFindObject('/Script/Engine.Default__GameplayStatics')
 signature('/Script/Engine.GameplayStatics:GetTimeSeconds',{{'WorldContextObject','ObjectProperty',0},{'ReturnValue','DoubleProperty',8}})
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function now()return clock:GetTimeSeconds(world)end
 local function vector(v)return string.format('%.6f,%.6f,%.6f',v.X,v.Y,v.Z)end
 local function magnitude(v)return math.sqrt(v.X*v.X+v.Y*v.Y+v.Z*v.Z)end
 local function emit(kind,text)report('DISC_SPEED_'..kind..'|role='..role..'|time='..now()..'|'..text)end
 local function safe(fn)
  return function(...)
   if stopped then return end
   local ok,why=pcall(fn,...)
   if not ok then stopped=true;report('DISC_SPEED_ERROR|role='..role..'|'..tostring(why))end
  end
 end
 local function later(ms,fn)ExecuteInGameThreadWithDelay(ms,safe(function()scope();fn()end))end
 local function properties(object,label)
  local cls=object:GetClass();local seen={};local n=0
  for depth=1,6 do
   if not valid(cls)then break end
   cls:ForEachProperty(function(p)
    local name=p:GetFName():ToString()
    if not seen[name]and(name:find('Speed',1,true)or name:find('Inherit',1,true)or name:find('Gravity',1,true)or name:find('Predict',1,true)or name:find('Fake',1,true))then
     seen[name]=true;n=n+1;assert(n<=128,'disc_property_bound')
     local kind=p:GetFullName():match('^(%S+) ')
     if kind=='FloatProperty'or kind=='DoubleProperty'or kind=='BoolProperty'or kind=='IntProperty'then emit('PROPERTY','owner='..label..'|name='..name..'|value='..tostring(object[name]))end
    end
   end)
   cls=cls:GetSuperStruct()
  end
 end
 local function observe(_,_,arg)
  if not valid(world)then return end
  local actor=arg:get()
  if not valid(actor)or not same(actor:GetWorld(),world)or actor:GetClass():GetFullName()~='BlueprintGeneratedClass '..path then return end
  local source=actor.Instigator;if not valid(source)then return end
  local movement=actor.ProjectileMovement;assert(valid(movement),'disc_movement_required')
  count=count+1;assert(count<=32,'disc_projectile_bound')
  local id=actor:GetFullName()..'@'..actor:GetAddress();local start=now();local pos=actor:K2_GetActorLocation();local v=movement.Velocity
  if magnitude(source:GetVelocity())>1000 then movingCount=movingCount+1 end
  emit('PROJECTILE','id='..id..'|authority='..tostring(actor:HasAuthority())..'|initial='..movement.InitialSpeed..'|max='..movement.MaxSpeed..'|gravity='..movement.ProjectileGravityScale..'|velocity='..vector(v)..'|speed='..magnitude(v)..'|sourceVelocity='..vector(source:GetVelocity())..'|position='..vector(pos))
  if count==1 then
   properties(actor,'projectile');properties(movement,'movement')
   local cdo=StaticFindObject(path:gsub('%.BP_Projectile_Topaz_LightSpinfusor_C$','.Default__BP_Projectile_Topaz_LightSpinfusor_C'))
   assert(valid(cdo)and valid(cdo.ProjectileMovement),'disc_original_defaults_required')
   emit('DEFAULTS','initial='..cdo.ProjectileMovement.InitialSpeed..'|max='..cdo.ProjectileMovement.MaxSpeed..'|forward='..cdo.InheritForwardVelocityPercent..'|lateral='..cdo.InheritLateralVelocityPercent)
  end
  if role=='host'and(count==3 or count==4)then
   local forward=count==3
   later(3000,function()
    assert(valid(source)and same(source:GetWorld(),world)and valid(source.Controller)and same(source.Controller.Pawn,source),'disc_motion_fixture_original_owner_required')
    signature('/Script/Engine.Character:LaunchCharacter',{{'LaunchVelocity','StructProperty',0},{'bXYOverride','BoolProperty',24},{'bZOverride','BoolProperty',25}})
    if forward then
     signature('/Script/Engine.Actor:K2_TeleportTo',{{'DestLocation','StructProperty',0},{'DestRotation','StructProperty',24},{'ReturnValue','BoolProperty',48}})
     local at=source:K2_GetActorLocation()
     assert(source:K2_TeleportTo({X=at.X,Y=at.Y,Z=at.Z+30000},{Pitch=0,Yaw=0,Roll=0}),'disc_private_airborne_fixture_required')
    end
    source:LaunchCharacter({X=forward and 5000 or 0,Y=forward and 0 or 5000,Z=0},true,true)
    emit('MOTION_SETUP','axis='..(forward and'forward'or'lateral')..'|requestedSpeed=5000|projectileWrites=false')
   end)
  end
  for _,delay in ipairs({10,25,50,100})do
   later(delay,function()
    if not valid(actor)or actor:GetFullName()..'@'..actor:GetAddress()~=id or not same(actor:GetWorld(),world)or actor.bStopped then return end
    local at=actor:K2_GetActorLocation();local dt=now()-start
    if dt>0 then
     local dx,dy,dz=at.X-pos.X,at.Y-pos.Y,at.Z-pos.Z
     emit('SAMPLE','id='..id..'|dt='..dt..'|position='..vector(at)..'|velocity='..vector(movement.Velocity)..'|distanceSpeed='..math.sqrt(dx*dx+dy*dy+dz*dz)/dt)
    end
   end)
  end
 end
 local hook='/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'
 signature(hook,{{'Projectile','ObjectProperty',0},{'Transform','StructProperty',16},{'ReturnValue','ObjectProperty',112}})
 local a,b=RegisterHook(hook,function()end,safe(observe));hooks[#hooks+1]={hook,a,b}
 local pressed=false
 local function tap(label)
  taps=taps+1;lastTap=now();emit('ACTION','label='..label..'|sourceVelocity='..vector(pawn:GetVelocity()))
  asc:PressInputID(5);pressed=true
  later(50,function()assert(same(pc.Pawn,pawn),'disc_probe_pawn_changed');asc:ReleaseInputID(5);pressed=false end)
 end
 local stage=0
 local function pulse()
  assert(same(pc.Pawn,pawn)and same(pawn:GetWorld(),world)and same(pawn.AbilitySystemComponent,asc),'disc_probe_original_owner_changed')
  local elapsed=now()-readyAt
  -- The isolated authoritative host launches this one original character after
  -- the third/fourth shots. Normal native character physics and networking run;
  -- no projectile or weapon property is assigned by this diagnostic.
  local velocity=pawn:GetVelocity();local at={2,5,8}
  if stage<3 and elapsed>=at[stage+1]then stage=stage+1;tap('stationary'..stage)
  elseif stage==3 and velocity.X>1000 and now()-lastTap>=2 then stage=4;tap('moving_forward')
  elseif stage==4 and velocity.Y>1000 and now()-lastTap>=2 then stage=5;tap('moving_lateral')
  elseif elapsed>=20 then
   if pressed then asc:ReleaseInputID(5);pressed=false end
   assert(taps==5 and count>=5 and movingCount>=2,'disc_probe_requires_actual_forward_and_lateral_motion')
   for _,h in ipairs(hooks)do UnregisterHook(h[1],h[2],h[3])end
   emit('COMPLETE','taps='..taps..'|projectiles='..count..'|movingProjectiles='..movingCount..'|projectileWrites=false|weaponStatWrites=false');stopped=true;return
  end
  later(25,pulse)
 end
 return function(context)
  if stopped then return end
  scope();world=context:GetWorld()
  if role=='host'or readyAt then return end
  pc=context;pawn=pc.Pawn
  if not valid(pawn)or not pawn.bInitialized or not valid(pc.PlayerState)or pc.PlayerState.r_PlayerLoadout.LoadoutId~=527 then return end
  local gameplay=false
  for _,gs in ipairs(FindAllOf('ValGameState')or{})do if same(gs:GetWorld(),world)and gs.r_GameplayPhaseInfo.Phase.TagName:ToString()=='GamePhase.GameplayStartPhase'then gameplay=true end end
  if not gameplay then return end
  assert(pc:IsLocalPlayerController()and not pc:HasAuthority(),'disc_probe_original_remote_owner_required')
  asc=pawn.AbilitySystemComponent;if not valid(asc)then return end
  signature('/Script/GameplayAbilities.AbilitySystemComponent:PressInputID',{{'InputID','IntProperty',0}})
  signature('/Script/GameplayAbilities.AbilitySystemComponent:ReleaseInputID',{{'InputID','IntProperty',0}})
  local slot={TagName=FName('EquipSlot.WeaponSlot.1')}
  pawn:SwapToEquipSlot(slot);readyAt=now();emit('READY','loadout=527|pawn='..pawn:GetFullName());later(25,pulse)
 end
end
