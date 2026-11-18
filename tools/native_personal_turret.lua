-- Isolated original Medium pack selection/deployment; never packaged gameplay.
return function(env)
 local started=false;local ticks=0;local input=nil
 local valid,report=env.valid,env.report
 local service={}
 function service.select(plc,id)
  assert(id==530,'personal_fixture_technician_required')
  local slot={TagName=FName('EquipSlot.Ability.2')};local items={};plc:GetLoadoutEquipSlotItems(id,slot,items)
  local chosen
  for _,w in ipairs(items)do local item=w:get();report('PERSONAL_PACK_CHOICE|item='..item.ItemId);if item.ItemId==19 then chosen=item end end
  assert(chosen,'personal_fixture_original_pack_missing')
  plc:RequestLoadoutItem(id,slot,chosen);report('PERSONAL_PACK_SELECTED|item=19|loadout=530')
 end
 function service.tick(pc,gs)
  if started or gs.r_GameplayPhaseInfo.Phase.TagName:ToString()~='GamePhase.GameplayStartPhase'or not valid(pc.Pawn)or not pc.Pawn.bInitialized then return end
  if pc.PlayerState:GetTeamId()==2 then
   started=true;local asc=pc.Pawn.AbilitySystemComponent
   ExecuteInGameThreadWithDelay(2000,function()
    env.scope();pc:SetControlRotation({Pitch=85,Yaw=180,Roll=0});asc:PressInputID(5)
    report('PERSONAL_ENEMY_SKY_SHOT|originalInput=true|spawnProtectionProbe=true')
    ExecuteInGameThreadWithDelay(100,function()env.scope();asc:ReleaseInputID(5)end)
   end)
   return
  end
  if pc.PlayerState:GetTeamId()~=1 then return end
  started=true;local pawn=pc.Pawn;local asc=pawn.AbilitySystemComponent
  assert(pc:IsLocalPlayerController()and not pc:HasAuthority(),'personal_fixture_local_owner')
  local function pulse()
   env.scope();ticks=ticks+1
   assert(valid(pawn)and valid(asc)and pc.Pawn:GetAddress()==pawn:GetAddress(),'personal_fixture_owner_changed')
   if ticks==100 then
    asc.ActivatableAbilities.Items:ForEach(function(_,p)local s=p:get();if valid(s.Ability)then
     local name=s.Ability:GetClass():GetFullName()
     if name:find('GA_Pack_LightTurret.GA_Pack_LightTurret_C',1,true)then input=s.InputID;report('PERSONAL_PACK_GRANT|input='..input..'|active='..s.ActiveCount)end
    end end)
    assert(input~=nil,'personal_fixture_pack_grant_missing');pc:SetControlRotation({Pitch=-45,Yaw=0,Roll=0});asc:PressInputID(input);report('PERSONAL_PACK_PRESS|input='..input)
   elseif ticks==110 then asc:ReleaseInputID(input);report('PERSONAL_PACK_RELEASE|input='..input)
   elseif ticks==160 then return end
   ExecuteInGameThreadWithDelay(100,function()local ok,e=pcall(pulse);if not ok then report('PERSONAL_FIXTURE_ERROR|'..tostring(e))end end)
  end
  ExecuteInGameThreadWithDelay(100,function()local ok,e=pcall(pulse);if not ok then report('PERSONAL_FIXTURE_ERROR|'..tostring(e))end end)
 end
 return service
end
