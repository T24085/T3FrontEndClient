-- Test-only actual client RepairTool input. No grants or capture/ownership calls.
return function(env)
 local valid,report=env.valid,env.report;local started=false;local pc,pawn,asc,point;local ticks=0;local input
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function pulse()
  env.scope();ticks=ticks+1;assert(ticks<1400,'repair_input_deadline')
  assert(same(pc.Pawn,pawn)and same(pawn.AbilitySystemComponent,asc),'repair_input_owner_changed')
  local p=pawn:K2_GetActorLocation();local target=point.Collision:K2_GetComponentLocation()
  local dx,dy,dz=target.X-p.X,target.Y-p.Y,target.Z-(p.Z+pawn.BaseEyeHeight)
  pc:SetControlRotation({Pitch=math.deg(math.atan(dz,math.sqrt(dx*dx+dy*dy))),Yaw=math.deg(math.atan(dy,dx)),Roll=0})
  if ticks==80 then
   local found=false
   asc.ActivatableAbilities.Items:ForEach(function(_,v)local s=v:get();if valid(s.Ability)and s.Ability:GetClass():GetFullName()=='BlueprintGeneratedClass /Game/Topaz/Abilities/Devices/RepairTool/RegularRepairTool/GA_RepairTool.GA_RepairTool_C'then assert(not found,'repair_input_ambiguous_original');found=true;input=s.InputID;report('REPAIR_CAPTURE_ORIGINAL_GRANT|input='..input..'|handle='..s.Handle.Handle)end end)
   assert(found and input>=0 and input<=255,'repair_input_original_grant_missing')
   pawn:SwapToEquipSlot({TagName=FName('EquipSlot.RepairTool')});asc:PressInputID(input);report('REPAIR_CAPTURE_INPUT_PRESS|input='..input..'|slot=EquipSlot.RepairTool|source=originalAbility')
  elseif ticks==720 then asc:ReleaseInputID(input);report('REPAIR_CAPTURE_INPUT_COMPLETE|input='..input..'|heldSeconds=16');return end
  ExecuteInGameThreadWithDelay(25,function()local ok,why=pcall(pulse);if not ok then report('REPAIR_CAPTURE_INPUT_ERROR|'..tostring(why))end end)
 end
 return {tick=function(controller,gs)
  if started or gs.r_GameplayPhaseInfo.Phase.TagName:ToString()~='GamePhase.GameplayStartPhase'or not valid(controller.Pawn)or not controller.Pawn.bInitialized then return end
  local candidate=controller.Pawn;local p=candidate:K2_GetActorLocation()
  for _,a in ipairs(FindAllOf('TopObservationPoint')or{})do if valid(a)and same(a:GetWorld(),candidate:GetWorld())then
   local q=a:K2_GetActorLocation();if math.abs(p.X-(q.X-350))<100 and math.abs(p.Y-q.Y)<100 then point=a end
  end end
  if not point then return end
  started=true;pc=controller;pawn=candidate;asc=pawn.AbilitySystemComponent
  assert(pc:IsLocalPlayerController()and not pc:HasAuthority(),'repair_input_local_client_required')
  env.signature('/Script/GameplayAbilities.AbilitySystemComponent:PressInputID',{{'InputID','IntProperty',0}})
  env.signature('/Script/GameplayAbilities.AbilitySystemComponent:ReleaseInputID',{{'InputID','IntProperty',0}})
  env.signature('/Script/Engine.Controller:SetControlRotation',{{'NewRotation','StructProperty',0}})
  pulse()
 end}
end
