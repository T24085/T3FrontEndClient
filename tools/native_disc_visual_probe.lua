-- Observe original projectile origin, visual component and local camera poses.
-- Composes the separate controlled-motion speed probe; no projectile writes.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 env.visual_fixture=true
 env.manual_visual_fixture=env.manual_input==true
 local role=assert(env.role);local base=assert(env.base_factory)(env);local world;local count=0;local failed=false;local inspected=false
 local path='/Game/Topaz/Abilities/Weapons/LightSpinfusor/BP_Projectile_Topaz_LightSpinfusor.BP_Projectile_Topaz_LightSpinfusor_C'
 local clock=StaticFindObject('/Script/Engine.Default__GameplayStatics')
 signature('/Script/Engine.SceneComponent:K2_GetComponentLocation',{{'ReturnValue','StructProperty',0}})
 signature('/Script/Engine.PlayerCameraManager:GetCameraLocation',{{'ReturnValue','StructProperty',0}})
 signature('/Script/Valhalla.ValCharacter:GetActiveMuzzleLocation',{{'ReturnValue','StructProperty',0}})
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function now()return clock:GetTimeSeconds(world)end
 local function vec(v)return string.format('%.5f,%.5f,%.5f',v.X,v.Y,v.Z)end
 local function copy(v)return{X=v.X,Y=v.Y,Z=v.Z}end
 local function field(o,name)local ok,v=pcall(function()return o[name]end);if ok then return v end end
 local function emit(kind,text)report('DISC_VISUAL_'..kind..'|role='..role..'|time='..now()..'|'..text)end
 local function safe(fn)return function(...)
  if failed then return end
  local ok,why=pcall(fn,...)
  if not ok then failed=true;report('DISC_VISUAL_ERROR|role='..role..'|'..tostring(why))end
 end end
 local function identity(o)return valid(o)and o:GetFullName()or'none'end
 local function census(o,label)
  local cls=o:GetClass();local seen={};local n=0
  for depth=1,7 do
   if not valid(cls)then break end
   cls:ForEachProperty(function(p)
    local name=p:GetFName():ToString();if seen[name]then return end;seen[name]=true
    if not(name:find('Visual',1,true)or name:find('Predict',1,true)or name:find('Mesh',1,true)or name:find('Camera',1,true)or name:find('Trail',1,true)or name:find('Origin',1,true))then return end
    n=n+1;assert(n<=256,'disc_visual_property_bound')
    local kind=p:GetFullName():match('^(%S+) ');local value=o[name]
    if kind=='ObjectProperty'then emit('FIELD','owner='..label..'|name='..name..'|object='..identity(value))
    elseif kind=='BoolProperty'or kind=='FloatProperty'or kind=='DoubleProperty'or kind=='IntProperty'or kind=='EnumProperty'or kind=='ByteProperty'then emit('FIELD','owner='..label..'|name='..name..'|value='..tostring(value))end
   end)
   cls:ForEachFunction(function(fn)
    local name=fn:GetFName():ToString()
    if name:find('Visual',1,true)or name:find('Predict',1,true)or name:find('Muzzle',1,true)or name:find('Projectile',1,true)or name:find('WeaponMesh',1,true)then
     local params={};fn:ForEachProperty(function(p)params[#params+1]=p:GetFullName()..'@'..p:GetOffset_Internal()end)
     emit('API','owner='..label..'|'..fn:GetFullName()..'|'..table.concat(params,';'))
    end
   end)
   cls=cls:GetSuperStruct()
  end
 end
 local function camera(source)
  local pc=source.Controller
  if not valid(pc)then return nil end
  local manager=pc.PlayerCameraManager
  if valid(manager)then return copy(manager:GetCameraLocation())end
 end
 local function component_position(o)
  if valid(o)then return vec(o:K2_GetComponentLocation())end
  return'none'
 end
 local function snapshot(actor,id,start,source)
  if not valid(actor)or actor:GetFullName()..'@'..actor:GetAddress()~=id or not same(actor:GetWorld(),world)or not valid(source)then return end
  local root=actor:K2_GetActorLocation();local visual=field(actor,'VisualRootSceneComponent');local trail=field(actor,'NS_Projectile_Trail')
  local view=camera(source)
  emit('POSE','id='..id..'|prediction='..actor.r_PredictionID..'|dt='..(now()-start)..'|actor='..vec(root)..'|visual='..component_position(visual)..'|trail='..component_position(trail)..'|source='..vec(source:K2_GetActorLocation())..'|sourceVelocity='..vec(source:GetVelocity())..'|camera='..(view and vec(view)or'none')..'|stopped='..tostring(actor.bStopped)..'|exploded='..tostring(actor.HasExploded))
 end
 local function observe(_,_,arg)
  if not valid(world)then return end
  local actor=arg:get()
  if not valid(actor)or not same(actor:GetWorld(),world)or actor:GetClass():GetFullName()~='BlueprintGeneratedClass '..path then return end
  local source=actor.Instigator;if not valid(source)then return end
  count=count+1;assert(count<=32,'disc_visual_projectile_bound')
  local id=actor:GetFullName()..'@'..actor:GetAddress();local start=now()
  emit('BIRTH','id='..id..'|prediction='..actor.r_PredictionID..'|authority='..tostring(actor:HasAuthority())..'|source='..identity(source)..'|localController='..tostring(valid(source.Controller)and source.Controller:IsLocalPlayerController()))
  snapshot(actor,id,start,source)
  for _,delay in ipairs({1,5,10,20,40,60,80,100,150,200,300})do
    ExecuteInGameThreadWithDelay(delay,safe(function()
     scope();snapshot(actor,id,start,source)
     if role=='client'and valid(source.Controller)and source.Controller:IsLocalPlayerController()then
      local peers=FindAllOf('BP_Projectile_Topaz_LightSpinfusor_C')or{};assert(#peers<=64,'disc_peer_bound')
      for _,peer in ipairs(peers)do
       if valid(peer)and not same(peer,actor)and same(peer:GetWorld(),world)and same(peer.Instigator,source)then
        local visual=field(peer,'VisualRootSceneComponent');local trail=field(peer,'NS_Projectile_Trail')
        emit('PEER','triggerPrediction='..actor.r_PredictionID..'|prediction='..peer.r_PredictionID..'|id='..peer:GetFullName()..'@'..peer:GetAddress()..'|authority='..tostring(peer:HasAuthority())..'|hidden='..tostring(peer.bHidden)..'|actor='..vec(peer:K2_GetActorLocation())..'|visual='..component_position(visual)..'|trail='..component_position(trail)..'|stopped='..tostring(peer.bStopped)..'|exploded='..tostring(peer.HasExploded))
       end
      end
     end
    end))
  end
 end
 local hook='/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'
 signature(hook,{{'Projectile','ObjectProperty',0},{'Transform','StructProperty',16},{'ReturnValue','ObjectProperty',112}})
 RegisterHook(hook,function()end,safe(observe))
 local deferred='/Script/Valhalla.ValBlueprintLibrary:SpawnProjectileDeferred'
 signature(deferred,{{'Class','ClassProperty',0},{'SpawnTransform','StructProperty',16},{'Owner','ObjectProperty',112},{'EffectSpec','StructProperty',120},{'ProjectileOrigin','StructProperty',136},{'ExplosionRadius','FloatProperty',160},{'ProjectileSpeedModify','FloatProperty',164},{'BotMuzzleSocketIndex','IntProperty',168},{'InstigatorController','ObjectProperty',176},{'PredictionID','IntProperty',184},{'Instigator','ObjectProperty',192},{'ReturnValue','ObjectProperty',200}})
 RegisterHook(deferred,safe(function(_,cls,transform,owner,effect,origin,radius,modify,bot,controller,prediction,instigator)
  if not valid(world)then return end
  local kind=cls:get();local source=instigator:get()
  if not valid(kind)or kind:GetFullName()~='BlueprintGeneratedClass '..path or not valid(source)or not same(source:GetWorld(),world)then return end
  local view=camera(source)
  local ok,spawn=pcall(function()return vec(transform:get().Translation)end)
  emit('REQUEST','prediction='..prediction:get()..'|origin='..vec(origin:get())..'|spawn='..(ok and spawn or'unavailable')..'|source='..vec(source:K2_GetActorLocation())..'|sourceVelocity='..vec(source:GetVelocity())..'|muzzle='..vec(source:GetActiveMuzzleLocation())..'|camera='..(view and vec(view)or'none'))
 end),function()end)
 for _,name in ipairs({'PressInputID','ReleaseInputID'})do
  signature('/Script/GameplayAbilities.AbilitySystemComponent:'..name,{{'InputID','IntProperty',0}})
  RegisterHook('/Script/GameplayAbilities.AbilitySystemComponent:'..name,safe(function(context,input)
   if not valid(world)or input:get()~=5 then return end
   local asc=context:get();local source=asc:GetOwner()
   if valid(source)and same(source:GetWorld(),world)and valid(source.Controller)and source.Controller:IsLocalPlayerController()then
    emit('INPUT','operation='..name..'|input=5|owner='..identity(source))
   end
  end),function()end)
 end
 return function(context)
  scope();world=context:GetWorld()
  if not inspected then
   for _,controller in ipairs(FindAllOf('ValPlayerController')or{})do
    local source=controller.Pawn;local ps=controller.PlayerState
    if valid(source)and source.bInitialized and valid(ps)and ps.r_PlayerLoadout.LoadoutId==527 and same(source:GetWorld(),world)then
     local cdo=StaticFindObject(path:gsub('%.BP_Projectile_Topaz_LightSpinfusor_C$','.Default__BP_Projectile_Topaz_LightSpinfusor_C'))
     if valid(cdo)then census(cdo,'projectile_default');census(source,'character');inspected=true;break end
    end
   end
  end
  base(context)
 end
end
