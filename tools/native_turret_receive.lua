-- Private original-input incoming-damage fixture; never player runtime.
return function(env)
 local valid,report=env.valid,env.report;local weapon=assert(env.weapon);local started=false;local pc;local pawn;local ticks=0;local input;local shots=0;local target;local firedAt;local stage='waiting';local peer
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local service={}
 function service.select(plc,id,controller)
  if controller.PlayerState:GetTeamId()==1 and env.target~='base'then
   local items={};plc:GetLoadoutEquipSlotItems(id,{TagName=FName('EquipSlot.Ability.2')},items)
   for _,p in ipairs(items)do local item=p:get();if item.ItemId==19 then plc:RequestLoadoutItem(id,{TagName=FName('EquipSlot.Ability.2')},item);return end end
   error('receive_original_pack_missing')
  elseif weapon=='gladiator'then
   local equipment=LoadAsset('/Game/Topaz/Equipment/Weapons/Topaz_Weapon_Gladiator.Topaz_Weapon_Gladiator');assert(valid(equipment),'receive_original_gladiator_asset')
   local items={};local slot={TagName=FName('EquipSlot.WeaponSlot.2')};plc:GetLoadoutEquipSlotItems(id,slot,items)
   for _,p in ipairs(items)do local item=p:get();if item.ItemId==equipment.ItemId then plc:RequestLoadoutItem(id,slot,item);report('RECEIVE_ORIGINAL_GLADIATOR_SELECTED|item='..item.ItemId);return end end
   error('receive_original_gladiator_inventory_missing')
  end
 end
 local function pulse()
  env.scope();ticks=ticks+1;assert(valid(pc)and valid(pawn)and same(pc.Pawn,pawn),'receive_client_owner_changed')
  local asc=pawn.AbilitySystemComponent
  if pc.PlayerState:GetTeamId()==1 and env.target~='base'then
   if ticks==100 then
    asc.ActivatableAbilities.Items:ForEach(function(_,p)local s=p:get();if valid(s.Ability)and s.Ability:GetClass():GetFullName():find('GA_Pack_LightTurret.GA_Pack_LightTurret_C',1,true)then input=s.InputID end end)
    assert(input,'receive_pack_grant_missing');pc:SetControlRotation({Pitch=-45,Yaw=0,Roll=0});asc:PressInputID(input);report('RECEIVE_PACK_PRESSED')
   elseif ticks==110 then asc:ReleaseInputID(input);report('RECEIVE_PACK_RELEASED')
   elseif ticks>=450 then if peer then peer.stop()end;return end
  else
   if stage=='waiting'then
    for _,p in ipairs(FindAllOf(env.target=='base'and'BP_Topaz_BaseTurret_C'or'BP_Turret_Deployable_C')or{})do
     if valid(p)and same(p:GetWorld(),pawn:GetWorld())and p.bInitialized and p:GetTeamId()==(env.target=='base'and 2 or 1)then
      local a,b=p:K2_GetActorLocation(),pawn:K2_GetActorLocation();local distance=math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2+(a.Z-b.Z)^2)
      if distance<2200 then target=p;stage='equip';pawn:SwapToEquipSlot({TagName=FName((weapon=='chain'or weapon=='gladiator'or weapon=='mortar')and'EquipSlot.WeaponSlot.2'or'EquipSlot.WeaponSlot.1')});firedAt=ticks;report('RECEIVE_TARGET_REPLICA|health='..p:GetHealth()..'|distance='..distance);break end
     end
    end
   elseif stage=='equip'and ticks-firedAt>=15 then
    local classes={};local selected=pawn:GetActiveEquippedAbility().Handle;local selectedClass
    asc.ActivatableAbilities.Items:ForEach(function(_,p)local s=p:get();if s.InputID==5 and valid(s.Ability)then local cls=s.Ability:GetClass():GetFullName();classes[#classes+1]=s.Handle.Handle..':'..cls;if s.Handle.Handle==selected then selectedClass=cls end end end)
    local expected=({lightdisc={'LightSpinfusor'},disc={'Spinfusor'},chain={'Chaingun'},mortar={'FusionMortar','Mortar'},gladiator={'Gladiator'}})[weapon]
    local matches=false;for _,name in ipairs(expected)do matches=matches or selectedClass=='BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/'..name..'/GA_Topaz_'..name..'.GA_Topaz_'..name..'_C'end
    assert(matches,'receive_selected_original_weapon_required:'..tostring(selectedClass))
    report('RECEIVE_GUN_GRANTS|weapon='..weapon..'|selected='..selected..'|classes='..table.concat(classes,';'));stage='firing';firedAt=ticks
   elseif stage=='firing'then
    if not valid(target)then asc:ReleaseInputID(5);if peer then peer.stop()end;report('RECEIVE_CLIENT_COMPLETE|weapon='..weapon..'|released=true|targetDestroyed=true');return end
    local eye,rot={},{};pawn:GetActorEyesViewPoint(eye,rot)
    local aim=target:K2_GetActorLocation();local mathLib=StaticFindObject('/Script/Engine.Default__KismetMathLibrary')
    if weapon=='lightdisc'then
     -- Isolate explosive damage with a normal shot at the original base's foot.
     -- Do not infer direct capsule contact from this splash-damage scenario.
     aim={X=aim.X,Y=aim.Y,Z=aim.Z-target.CapsuleComponent:GetScaledCapsuleHalfHeight()}
    end
    local look=mathLib:FindLookAtRotation(eye,aim);pc:SetControlRotation(look)
    local elapsed=ticks-firedAt
    if weapon=='chain'then
     if elapsed==1 then asc:PressInputID(5);report('RECEIVE_FIRE|weapon=chain|holdMs=1800')end
     if elapsed==19 then asc:ReleaseInputID(5);report('RECEIVE_INPUT_RELEASED|weapon=chain')end
     if elapsed>=45 then stage='complete';if peer then peer.stop()end;report('RECEIVE_CLIENT_COMPLETE|weapon=chain|released=true');return end
    else
     if elapsed==1 or elapsed==45 or elapsed==90 then asc:PressInputID(5);shots=shots+1;report('RECEIVE_FIRE|weapon='..weapon..'|shot='..shots..'|eye='..eye.X..','..eye.Y..','..eye.Z..'|target='..aim.X..','..aim.Y..','..aim.Z..'|aimRotation='..look.Pitch..','..look.Yaw..'|selected='..pawn:GetActiveEquippedAbility().Handle)end
     if elapsed==3 or elapsed==47 or elapsed==92 then asc:ReleaseInputID(5);report('RECEIVE_INPUT_RELEASED|weapon='..weapon)end
     if elapsed>=125 then stage='complete';if peer then peer.stop()end;report('RECEIVE_CLIENT_COMPLETE|weapon='..weapon..'|released=true');return end
    end
   end
  end
  assert(ticks<600,'receive_client_fixture_timeout')
  ExecuteInGameThreadWithDelay(100,function()local ok,e=pcall(pulse);if not ok then if valid(pawn)and valid(pawn.AbilitySystemComponent)then pawn.AbilitySystemComponent:ReleaseInputID(5);if input then pawn.AbilitySystemComponent:ReleaseInputID(input)end end;report('PERSONAL_FIXTURE_ERROR|'..tostring(e))end end)
 end
 function service.tick(controller,gs)
  if started or gs.r_GameplayPhaseInfo.Phase.TagName:ToString()~='GamePhase.GameplayStartPhase'or not valid(controller.Pawn)or not controller.Pawn.bInitialized then return end
  started=true;pc=controller;pawn=pc.Pawn
  peer=assert(env.peer_factory)({valid=valid,scope=env.scope,signature=env.signature,report=report,
   world=function()return pc:GetWorld()end,local_pawn=function()return pc.Pawn end,
   accept_source=function(source)return valid(source.PlayerState)and source:GetTeamId()==3-pc.PlayerState:GetTeamId()end})
  peer.start()
  local finish='/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'
  env.signature(finish,{{'Projectile','ObjectProperty',0},{'Transform','StructProperty',16},{'ReturnValue','ObjectProperty',112}})
  local spawned=0
  RegisterHook(finish,function()end,function(_,_,param)
   local ok,e=pcall(function()
    local p=param:get();if spawned>=20 or not valid(p)or not same(p:GetWorld(),pawn:GetWorld())or not same(p.Instigator,pawn)then return end
    spawned=spawned+1;local a=p:K2_GetActorLocation();local v=p:GetVelocity();local av=p:GetAudioVisual()
    local function asset(x)return valid(x)and x:GetFullName()or'none'end
    report('RECEIVE_LOCAL_SPAWN|class='..p:GetClass():GetFullName()..'|position='..a.X..','..a.Y..','..a.Z..'|velocity='..v.X..','..v.Y..','..v.Z..'|predicted='..tostring(p.bIsClientProjectile)..'|trail1P='..(valid(av)and asset(av.ProjectileTrail1P)or'unknown')..'|trail3P='..(valid(av)and asset(av.ProjectileTrail3P)or'unknown'))
   end);if not ok then report('RECEIVE_LOCAL_SPAWN_UNKNOWN|'..tostring(e))end
  end)
  local chainBirths=0
  RegisterBeginPlayPostHook(function(ctx)
   local ok,e=pcall(function()
    local p=ctx:get();if chainBirths>=32 or not valid(p)or not same(p:GetWorld(),pawn:GetWorld())then return end
    local cls=p:GetClass():GetFullName();if not cls:find('BP_Projectile_Topaz_Chaingun.',1,true)then return end
    chainBirths=chainBirths+1
    local own=same(p.Instigator,pawn)
    local trail=p.NS_Projectile_Trail
    report('RECEIVE_CHAIN_PROJECTILE|viewerTeam='..pc.PlayerState:GetTeamId()..'|own='..tostring(own)..'|authority='..tostring(p:HasAuthority())..'|predicted='..tostring(p.bIsClientProjectile)..'|hidden='..tostring(p.bHidden)..'|trail='..(valid(trail)and valid(trail.Asset)and trail.Asset:GetFullName()or'none'))
   end)
   if not ok then report('RECEIVE_VISUAL_PROBE_UNKNOWN|'..tostring(e))end
  end)
  ExecuteInGameThreadWithDelay(100,function()local ok,e=pcall(pulse);if not ok then report('PERSONAL_FIXTURE_ERROR|'..tostring(e))end end)
 end
 return service
end
