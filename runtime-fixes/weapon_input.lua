-- Client-side completion of original weapon input and cancellation protocols.
-- Projectile creation, ammo, per-weapon last-shot times and cooldowns stay native.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 signature('/Script/GameplayAbilities.AbilitySystemComponent:ServerSetInputReleased',{{'AbilityHandle','StructProperty',0}})
 signature('/Script/GameplayAbilities.GameplayAbility:K2_CancelAbility',{})
 signature('/Script/Valhalla.ValCharacter:GetActiveEquippedAbility',{{'ReturnValue','StructProperty',0}})
 local masterPath='/Game/Abilities/Devices/Gun/GA_Gun_Master.GA_Gun_Master_C'
 local reloadPath='/Game/Abilities/Devices/Gun/GA_Gun_Master_Reload.GA_Gun_Master_Reload_C'
 local master=nil;local reloadMaster=nil;local state;local stopped=false;local visualObserver=env.observeVisuals
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function owned(s)
  return valid(s.pc)and s.pc:IsLocalPlayerController()and not s.pc:HasAuthority()
   and same(s.pc.Pawn,s.pawn)and s.pawn:GetFullName()==s.name and same(s.pawn.Controller,s.pc)
   and same(s.pawn.AbilitySystemComponent,s.asc)and same(s.asc:GetOwner(),s.pawn)
   and same(s.pawn:GetWorld(),s.world)
 end
 local function pulse()
  local s=state;if not s then return end
  if not owned(s)then state=nil;return end
  if not valid(master)then master=StaticFindObject(masterPath)end
  if not valid(master)then return end
  assert(master:GetFullName()=='BlueprintGeneratedClass '..masterPath,'weapon_input_master_identity_changed')
  local selected=s.pawn:GetActiveEquippedAbility().Handle
  if visualObserver then
   local ok,why=pcall(visualObserver,s.pc,s.pawn,s.asc,selected)
   if not ok then visualObserver=nil;report('HEAVY_BOLT_VISUAL_ERROR|'..tostring(why):sub(1,500))end
  end
  if not valid(reloadMaster)then reloadMaster=StaticFindObject(reloadPath)end
  if valid(reloadMaster)then assert(reloadMaster:GetFullName()=='BlueprintGeneratedClass '..reloadPath,'weapon_input_reload_identity_changed')end
  local pressed=false;local grants={};local reloads={};local count=0
  s.asc.ActivatableAbilities.Items:ForEach(function(_,param)
   count=count+1;assert(count<=256,'weapon_input_grant_bound')
   local spec=param:get()
   if spec.InputID==5 and valid(spec.Ability)and spec.Ability:IsA(master)then
    pressed=pressed or spec.InputPressed
    grants[#grants+1]=spec
   end
   if valid(reloadMaster)and valid(spec.Ability)and spec.Ability:IsA(reloadMaster)then reloads[#reloads+1]=spec end
  end)
  if #grants==0 then return end
  -- GAS can end the local predicted ability before key-up. Its ordinary
  -- release path can then omit the still-active server counterpart.
  if not pressed and s.pressed==true then
   for _,spec in ipairs(grants)do s.asc:ServerSetInputReleased(spec.Handle)end
   report('WEAPON_INPUT_RELEASE_SYNC|handles='..#grants)
  end
  s.pressed=pressed
  if selected==s.selected then return end
  local previous=s.selected;s.selected=selected
  if not previous or previous==0 then return end
  local oldInstances={}
  for _,spec in ipairs(grants)do
   if spec.Handle.Handle==previous and spec.Handle.Handle~=selected then
    local cancelled={}
    for _,arrayName in ipairs({'NonReplicatedInstances','ReplicatedInstances'})do
     spec[arrayName]:ForEach(function(_,param)
      local ability=param:get()
      if valid(ability)and ability:IsA(master)and same(ability.SourceCharacter,s.pawn)and not cancelled[ability:GetAddress()]then
       cancelled[ability:GetAddress()]=true
       oldInstances[ability:GetAddress()]=true
       if spec.ActiveCount>0 then
        assert(ability.bServerRespectsRemoteAbilityCancellation==true,'weapon_input_native_cancel_contract_required')
        ability.InputBuffered=false;ability.ListeningForInput=false
        ability:K2_CancelAbility()
        report('WEAPON_INPUT_SWAP_CANCEL|oldHandle='..previous..'|newHandle='..selected..'|weapon='..ability:GetClass():GetFullName())
       end
      end
     end)
    end
   end
  end
  for _,spec in ipairs(reloads)do
   if spec.ActiveCount>0 then
    local cancelled={}
    for _,arrayName in ipairs({'NonReplicatedInstances','ReplicatedInstances'})do
     spec[arrayName]:ForEach(function(_,param)
      local ability=param:get()
      if valid(ability)and ability:IsA(reloadMaster)and same(ability.OwningCharacter,s.pawn)
       and valid(ability.GA_Gun)and oldInstances[ability.GA_Gun:GetAddress()]and not cancelled[ability:GetAddress()]then
       cancelled[ability:GetAddress()]=true
       assert(ability.bServerRespectsRemoteAbilityCancellation==true,'weapon_input_native_reload_cancel_contract_required')
       ability:K2_CancelAbility()
       report('WEAPON_INPUT_OLD_RELOAD_CANCEL|oldHandle='..previous..'|newHandle='..selected..'|reloadHandle='..spec.Handle.Handle)
      end
     end)
    end
   end
  end
 end
 local schedule
 schedule=function()
  ExecuteInGameThreadWithDelay(25,function()
   if stopped then return end
   local ok,why=pcall(function()scope();pulse();schedule()end)
   if not ok then stopped=true;report('WEAPON_INPUT_ERROR|'..tostring(why):sub(1,500))end
  end)
 end
 schedule();report('WEAPON_INPUT_READY|nativeFire=true|nativeAmmo=true|perWeaponCooldowns=true')
 return function(pc,ps)
  local pawn=pc.Pawn
  if not valid(pawn)or not pawn.bInitialized or not same(pawn.PlayerState,ps)then return end
  if state and same(state.pawn,pawn)and state.name==pawn:GetFullName()then return end
  local asc=pawn.AbilitySystemComponent;if not valid(asc)then return end
  state={pc=pc,pawn=pawn,asc=asc,world=pawn:GetWorld(),name=pawn:GetFullName()}
 end
end
