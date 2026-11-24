-- Cooked response names can differ from the retail project's configured names.
-- Restore the authored mask by native channel number on the marked map actors.
return function(env)
 local valid,scope,report=env.valid,env.scope,env.report
 local function same(a,b)
  return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()and a:GetFullName()==b:GetFullName()
 end
 local function signature(name,fields)
  local path='/Script/Engine.PrimitiveComponent:'..name
  local fn=StaticFindObject(path)
  assert(valid(fn)and fn:GetFullName()=='Function '..path,'perimeter_collision_signature_required')
  local count=0
  fn:ForEachProperty(function(p)
   count=count+1
   local expected=assert(fields[count],'perimeter_collision_extra_parameter')
   assert(p:GetFullName()=='ByteProperty '..path..':'..expected and p:GetOffset_Internal()==count-1,
          'perimeter_collision_signature_changed='..path)
  end)
  assert(count==#fields,'perimeter_collision_missing_parameter')
 end
 return function(context)
  scope()
  assert(valid(context),'perimeter_collision_context_required')
  local world=context:GetWorld()
  assert(valid(world),'perimeter_collision_world_required')
  local prefix='T3MissionPerimeter'
  local filter,wall,pawn,vehicle=FName(prefix..'Filtered'),FName(prefix),FName(prefix..'BlockPawn'),FName(prefix..'BlockVehicle')
  local plans={}
  for _,definition in ipairs({{'TriggerBox','CollisionComponent'},{'StaticMeshActor','StaticMeshComponent'}})do
   for _,actor in ipairs(FindAllOf(definition[1])or{})do
    if valid(actor)and same(actor:GetWorld(),world)and actor:ActorHasTag(filter)then
     assert(actor:ActorHasTag(wall)and actor:GetClass():GetFullName()=='Class /Script/Engine.'..definition[1],
            'perimeter_collision_owned_wall_required')
     local block_pawn,block_vehicle=actor:ActorHasTag(pawn),actor:ActorHasTag(vehicle)
     assert(block_pawn or block_vehicle,'perimeter_collision_empty_filter')
     local component=actor[definition[2]]
     assert(valid(component)and same(component:GetOwner(),actor)and same(component:GetWorld(),world),
            'perimeter_collision_owned_component_required')
     plans[#plans+1]={component=component,mask={[2]=block_pawn,[6]=block_vehicle}}
    end
   end
  end
  if #plans==0 then return false end
  signature('GetCollisionObjectType',{'ReturnValue'})
  signature('GetCollisionResponseToChannel',{'Channel','ReturnValue'})
  signature('SetCollisionResponseToChannel',{'Channel','NewResponse'})
  for _,plan in ipairs(plans)do
   assert(plan.component:GetCollisionObjectType()==0,'perimeter_collision_world_static_required')
  end
  local changed=0
  for _,plan in ipairs(plans)do
   for channel=0,31 do
    local expected=plan.mask[channel]and 2 or 0
    if plan.component:GetCollisionResponseToChannel(channel)~=expected then
     plan.component:SetCollisionResponseToChannel(channel,expected)
     assert(plan.component:GetCollisionResponseToChannel(channel)==expected,'perimeter_collision_mask_readback_failed')
     changed=changed+1
    end
   end
  end
  report(('MISSION_PERIMETER_COLLISION_READY|faces=%d|corrected=%d'):format(#plans,changed))
  return true
 end
end
