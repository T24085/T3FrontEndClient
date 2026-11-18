-- Isolated original loadout request and fire/stow fixture. No custom grants.
return function(env)
 local valid,scope,signature,report=env.valid,env.scope,env.signature,env.report
 local requested=false;local started=false;local pc,pawn,asc;local ticks=0;local stage=0;local shots=0;local trailObserved=false;local predictedSeen=false;local replicatedSeen=false;local stable=0
 local gun='BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/GA_Topaz_HeavyBoltLauncher.GA_Topaz_HeavyBoltLauncher_C'
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function selected_bolt()
  local selected=pawn:GetActiveEquippedAbility().Handle;local found=false
  asc.ActivatableAbilities.Items:ForEach(function(_,p)local s=p:get();if s.InputID==5 and s.Handle.Handle==selected and valid(s.Ability)then found=s.Ability:GetClass():GetFullName()==gun end end)
  return found
 end
 local service={}
 function service.select(plc,id)
  scope();if requested then return end;assert(id==531,'bolt_fixture_heavy_loadout_required')
  local slot={TagName=FName('EquipSlot.WeaponSlot.1')};local items={};plc:GetLoadoutEquipSlotItems(id,slot,items)
  assert(#items==2,'bolt_fixture_original_primary_choices_changed')
  local chosen
  for _,wrapper in ipairs(items)do local item=wrapper:get();if item.ItemId==380 then assert(not chosen,'bolt_fixture_ambiguous_primary');chosen=item end end
  assert(chosen,'bolt_fixture_original_alternate_primary_missing')
  signature('/Script/Valhalla.PlayerLoadoutComponent:RequestLoadoutItem',{{'LoadoutId','IntProperty',0},{'EquipSlot','StructProperty',4},{'InventoryItem','StructProperty',16}})
  plc:RequestLoadoutItem(id,slot,chosen);requested=true;report('BOLT_FIXTURE_LOADOUT_REQUEST|loadout=531|item=380|source=original_inventory')
 end
 local pulse
 pulse=function()
  scope();ticks=ticks+1;assert(ticks<1600,'bolt_fixture_deadline')
  assert(same(pc.Pawn,pawn)and same(pawn.Controller,pc)and same(pawn.AbilitySystemComponent,asc),'bolt_fixture_owner_changed')
  if stage==0 then
   assert(selected_bolt(),'bolt_fixture_original_grant_not_heavy_bolt')
   if ticks==80 then
    pc:SetControlRotation({Pitch=65,Yaw=0,Roll=0});asc:PressInputID(5);shots=shots+1;report('BOLT_FIXTURE_FIRE|shot='..shots);stage=1
    ExecuteInGameThreadWithDelay(80,function()scope();asc:ReleaseInputID(5)end)
   end
  elseif stage==1 and ticks>=88 then
   pawn:SwapToEquipSlot({TagName=FName('EquipSlot.WeaponSlot.2')});report('BOLT_FIXTURE_STOW|shot='..shots);stage=2
  elseif stage==2 then
   local count,allWorld=0,true
   for _,p in ipairs(FindAllOf('BP_Projectile_Topaz_HeavyBoltLauncher_C')or{})do
    if valid(p)and same(p:GetWorld(),pawn:GetWorld())and same(p.Instigator,pawn)and not p.bStopped then
     local t=p.NS_Projectile_Trail
     if valid(t)and valid(t.Asset)then
      local name=t.Asset:GetFullName();count=count+1
      predictedSeen=predictedSeen or p:HasAuthority();replicatedSeen=replicatedSeen or not p:HasAuthority()
      allWorld=allWorld and name:find('NS_BoltLauncher_Heavy_Projectile_3P.',1,true)~=nil
      report('BOLT_FIXTURE_TRAIL|shot='..shots..'|localAuthority='..tostring(p:HasAuthority())..'|predicted='..tostring(p.bIsClientProjectile)..'|hidden='..tostring(p.bHidden)..'|asset='..name..'|initialSpeed='..p.ProjectileMovement.InitialSpeed)
      if name:find('NS_BoltLauncher_Heavy_Projectile_3P.',1,true)then trailObserved=true end
     end
    end
   end
   stable=count>0 and allWorld and stable+1 or 0
   if ticks>=112 and stable>=20 and predictedSeen and replicatedSeen then report('BOLT_FIXTURE_COMPLETE|nativeShot=true|bothCopies=original3P|stableSamples='..stable..'|visualConfirmationSeparate=true');return end
  end
  ExecuteInGameThreadWithDelay(25,function()local ok,why=pcall(pulse);if not ok then report('BOLT_FIXTURE_ERROR|'..tostring(why))end end)
 end
 function service.tick(controller,gs)
  if started or gs.r_GameplayPhaseInfo.Phase.TagName:ToString()~='GamePhase.GameplayStartPhase'then return end
  if not valid(controller.Pawn)or not controller.Pawn.bInitialized then return end
  started=true;pc=controller;pawn=pc.Pawn;asc=pawn.AbilitySystemComponent
  assert(pc:IsLocalPlayerController()and not pc:HasAuthority(),'bolt_fixture_local_owner_required')
  signature('/Script/GameplayAbilities.AbilitySystemComponent:PressInputID',{{'InputID','IntProperty',0}})
  signature('/Script/GameplayAbilities.AbilitySystemComponent:ReleaseInputID',{{'InputID','IntProperty',0}})
  signature('/Script/Engine.Controller:SetControlRotation',{{'NewRotation','StructProperty',0}})
  pawn:SwapToEquipSlot({TagName=FName('EquipSlot.WeaponSlot.1')})
  ExecuteInGameThreadWithDelay(25,function()local ok,why=pcall(pulse);if not ok then report('BOLT_FIXTURE_ERROR|'..tostring(why))end end)
 end
 return service
end
