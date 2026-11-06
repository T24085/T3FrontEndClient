-- Candidate: retire the first-person-only Heavy Bolt trail after stowing its
-- weapon. Use the original world-space trail; never change projectile physics.
return function(env)
 local valid,scope,signature,report=env.valid,env.scope,env.signature,env.report
 local gun='BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/GA_Topaz_HeavyBoltLauncher.GA_Topaz_HeavyBoltLauncher_C'
 local projectile='BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/BP_Projectile_Topaz_HeavyBoltLauncher.BP_Projectile_Topaz_HeavyBoltLauncher_C'
 local one='NiagaraSystem /Game/VFX/Weapons/BoltLauncher/Heavy/Projectile/NS_BoltLauncher_Heavy_Projectile_1P.NS_BoltLauncher_Heavy_Projectile_1P'
 local three='NiagaraSystem /Game/VFX/Weapons/BoltLauncher/Heavy/Projectile/NS_BoltLauncher_Heavy_Projectile_3P.NS_BoltLauncher_Heavy_Projectile_3P'
 local checked=false
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 return function(pc,pawn,asc,selected)
  scope()
  if not valid(pc)or not pc:IsLocalPlayerController()or pc:HasAuthority()or not same(pc.Pawn,pawn)or not same(pawn.Controller,pc)or not same(pawn.AbilitySystemComponent,asc)or not same(asc:GetOwner(),pawn)then return end
  local hasBolt,equipped=false,false
  asc.ActivatableAbilities.Items:ForEach(function(_,p)
   local spec=p:get()
   if spec.InputID==5 and valid(spec.Ability)and spec.Ability:GetClass():GetFullName()==gun then hasBolt=true;equipped=equipped or spec.Handle.Handle==selected end
  end)
  if not hasBolt or equipped then return end
  local all=FindAllOf('BP_Projectile_Topaz_HeavyBoltLauncher_C')or{};assert(#all<=128,'heavy_bolt_projectile_bound')
  for _,p in ipairs(all)do
   if valid(p)and p:GetClass():GetFullName()==projectile and same(p:GetWorld(),pawn:GetWorld())and same(p.Instigator,pawn)then
    local trail=p.NS_Projectile_Trail
    if valid(trail)and same(trail:GetOwner(),p)and same(trail:GetWorld(),p:GetWorld())and valid(trail.Asset)and trail.Asset:GetFullName()==one then
     local av=p:GetAudioVisual()
     if valid(av)and valid(av.ProjectileTrail1P)and av.ProjectileTrail1P:GetFullName()==one and valid(av.ProjectileTrail3P)and av.ProjectileTrail3P:GetFullName()==three then
      if not checked then
       signature('/Script/Niagara.NiagaraComponent:SetAsset',{{'InAsset','ObjectProperty',0},{'bResetExistingOverrideParameters','BoolProperty',8}})
       checked=true
      end
      trail:SetAsset(av.ProjectileTrail3P,false)
      assert(valid(trail.Asset)and trail.Asset:GetFullName()==three,'heavy_bolt_stowed_trail_readback_failed')
      report('HEAVY_BOLT_STOWED_TRAIL|owner=original_3P_trail|localAuthority='..tostring(p:HasAuthority())..'|predicted='..tostring(p.bIsClientProjectile)..'|physicsChanged=false')
     end
    end
   end
  end
 end
end
