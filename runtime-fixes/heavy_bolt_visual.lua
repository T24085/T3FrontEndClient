-- Keep the local Heavy Bolt's flight and reload effects out of the camera.
return function(env)
 local valid,scope,report=env.valid,env.scope,env.report
 local weapon='/Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/'
 local gun='BlueprintGeneratedClass '..weapon..'GA_Topaz_HeavyBoltLauncher.GA_Topaz_HeavyBoltLauncher_C'
 local visualPath=weapon..'AV_Topaz_HeavyBoltLauncher.AV_Topaz_HeavyBoltLauncher'
 local trail='/Game/VFX/Weapons/BoltLauncher/Heavy/Projectile/NS_BoltLauncher_Heavy_Projectile_'
 local one='NiagaraSystem '..trail..'1P.NS_BoltLauncher_Heavy_Projectile_1P'
 local three='NiagaraSystem '..trail..'3P.NS_BoltLauncher_Heavy_Projectile_3P'
 local reload='NiagaraSystem /Game/VFX/Weapons/BoltLauncher/Heavy/Reload/'
 local reloadSockets={
  [reload..'NS_BoltLauncher_Heavy_Bolt_Reload.NS_BoltLauncher_Heavy_Bolt_Reload']='EnergyBullet_Socket',
  [reload..'NS_BoltLauncher_Heavy_EnergyTether_Reload.NS_BoltLauncher_Heavy_EnergyTether_Reload']='MuzzleSocket',
 }
 local configured
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end

 return function(pc,pawn,asc)
  scope()
  if valid(configured) then return end
  if not valid(pc)or not pc:IsLocalPlayerController()or pc:HasAuthority()or not same(pc.Pawn,pawn)or not same(pawn.Controller,pc)or not same(pawn.AbilitySystemComponent,asc)or not same(asc:GetOwner(),pawn)then return end
  local hasBolt=false
  asc.ActivatableAbilities.Items:ForEach(function(_,p)
   local spec=p:get()
   if spec.InputID==5 and valid(spec.Ability)and spec.Ability:GetClass():GetFullName()==gun then hasBolt=true end
  end)
  if not hasBolt then return end

  local visual=StaticFindObject(visualPath)
  if not valid(visual)or visual:GetFullName()~='ValDeviceAudioVisual '..visualPath then return end
  local first,world=visual.ProjectileTrail1P,visual.ProjectileTrail3P
  if not valid(first)or not valid(world)or world:GetFullName()~=three then return end
  if not same(first,world)and first:GetFullName()~=one then return end

  local targets={}
  local seen={}
  visual.ReloadActions:ForEach(function(_,param)
   local action=param:get()
   local system=action.ParticleSystem
   if not valid(system) then return end
   local name=system:GetFullName()
   local socket=reloadSockets[name]
   if socket and action.SocketName:ToString()==socket then
    assert(not seen[name],'heavy_bolt_duplicate_camera_reload_action')
    seen[name]=true
    targets[#targets+1]=action
   end
  end)
  if #targets~=2 then return end

  -- The original projectile reads this slot when assigning its trail. A single
  -- asset selection also covers bolts that impact before the player stows the gun.
  -- The two first-person reload emitters can outlive the weapon attachment.
  -- Retire their particle systems while preserving the original reload itself.
  for _,action in ipairs(targets)do
   action.ParticleSystem=nil
   assert(not valid(action.ParticleSystem),'heavy_bolt_camera_reload_readback_failed')
  end
  visual.ProjectileTrail1P=world
  assert(same(visual.ProjectileTrail1P,world),'heavy_bolt_world_trail_readback_failed')
  configured=visual
  report('HEAVY_BOLT_CAMERA_EFFECTS_READY|trail=original_3P|reload_emitters=2|stage=before_projectile')
 end
end
