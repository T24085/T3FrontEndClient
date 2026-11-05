-- Preserve the release edge even when exhaustion ends the predicted ability first.
return function(env)
 local valid,report=env.valid,env.report
 env.signature('/Script/GameplayAbilities.AbilitySystemComponent:ServerSetInputReleased',{{'AbilityHandle','StructProperty',0}})
 local state=nil;local stopped=false
 local function pulse()
  local s=state;if not s then return end
  if not valid(s.pc) or not valid(s.pawn) or not valid(s.asc) or not valid(s.pc.Pawn) or s.pc.Pawn:GetAddress()~=s.address or s.pawn:GetFullName()~=s.name or not valid(s.pawn.Controller) or s.pawn.Controller:GetAddress()~=s.pc:GetAddress() then state=nil;return end
  if s.pc:HasAuthority() or not s.pc:IsLocalPlayerController() then state=nil;return end
  local pressed=false;local found=false
  s.asc.ActivatableAbilities.Items:ForEach(function(i,e) local spec=e:get();if spec.InputID==s.input then found=true;pressed=pressed or spec.InputPressed end end)
  if not found then return end
  if not pressed and s.pressed~=false then
   local count=0
   s.asc.ActivatableAbilities.Items:ForEach(function(i,e) local spec=e:get();if spec.InputID==s.input then s.asc:ServerSetInputReleased(spec.Handle);count=count+1 end end)
   report('JETPACK_INPUT_RELEASE_SYNC|input='..s.input..'|handles='..count)
  end
  s.pressed=pressed
 end
 local schedule
 schedule=function()
  ExecuteInGameThreadWithDelay(50,function()
   if stopped then return end
   local ok,why=pcall(function() env.scope();pulse();schedule() end)
   if not ok then stopped=true;report('JETPACK_INPUT_ERROR|'..tostring(why):sub(1,500)) end
  end)
 end
 schedule();report('JETPACK_INPUT_SYNC_READY')
 return function(pc,ps)
  local pawn=pc.Pawn
  if not valid(pawn) or not pawn.bInitialized or not valid(pawn.PlayerState) or pawn.PlayerState:GetAddress()~=ps:GetAddress() then return end
  if state and state.address==pawn:GetAddress() and state.name==pawn:GetFullName() then return end
  local asc=pawn.AbilitySystemComponent;if not valid(asc) then return end
  local input
  asc.ActivatableAbilities.Items:ForEach(function(i,e)
   local spec=e:get();if valid(spec.Ability) and spec.Ability:GetClass():GetFullName()=='BlueprintGeneratedClass /Game/Abilities/Devices/Jet_Pack/GA_Jetpack.GA_Jetpack_C' then input=spec.InputID end
  end)
  if type(input)~='number' or input<0 then return end
  state={pc=pc,pawn=pawn,asc=asc,address=pawn:GetAddress(),name=pawn:GetFullName(),input=input}
 end
end
