local originalFactory=(function()
-- One owner for the native level's collision profiles. Exact private maps only.
return function(env)
 local valid,report=env.valid,env.report;local checked={};local signatures=false;local settings=assert(env.settings)
 local descriptors=assert(env.descriptors,'geometry_map_descriptors_required')
 assert(type(descriptors)=='table','geometry_map_descriptors_table_required')
 local seenWorlds={}
 for name,row in pairs(descriptors)do
  assert(type(name)=='string' and type(row)=='table','geometry_descriptor_row_required')
  assert(type(row.world)=='string' and row.world:match('^/Game/[^%s:]+%.[^%s:]+:$'),'geometry_descriptor_world_required')
  assert(row.native==true or (type(row.assembly_asset)=='string' and row.assembly_asset:match('^/Game/[^%s:]+%.[^%s:]+$')),'geometry_descriptor_asset_required')
  assert(not seenWorlds[row.world],'geometry_duplicate_descriptor_world');seenWorlds[row.world]=true
 end
 return function(context)
  local map,descriptor=nil,nil
  local contextName=context:GetFullName()
  for name,row in pairs(descriptors)do if contextName:find(row.world,1,true) then
   assert(descriptor==nil,'geometry_descriptor_world_ambiguous');map,descriptor=name,row
  end end
  assert(descriptor~=nil,'geometry_descriptor_missing_for_context')
  if map~='Damnation' and map~='HighOctane' and map~='Scarabrae' then return end
  local world=context:GetWorld();assert(valid(world));local prefix=descriptor.world
  local key=tostring(world:GetAddress())..'|'..prefix..'|'..descriptor.assembly_asset;if checked[key] then return end
  local statics=FindAllOf('StaticMeshActor') or {};local primaryActor=nil;local primaryCount=0
  for _,actor in ipairs(statics)do
   if valid(actor) and actor:GetFullName():find(prefix,1,true) and actor:GetWorld():GetAddress()==world:GetAddress() then
    local component=actor.StaticMeshComponent;assert(valid(component) and component:GetOwner():GetAddress()==actor:GetAddress())
    local mesh=component.StaticMesh
    if valid(mesh) and mesh:GetFullName()=='StaticMesh '..descriptor.assembly_asset then primaryActor=actor;primaryCount=primaryCount+1 end
   end
  end
  assert(primaryCount==1,'geometry_descriptor_primary_assembly_missing_or_ambiguous')
  if not signatures then
   env.signature('/Script/Engine.PrimitiveComponent:SetCollisionProfileName',{{'InCollisionProfileName','NameProperty',0},{'bUpdateOverlaps','BoolProperty',8}})
   env.signature('/Script/Engine.PrimitiveComponent:SetCollisionEnabled',{{'NewType','ByteProperty',0}})
   env.signature('/Script/Engine.Actor:SetActorEnableCollision',{{'bNewActorEnableCollision','BoolProperty',0}})
   env.signature('/Script/Engine.PrimitiveComponent:SetCastShadow',{{'NewCastShadow','BoolProperty',0}})
   env.signature('/Script/Engine.SceneComponent:SetMobility',{{'NewMobility','ByteProperty',0}})
   env.signature('/Script/Engine.SkyLightComponent:RecaptureSky',{})
   signatures=true
  end
  local assembly,sky=0,0
  for _,actor in ipairs(statics) do
   if valid(actor) and actor:GetFullName():find(prefix,1,true) and actor:GetWorld():GetAddress()==world:GetAddress() then
    local component=actor.StaticMeshComponent;assert(valid(component) and component:GetOwner():GetAddress()==actor:GetAddress())
    local mesh=component.StaticMesh
    if valid(mesh) then
     local name=mesh:GetFullName();local old=component:GetCollisionEnabled();local profile=component:GetCollisionProfileName():ToString()
     if actor:GetAddress()==primaryActor:GetAddress() then
      local body=mesh.BodySetup;assert(valid(body),'missing assembly collision body')
      report('ASSEMBLY_COLLISION_SOURCE|trace='..tostring(body.CollisionTraceFlag)..'|double='..tostring(body.bDoubleSidedGeometry)..'|enabled='..tostring(old)..'|profile='..profile)
      assert(body.CollisionTraceFlag==3 and body.bDoubleSidedGeometry,'unexpected cooked triangle collision settings')
      actor:SetActorEnableCollision(true);component:SetCollisionProfileName(FName('BlockAll'),true);component:SetCollisionEnabled(3)
      assert(actor:GetActorEnableCollision() and component:GetCollisionEnabled()==3);assembly=assembly+1
     elseif name=='StaticMesh /Game/Community/ClassicShared/SM_ClassicSkySphere.SM_ClassicSkySphere' then
      report('SKY_COLLISION_SOURCE|enabled='..tostring(old)..'|profile='..profile..'|actor='..tostring(actor:GetActorEnableCollision()))
      report('SKY_SHADOW_SOURCE|'..tostring(component.CastShadow));component:SetCastShadow(false);assert(not component.CastShadow)
      actor:SetActorEnableCollision(false);component:SetCollisionProfileName(FName('NoCollision'),true);component:SetCollisionEnabled(0)
      assert(not actor:GetActorEnableCollision() and component:GetCollisionEnabled()==0);sky=sky+1
     end
    end
   end
  end
  assert(assembly==1 and sky==1,'unexpected classic level geometry count')
  local sun_count,fill_count,sky_count=0,0,0
  for _,actor in ipairs(FindAllOf('DirectionalLight') or {}) do
   if valid(actor) and actor:GetFullName():find(prefix,1,true) and actor:GetWorld():GetAddress()==world:GetAddress() then
    local light=actor.LightComponent;assert(valid(light));local sun=actor:ActorHasTag(FName('T3ClassicSun'))
    report('LIGHT_SOURCE|sun='..tostring(sun)..'|intensity='..light.Intensity..'|mobility='..tostring(light.Mobility)..'|shadows='..tostring(light.CastShadows))
    light.bAtmosphereSunLight=sun;light.CastShadows=sun;light:SetMobility(2);light:SetIntensity(sun and settings.sun_intensity or settings.fill_intensity)
    if sun then actor:K2_SetActorRotation({Pitch=settings.sun_pitch,Yaw=settings.sun_yaw,Roll=0},true);sun_count=sun_count+1 else fill_count=fill_count+1 end
   end
  end
  for _,actor in ipairs(FindAllOf('SkyLight') or {}) do
   if valid(actor) and actor:GetFullName():find(prefix,1,true) and actor:GetWorld():GetAddress()==world:GetAddress() then
    local light=actor.LightComponent;assert(valid(light) and type(light.bRealTimeCapture)=='boolean');light.bRealTimeCapture=true;light:SetMobility(2);light:SetIntensity(settings.skylight_intensity);sky_count=sky_count+1
    if not context:HasAuthority() then
     ExecuteInGameThreadWithDelay(2000,function() if valid(context) and valid(light) and light:GetWorld():GetAddress()==world:GetAddress() then light:RecaptureSky() end end)
    end
   end
  end
  assert(sun_count==1 and fill_count==5 and sky_count==1,'unexpected classic level lighting count')
  report('CLASSIC_LIGHTING_READY|sun='..settings.sun_intensity..'|fill='..settings.fill_intensity..'|sky='..settings.skylight_intensity..'|pitch='..settings.sun_pitch)
  checked[key]=true;report('CLASSIC_GEOMETRY_READY|'..map..'|authority='..tostring(context:HasAuthority()))
 end
end

end)()
local edition2026Factory=(function()
-- Split terrain, structures and containment are explicit authored level members.
return function(env)
 local valid,report=assert(env.valid),assert(env.report);local descriptors=assert(env.descriptors);local reported={};local signatures=false
 return function(context)
  local descriptor=nil
  for _,row in pairs(descriptors)do
   if row.edition==2026 and context:GetFullName():find(row.world,1,true)then assert(not descriptor);descriptor=row end
  end
  if not descriptor then return end
  assert(#descriptor.geometry==31,'geometry_2026_member_contract')
  local world=context:GetWorld();assert(valid(world))
  if not signatures then
   env.signature('/Script/Engine.Actor:SetActorEnableCollision',{{'bNewActorEnableCollision','BoolProperty',0}})
   env.signature('/Script/Engine.PrimitiveComponent:SetCollisionProfileName',{{'InCollisionProfileName','NameProperty',0},{'bUpdateOverlaps','BoolProperty',8}})
   env.signature('/Script/Engine.PrimitiveComponent:SetCollisionEnabled',{{'NewType','ByteProperty',0}});signatures=true
  end
  local wanted={};local counts={terrain=0,structures=0,containment=0}
  for _,row in ipairs(descriptor.geometry)do
   assert(counts[row.kind]~=nil and type(row.actor)=='string'and row.actor:match('^[%w_]+$'))
   local key='StaticMeshActor '..descriptor.world..'PersistentLevel.'..row.actor;assert(not wanted[key]);wanted[key]=row
  end
  for _,actor in ipairs(FindAllOf('StaticMeshActor')or{})do
   if valid(actor)and actor:GetWorld():GetAddress()==world:GetAddress()then
    local row=wanted[actor:GetFullName()]
    if row then
     local c=actor.StaticMeshComponent;assert(valid(c)and c:GetOwner():GetAddress()==actor:GetAddress())
     local mesh=c.StaticMesh;assert(valid(mesh)and mesh:GetFullName()=='StaticMesh '..row.asset,'geometry_2026_asset_identity')
     if row.kind~='containment'then local body=mesh.BodySetup;assert(valid(body)and body.CollisionTraceFlag==3 and body.bDoubleSidedGeometry,'geometry_2026_triangle_collision')end
     if not actor:GetActorEnableCollision()then actor:SetActorEnableCollision(true)end
     if c:GetCollisionProfileName():ToString()~='BlockAll'then c:SetCollisionProfileName(FName('BlockAll'),true)end
     if c:GetCollisionEnabled()~=3 then c:SetCollisionEnabled(3)end
     assert(actor:GetActorEnableCollision()and c:GetCollisionEnabled()==3)
     if row.kind=='containment'then assert(actor.bHidden and not c.bVisible,'geometry_2026_hidden_containment')end
     counts[row.kind]=counts[row.kind]+1;wanted[actor:GetFullName()]=nil
    end
   end
  end
  assert(counts.terrain==25 and counts.structures==1 and counts.containment==5,'geometry_2026_missing_authored_members')
  for _ in pairs(wanted)do error('geometry_2026_missing_actor')end
  local key=context:GetFullName()..'|'..string.format('%x',context:GetAddress())
  if not reported[key]then reported[key]=true;report('GEOMETRY_2026_READY|'..descriptor.name..'|terrain=25|structures=1|containment=5')end
 end
end

end)()
return function(env)
 local original=originalFactory(env);local newer=edition2026Factory(env)
 return function(...) original(...);newer(...) end
end
