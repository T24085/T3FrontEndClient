-- Viewer-local presentation materials. Original skin/team overrides are copied
-- into distinct MIDs; a native owned component retains displaced UObject refs.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 local pc=assert(env.pc);local ps=pc.PlayerState;local world=pc:GetWorld()
 local current=nil;local records={};local primed=false
 local function identity(o)return o:GetFullName()..'|'..tostring(o:GetAddress())end
 local function same(a,b)return valid(a)and valid(b)and identity(a)==identity(b)end
 local function context()
  scope();assert(valid(pc)and pc:IsLocalPlayerController()and not pc:HasAuthority()and same(pc:GetWorld(),world),'spectator_material_context_changed')
  assert(valid(ps)and same(pc.PlayerState,ps)and same(ps:GetWorld(),world)and ps:IsOnlyASpectator()and not valid(pc.Pawn),'spectator_material_observer_only_required')
 end
 local function prime()
  if primed then return end
  local found=false
  StaticFindObject('/Script/Valhalla.ValCharacter'):ForEachProperty(function(p)
   if p:GetFName():ToString()=='IsLocallyViewed1pParam'then
    assert(not found and p:GetFullName()=='NameProperty /Script/Valhalla.ValCharacter:IsLocallyViewed1pParam'and p:GetOffset_Internal()==1896,'spectator_material_parameter_schema_changed');found=true
   end
  end);assert(found,'spectator_material_parameter_field_required')
  signature('/Script/Valhalla.ValCharacter:GetMesh3P',{{'ReturnValue','ObjectProperty',0}})
  signature('/Script/Valhalla.ValCharacter:GetGunMesh3P',{{'ReturnValue','ObjectProperty',0}})
  signature('/Script/Engine.PrimitiveComponent:SetOwnerNoSee',{{'bNewOwnerNoSee','BoolProperty',0}})
  local gunFlag=false
  StaticFindObject('/Script/Engine.PrimitiveComponent'):ForEachProperty(function(p)
   if p:GetFName():ToString()=='bOwnerNoSee'then
    assert(not gunFlag and p:GetFullName()=='BoolProperty /Script/Engine.PrimitiveComponent:bOwnerNoSee'and p:GetOffset_Internal()==724,'spectator_weapon_visibility_schema_changed');gunFlag=true
   end
  end);assert(gunFlag,'spectator_weapon_visibility_field_required')
  signature('/Script/Valhalla.ValCharacter:UpdateMeshVisibility',{})
  signature('/Script/Engine.PrimitiveComponent:GetNumMaterials',{{'ReturnValue','IntProperty',0}})
  signature('/Script/Engine.PrimitiveComponent:GetMaterial',{{'ElementIndex','IntProperty',0},{'ReturnValue','ObjectProperty',8}})
  signature('/Script/Engine.PrimitiveComponent:SetMaterial',{{'ElementIndex','IntProperty',0},{'Material','ObjectProperty',8}})
  signature('/Script/Engine.PlayerController:GetSpectatorPawn',{{'ReturnValue','ObjectProperty',0}})
  signature('/Script/Engine.Actor:AddComponentByClass',{{'Class','ClassProperty',0},{'bManualAttachment','BoolProperty',8},{'RelativeTransform','StructProperty',16},{'bDeferredFinish','BoolProperty',112},{'ReturnValue','ObjectProperty',120}})
  signature('/Script/Engine.ActorComponent:K2_DestroyComponent',{{'Object','ObjectProperty',0}})
  signature('/Script/Engine.MaterialInstanceDynamic:K2_GetScalarParameterValue',{{'ParameterName','NameProperty',0},{'ReturnValue','FloatProperty',8}})
  signature('/Script/Engine.MaterialInstanceDynamic:SetScalarParameterValue',{{'ParameterName','NameProperty',0},{'Value','FloatProperty',8}})
  signature('/Script/Engine.MaterialInstanceDynamic:CopyParameterOverrides',{{'MaterialInstance','ObjectProperty',0}})
  signature('/Script/Engine.KismetMaterialLibrary:CreateDynamicMaterialInstance',{{'WorldContextObject','ObjectProperty',0},{'Parent','ObjectProperty',8},{'OptionalName','NameProperty',16},{'CreationFlags','EnumProperty',24},{'ReturnValue','ObjectProperty',32}})
  local parentField=false
  StaticFindObject('/Script/Engine.MaterialInstance'):ForEachProperty(function(p)
   if p:GetFName():ToString()=='Parent'then
    assert(not parentField and p:GetFullName()=='ObjectProperty /Script/Engine.MaterialInstance:Parent'and p:GetPropertyClass():GetFullName()=='Class /Script/Engine.MaterialInterface','spectator_material_parent_schema_required');parentField=true
   end
  end);assert(parentField,'spectator_material_parent_field_required')
  primed=true
 end
 local function liveness(o)
  if o==nil then return'invalid'end
  local ok,value=pcall(function()
   local method=o.IsValid
   if type(method)~='function'then return nil end
   local live=method(o);if type(live)~='boolean'then return nil end
   return live
  end)
  if not ok or value==nil then return'unknown'end
  return value and'live'or'invalid'
 end
 local function usable(o)return liveness(o)=='live'end
 local function restore_gun(r)
  if not r.gun or r.gunRestored then return true end
  local live=liveness(r.gun)
  if live=='invalid'then r.gunRestored=true;return true end
  if live~='live'then return false end
  local known,restored=pcall(function()
   if identity(r.gun)~=r.gunIdentity or not same(r.gun:GetOwner(),r.target)or not same(r.gun:GetWorld(),world)then return false end
   local value=r.gun.bOwnerNoSee
   if value==r.gunOriginal then return true end
   if value~=false then return false end
   r.gun:SetOwnerNoSee(r.gunOriginal)
   return r.gun.bOwnerNoSee==r.gunOriginal
  end)
  if known and restored then r.gunRestored=true;return true end
  return false
 end
 local function weapon(r)
  local gun=r.target:GetGunMesh3P()
  if not valid(gun)then return end
  assert(same(gun:GetOwner(),r.target)and same(gun:GetWorld(),world),'spectator_weapon_owner_required')
  if not r.gun or not same(r.gun,gun)then
   assert(restore_gun(r),'spectator_weapon_restore_pending')
   local original=gun.bOwnerNoSee;assert(type(original)=='boolean','spectator_weapon_visibility_boolean_required')
   r.gun=gun;r.gunIdentity=identity(gun);r.gunOriginal=original;r.gunRestored=false
  end
  -- The native remote third-person gun is hidden from its view target by
  -- bOwnerNoSee. Expose only this exact viewer-local replica, preserving its
  -- material/animation and restoring the original flag when leaving it.
  if gun.bOwnerNoSee then gun:SetOwnerNoSee(false)end
  assert(gun.bOwnerNoSee==false,'spectator_weapon_visibility_not_observed')
 end
 local function release_keeper(r)
  if not r.keeper then return true end
  local live=liveness(r.keeper)
  if live=='invalid'then r.keeper=nil;return true end
  if live=='unknown'then r.cleanup_status='keeper_liveness_unknown';return false end
  local known,owned=pcall(function()
   return identity(r.keeper)==r.keeperIdentity and same(r.keeper:GetOwner(),r.keeperOwner)
    and same(pc:GetSpectatorPawn(),r.keeperOwner)and same(r.keeperOwner:GetWorld(),world)
    and same(r.keeperOwner:GetOwner(),pc)and same(r.keeperOwner.Controller,pc)
  end)
  if not known or owned~=true then
   r.cleanup_status='keeper_scope_changed';return false
  end
  r.keeper:K2_DestroyComponent(r.keeper);r.keeper=nil;return true
 end
 local function restore(r)
  -- Once both original presentation owners are explicitly invalid, no live
  -- slot remains to restore. Unknown wrappers/errors do not establish death.
  -- Release only our exact native reference holder; never query the dead mesh.
  if liveness(r.target)=='invalid'and liveness(r.mesh)=='invalid'then
   for _,slot in ipairs(r.slots or{})do slot.status='owner_destroyed'end
   r.cleanup_status='owner_destroyed'
   return release_keeper(r)
  end
  if not r.slots then return release_keeper(r)end
  local all=true
  for _,slot in ipairs(r.slots)do
   if not slot.restored then
    if not usable(r.mesh)then slot.status='unavailable_mesh'
    elseif not same(r.mesh:GetWorld(),world)or identity(r.mesh)~=r.meshIdentity then slot.status='scope_changed'
    elseif not usable(slot.original)or identity(slot.original)~=slot.originalIdentity then slot.status='unavailable_original'
    else
     local present=r.mesh:GetMaterial(slot.index)
     if same(present,slot.original)then slot.restored=true;slot.status='restored'
     elseif not same(present,slot.clone)or identity(slot.clone)~=slot.cloneIdentity then slot.status='conflict_preserved'
     else
      r.mesh:SetMaterial(slot.index,slot.original)
      assert(same(r.mesh:GetMaterial(slot.index),slot.original),'spectator_material_restore_not_observed')
      slot.restored=true;slot.status='restored'
     end
    end
   end
   if not slot.restored then all=false end
  end
  if all and restore_gun(r)then return release_keeper(r)end
  if not r.pendingReported then r.pendingReported=true;report('SPECTATOR_MATERIAL_CLEANUP_PENDING|target='..r.identity)end
  return false
 end
 local function sweep()
  for i=#records,1,-1 do
   local r=records[i]
   if r~=current and restore(r)then table.remove(records,i)end
  end
 end
 local function scalar(material,param)
  assert(valid(material)and material:IsA(StaticFindObject('/Script/Engine.MaterialInstanceDynamic')),'spectator_material_owned_mid_required')
  local value=material:K2_GetScalarParameterValue(param)
  assert(type(value)=='number'and value==value and math.abs(value)<math.huge,'spectator_material_scalar_number_required')
  return value
 end
 local function observe(target)
  assert(valid(target)and same(target,pc:GetViewTarget())and not target:HasAuthority()and same(target:GetWorld(),world),'spectator_material_exact_remote_target_required')
  assert(valid(target.PlayerState)and same(target.PlayerState.PawnPrivate,target),'spectator_material_reciprocal_target_required')
  if current and current.identity~=identity(target)then restore(current);current=nil end
  if current then return current end
  sweep();assert(#records<32,'spectator_material_retained_target_bound')
  local body=target:GetMesh3P()
  assert(valid(body)and same(body:GetWorld(),world)and same(body:GetOwner(),target),'spectator_material_body_mesh_required')
  local param=target.IsLocallyViewed1pParam;local name=param:ToString()
  assert(type(name)=='string'and #name>0 and #name<=256 and name~='None','spectator_material_native_parameter_required')
  local r={target=target,identity=identity(target),mesh=body,meshIdentity=identity(body),param=param,slots={}}
  current=r;records[#records+1]=r
  return r
 end
 local function clone_slots(r)
  assert(not r.originals,'spectator_material_clones_already_present')
  local library=StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary');assert(valid(library),'spectator_material_library_required')
  local count=r.mesh:GetNumMaterials();assert(type(count)=='number'and count%1==0 and count>=0 and count<=64,'spectator_material_slot_resource_bound')
  r.originals={}
  for index=0,count-1 do r.originals[index+1]=r.mesh:GetMaterial(index);assert(valid(r.originals[index+1]),'spectator_material_original_required')end
  -- Lua wrappers do not retain native objects for UE garbage collection.
  -- SetMaterial stores strong UPROPERTY OverrideMaterials references. A fresh
  -- meshless component has no visual/collision geometry and is owned only by
  -- this local native spectator pawn, never by an ordinary player/server.
  local owner=pc:GetSpectatorPawn()
  -- UE spawns this non-replicated pawn on the client, so it legitimately has
  -- local authority. Its exact controller/owner establishes observer scope;
  -- the network PlayerController above must still be a non-authority client.
  assert(valid(owner)and same(owner:GetWorld(),world)and same(owner:GetOwner(),pc)and same(owner.Controller,pc),'spectator_material_keeper_spectator_owner_required')
  r.keeperOwner=owner
  r.keeper=owner:AddComponentByClass(StaticFindObject('/Script/Engine.StaticMeshComponent'),false,{Rotation={X=0,Y=0,Z=0,W=1},Translation={X=0,Y=0,Z=0},Scale3D={X=1,Y=1,Z=1}},false)
  assert(valid(r.keeper)and same(r.keeper:GetOwner(),owner),'spectator_material_keeper_creation_failed')
  r.keeperIdentity=identity(r.keeper)
  for index=0,count-1 do
   r.keeper:SetMaterial(index*2,r.originals[index+1])
   assert(same(r.keeper:GetMaterial(index*2),r.originals[index+1]),'spectator_material_original_reference_not_observed')
  end
  for index=0,count-1 do
   local original=r.originals[index+1];local midClass=StaticFindObject('/Script/Engine.MaterialInstanceDynamic')
   local originalIsMid=original:IsA(midClass)
   local parent=originalIsMid and original.Parent or original
   assert(valid(parent)and not parent:IsA(midClass),'spectator_material_non_mid_parent_required')
   -- UE4SS's NameProperty boundary requires an actual FName userdata.
   local optionalName=FName('None');assert(type(optionalName)=='userdata','spectator_material_fname_userdata_required')
   local clone=library:CreateDynamicMaterialInstance(r.target,parent,optionalName,0)
   assert(valid(clone)and clone:IsA(midClass),'spectator_material_new_mid_required')
   for _,record in ipairs(records)do
    for _,saved in ipairs(record.originals or{})do assert(not same(clone,saved),'spectator_material_distinct_mid_required')end
    for _,saved in ipairs(record.slots or{})do assert(not same(clone,saved.clone),'spectator_material_fresh_mid_required')end
   end
   assert(same(clone.Parent,parent),'spectator_material_clone_parent_required')
   if originalIsMid then clone:CopyParameterOverrides(original)end
   local slot={index=index,original=original,originalIdentity=identity(original),clone=clone,cloneIdentity=identity(clone)}
   r.slots[#r.slots+1]=slot -- Ownership precedes either partially failing assignment.
   r.keeper:SetMaterial(index*2+1,clone)
   assert(same(r.keeper:GetMaterial(index*2+1),clone),'spectator_material_clone_reference_not_observed')
   r.mesh:SetMaterial(index,clone);assert(same(r.mesh:GetMaterial(index),clone),'spectator_material_clone_assignment_required')
  end
  report('SPECTATOR_MATERIAL_BOUND|target='..r.identity..'|slots='..count)
 end
 local function write(r,third)
  local desired=third and 0 or 1
  for _,slot in ipairs(r.slots)do
   assert(same(r.mesh:GetMaterial(slot.index),slot.clone)and identity(slot.clone)==slot.cloneIdentity,'spectator_material_slot_changed_externally')
   if scalar(slot.clone,r.param)~=desired then
    slot.clone:SetScalarParameterValue(r.param,desired)
    assert(scalar(slot.clone,r.param)==desired,'spectator_material_scalar_write_not_observed')
   end
  end
 end
 local self={}
 function self.apply(target,third)
  context();prime();assert(type(third)=='boolean','spectator_material_mode_required')
  local r=observe(target);target:UpdateMeshVisibility()
  if not r.originals then clone_slots(r)end
  weapon(r);write(r,third)
 end
 function self.poll(target,third)
  context();assert(type(third)=='boolean','spectator_material_mode_required')
  if not current or current.identity~=identity(target)then self.apply(target,third)
  else
   assert(same(target:GetMesh3P(),current.mesh)and same(current.mesh:GetWorld(),world),'spectator_material_body_mesh_changed')
   weapon(current);write(current,third)
  end
 end
 function self.retire()
  context();current=nil;sweep();return #records==0
 end
 function self.owned()return records end
 return self
end
