-- Private launcher runtime. All calls run on the game thread in this exact child.
local EXPECTED=@@EXPECTED@@
local OUTPUT=@@OUTPUT@@
local DESTINATION=@@DESTINATION@@
-- SPECTATOR_CLIENT_CONTRACT_V1
local SPECTATOR_ROLE=@@SPECTATOR_ROLE@@
local SPECTATOR_LEASE=@@MATCH_LEASE@@
local SPECTATOR_WATCH=@@WATCH_ID@@
local spectatorRuntime=nil
local MODE="BlueprintGeneratedClass /Game/Topaz/Game/BP_TopazGameMode_CTF_Persistent_BotBackfill.BP_TopazGameMode_CTF_Persistent_BotBackfill_C"
local joined=false
local nextHandle=nil
local stopped=false
local records={}
local recordCount=0
local written=0
local function valid(o) return o~=nil and o:IsValid() end
local function report(text)
    text=tostring(text):gsub("[\r\n]"," "):sub(1,2048)
    written=written+#text+1;assert(written<=1048576,"launcher_runtime_output_bound")
    local f=assert(io.open(OUTPUT,"ab"));assert(f:write(text,"\n"));assert(f:flush());assert(f:close())
end
local function loaded(path,identity)
    local o=StaticFindObject(path);assert(valid(o) and o:GetFullName()==identity,"loaded_identity_required="..path);return o
end
local function signature(path,fields)
    local fn=loaded(path,"Function "..path);local n=0
    fn:ForEachProperty(function(p)
        n=n+1;local field=assert(fields[n],"extra_function_parameter")
        assert(p:GetFullName()==field[2].." "..path..":"..field[1] and p:GetOffset_Internal()==field[3],"function_parameter_changed="..path)
    end);assert(n==#fields,"parameter_count_changed="..path)
end
local function scope()
    assert(IsInGameThread()==true,"game_thread_required")
    local sys=loaded("/Script/Engine.Default__KismetSystemLibrary","KismetSystemLibrary /Script/Engine.Default__KismetSystemLibrary")
    local c=sys:GetCommandLine();c=type(c)=="string" and c or c:ToString()
    assert(c:match("^%s*(.-)%s*$")==EXPECTED,"exact_owned_command_required")
    return sys
end
local mapDefinitions=assert(loadfile(@@MAP_DEFINITIONS@@))()
local configure_geometry=assert(loadfile(@@GEOMETRY@@))()({valid=valid,report=report,signature=signature,settings=assert(loadfile(@@LEVEL_SETTINGS@@))(),descriptors=mapDefinitions})
local configure_weather=assert(loadfile(@@SNOWBLIND_WEATHER@@))()({valid=valid,report=report,scope=scope,descriptors=mapDefinitions})
local allowedMaps={}
for name,row in pairs(mapDefinitions)do
 assert(name==row.name,"map_descriptor_identity_disagreement");allowedMaps[#allowedMaps+1]=row
end
local function player_key(pc) return pc:GetFullName()..'|'..string.format('%x',pc:GetAddress()) end
local function player_record(pc,ps)
    local key=player_key(pc)
    if not records[key] then
        assert(recordCount<64,"launcher_player_history_capacity_restart_client")
        records[key]={psName=ps:GetFullName(),psAddress=ps:GetAddress()};recordCount=recordCount+1
    end
    local r=records[key]
    assert(r.psName==ps:GetFullName() and r.psAddress==ps:GetAddress(),"player_state_identity_changed_restart_client")
    return r
end
local function state()
    local all=FindAllOf("ValGameState") or {};if #all~=1 or not valid(all[1]) then return nil end
    local recognized=false;for _,entry in ipairs(allowedMaps) do if all[1]:GetFullName():find(entry.world,1,true) then recognized=true end end
    if not recognized then return nil end
    return all[1]
end
local markerService=nil
local inputService=nil
-- BEGIN_WEAPON_INPUT_RECOVERY_V1|sha256=816a2c97f0ca5be92b4072752aeea2049c45c816d405743fa4b2aa1980f0feeb
local weaponInputFactory=(function()
-- Client-side completion of original weapon input and cancellation protocols.
-- Projectile creation, ammo, per-weapon last-shot times and cooldowns stay native.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 signature('/Script/GameplayAbilities.AbilitySystemComponent:ServerSetInputReleased',{{'AbilityHandle','StructProperty',0}})
 signature('/Script/GameplayAbilities.GameplayAbility:K2_CancelAbility',{})
 signature('/Script/Valhalla.ValCharacter:GetActiveEquippedAbility',{{'ReturnValue','StructProperty',0}})
 local masterPath='/Game/Abilities/Devices/Gun/GA_Gun_Master.GA_Gun_Master_C'
 local reloadPath='/Game/Abilities/Devices/Gun/GA_Gun_Master_Reload.GA_Gun_Master_Reload_C'
 local master=nil;local reloadMaster=nil;local state;local stopped=false
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

end)()
local weaponInput=weaponInputFactory({valid=valid,scope=scope,signature=signature,report=report})
-- END_WEAPON_INPUT_RECOVERY_V1
local function observe_markers(pc,ps,gs)
 weaponInput(pc,ps)
 if not inputService then inputService=assert(loadfile(@@JETPACK_INPUT@@))()({valid=valid,report=report,signature=signature,scope=scope}) end
 inputService(pc,ps)
 if not markerService then markerService=assert(loadfile(@@FLAG_MARKERS@@))()({valid=valid,report=report,signature=signature,scope=scope,projection=@@FLAG_PROJECTION@@}) end
 markerService(pc,ps,gs)
end

local clientWorld=nil
local lastJoin=0
-- Production network-client radar binding; authored settings stay native.
local releaseRadarGuardFactory=(function()
-- One owner for the network-client/explicit standalone diagnostic distinction.
return function(env)
 local valid,scope,signature=assert(env.valid),assert(env.scope),assert(env.signature)
 return function(pc,gs)
  scope()
  assert(valid(pc) and valid(gs) and pc:IsLocalPlayerController(),'radar_local_player_required')
  assert(valid(pc:GetWorld()) and valid(gs:GetWorld()) and pc:GetWorld():GetAddress()==gs:GetWorld():GetAddress(),'radar_same_world_required')
  if not pc:HasAuthority() then return 'network_client' end
  assert(env.allow_standalone==true,'radar_authoritative_client_requires_explicit_standalone_scope')
  signature('/Script/Engine.KismetSystemLibrary:IsStandalone',{{'WorldContextObject','ObjectProperty',0},{'ReturnValue','BoolProperty',8}})
  local system=StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
  assert(valid(system) and system:GetFullName()=='KismetSystemLibrary /Script/Engine.Default__KismetSystemLibrary','radar_native_system_library_required')
  assert(system:IsStandalone(pc)==true,'radar_listen_or_dedicated_host_is_not_standalone')
  return 'standalone_diagnostic'
 end
end

end)()
local releaseRadarHelperFactory=(function()
-- Local minimap capture/view binding only. Native radars, teams, power and
-- authored ValWorldSettings remain owners. No radar-online or map-scale patches.
return function(env)
 local valid,report,scope,signature=assert(env.valid),assert(env.report),assert(env.scope),assert(env.signature)
 local contracts=assert(env.blueprint_contracts);local prefix=assert(env.world_prefix)
 local projection=assert(env.projection,'radar_client_explicit_projection_contract_required')
 if env.allow_standalone then assert(type(env.client_context_guard)=='function','radar_standalone_requires_native_context_guard') end
 local state=nil;local retired=false;local checkedBlueprints=false
 local capturePath='/Game/Common/Blueprints/Cameras/BP_MinimapCapture.BP_MinimapCapture_C'
 local targetName='TextureRenderTarget2D /Game/Maps/Game/CrossFire/Crossfire_RenderTarget2D.Crossfire_RenderTarget2D'
 local function same(a,b) return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() end
 local function finite(n) return type(n)=='number' and n==n and n>-math.huge and n<math.huge end
 local function loaded(path,name)
  local o=StaticFindObject(path);assert(valid(o) and o:GetFullName()==name,'radar_client_loaded_identity='..path);return o
 end
 local function verify_blueprints()
  if checkedBlueprints then return end
  for name,contract in pairs(contracts) do
   assert((name=='UpdateTexture' or name=='UpdateSublevel' or name=='BindRadarSensors') and contract.parameters==0,'radar_client_unknown_blueprint_contract')
   local fn=loaded(contract.path,'Function '..contract.path);local found={};local count,want=0,0
   for _ in pairs(contract.fields) do want=want+1 end
   fn:ForEachProperty(function(p)
    local field=p:GetFName():ToString();local kind=p:GetFullName():match('^(%S+)')
    assert(not found[field] and contract.fields[field]==kind,'radar_client_blueprint_field_changed='..name..':'..field)
    found[field]=true;count=count+1
   end)
   assert(count==want,'radar_client_blueprint_schema_incomplete='..name)
  end
  assert(contracts.UpdateTexture and contracts.UpdateSublevel and contracts.BindRadarSensors);checkedBlueprints=true
 end
 local function original_settings(pc) return assert(env.world_settings_guard)(pc,env.descriptor) end
 local function own_world(pc,gs)
  scope();assert(not retired,'radar_client_retired')
  if env.client_context_guard then env.client_context_guard(pc,gs)
  else assert(valid(pc) and valid(gs) and pc:IsLocalPlayerController() and not pc:HasAuthority(),'radar_client_local_network_player_required') end
  assert(same(pc:GetWorld(),gs:GetWorld()) and gs:GetFullName():find(prefix,1,true),'radar_client_selected_world_required')
  if state then assert(same(pc,state.pc) and same(gs,state.gs) and same(pc:GetWorld(),state.world),'radar_client_world_changed') end
 end
 local function setup(pc,gs)
  own_world(pc,gs);verify_blueprints()
  local settings=original_settings(pc);local size=settings.MapSize;local world=pc:GetWorld()
  local ratio=projection.orthographic_width_per_map_size
  assert(finite(ratio) and ratio>0 and type(projection.source_reference)=='string' and projection.source_reference~='','radar_client_projection_source_required')
  local captureWidth=size*ratio;assert(finite(captureWidth),'radar_client_finite_capture_width_required')
  signature('/Script/Engine.Actor:GetActorBounds',{{'bOnlyCollidingComponents','BoolProperty',0},{'Origin','StructProperty',8},{'BoxExtent','StructProperty',32},{'bIncludeFromChildActors','BoolProperty',56}})
  signature('/Script/UMG.Widget:GetOwningPlayer',{{'ReturnValue','ObjectProperty',0}})
  signature('/Script/UMG.PanelWidget:GetChildrenCount',{{'ReturnValue','IntProperty',0}})
  local assembly=assert(env.find_assembly)(pc,gs)
  assert(valid(assembly) and same(assembly:GetWorld(),world),'radar_client_owned_map_assembly_required')
  local origin,extent={},{};assembly:GetActorBounds(true,origin,extent,false)
  for _,axis in ipairs({'X','Y','Z'}) do assert(finite(origin[axis]) and finite(extent[axis]) and extent[axis]>=0,'radar_client_finite_geometry_bounds_required') end
  local halfWidth=math.max(math.abs(origin.X)+extent.X,math.abs(origin.Y)+extent.Y)
  assert(captureWidth>=2*halfWidth,'radar_client_authored_capture_does_not_cover_map_bounds')
  local captures={};for _,a in ipairs(FindAllOf('BP_MinimapCapture_C') or {}) do if valid(a) and same(a:GetWorld(),world) then captures[#captures+1]=a end end
  assert(#captures==0,'radar_client_existing_capture_requires_map_owner_adoption')
  local class=StaticFindObject(capturePath);if not valid(class) then class=LoadAsset(capturePath) end
  assert(valid(class) and class:GetFullName()=='BlueprintGeneratedClass '..capturePath,'radar_client_original_capture_class_required')
  local height=math.max(100000,origin.Z+extent.Z+11000)
  -- Exact original Pitch=-90,Yaw=0,Roll=-90 converted by UE5.3's FRotator
  -- quaternion formula (UnrealMath.cpp530), avoiding opaque transform locals.
  local transform={Rotation={X=.5,Y=.5,Z=-.5,W=.5},Translation={X=0,Y=0,Z=height},Scale3D={X=1,Y=1,Z=1}}
  local api=loaded('/Script/Engine.Default__GameplayStatics','GameplayStatics /Script/Engine.Default__GameplayStatics')
  local actor=api:BeginDeferredActorSpawnFromClass(pc,class,transform,1,nil,0)
  assert(valid(actor),'radar_client_capture_begin_failed')
  state={pc=pc,gs=gs,world=world,settings=settings,map_size=size,capture_width=captureWidth,capture=actor,capture_name=actor:GetFullName(),widgets={},created=true,manual_capture=false}
  local finished=api:FinishSpawningActor(actor,transform,0);assert(same(actor,finished),'radar_client_capture_finish_identity')
  local component=actor.SceneCaptureComponent2D
  assert(valid(component) and same(component:GetOwner(),actor),'radar_client_original_capture_component_required')
  local target=component.TextureTarget
  assert(valid(target) and target:GetFullName()==targetName,'radar_client_original_material_target_required')
  assert(type(target.SizeX)=='number' and target.SizeX>0 and target.SizeX==target.SizeY,'radar_client_square_render_target_required')
  assert(component.ProjectionType==1,'radar_client_orthographic_projection_required')
  component.OrthoWidth=captureWidth
  component.MaxViewDistanceOverride=math.max(200000,math.sqrt(2*halfWidth*halfWidth+(height-origin.Z+extent.Z)^2)+1000)
  state.component=component;state.target=target
  report('BASE_RADAR_CLIENT_CAPTURE_CREATED|mapSize='..size..'|width='..component.OrthoWidth..'|projectionSource='..projection.source_reference..'|height='..height..'|target='..target:GetFullName()..'|pixels='..target.SizeX..'x'..target.SizeY)
 end
 local function bind_native_radars(widget,record)
  local canvas=widget.RadarSensors
  if not valid(canvas) then return false end
  local before=canvas:GetChildrenCount();assert(type(before)=='number' and before>=0 and before<=64,'radar_client_native_radar_canvas_capacity')
  local actors,teams={},{}
  for _,actor in ipairs(FindAllOf('BP_Objective_RadarSensor_C') or {}) do
   if valid(actor) and same(actor:GetWorld(),state.world) then
    assert(actor:GetClass():GetFullName()=='BlueprintGeneratedClass /Game/Topaz/Game/Objectives/BP_Objective_RadarSensor.BP_Objective_RadarSensor_C','radar_client_original_radar_class_required')
    actors[#actors+1]=actor
    local team=actor.r_TeamId;if team==1 or team==2 then assert(not teams[team],'radar_client_ambiguous_native_radar_team');teams[team]=actor end
   end
  end
  if #actors~=2 or not teams[1] or not teams[2] then return false end
  if before==0 then
   -- Invoke the exact original zero-parameter Blueprint only on its empty
   -- native canvas; it owns creation, binding, friendliness and positions.
   widget:BindRadarSensors()
   local after=canvas:GetChildrenCount();assert(after==2,'radar_client_original_bind_radar_canvas_count')
   record.radar_canvas_ready=true
   report('BASE_RADAR_CLIENT_RADAR_CANVAS_BOUND|widget='..widget:GetFullName()..'|before=0|after='..after..'|radarActors=2|owner=OriginalBindRadarSensors|onlineFlagWrites=0')
   return true
  end
  -- Native initialization may already have populated the canvas. Never
  -- clear/rebind it or create duplicate widgets to repair partial state.
  if before~=2 then return false end
  if not record.radar_canvas_ready then report('BASE_RADAR_CLIENT_RADAR_CANVAS_READY|widget='..widget:GetFullName()..'|before=2|nativeBindCalls=0|radarActors=2');record.radar_canvas_ready=true end
  return true
 end
 local service={}
 function service.tick(pc,gs)
  own_world(pc,gs)
  if not state then setup(pc,gs) end
  assert(valid(state.capture) and state.capture:GetFullName()==state.capture_name and same(state.capture:GetWorld(),state.world),'radar_client_capture_identity_changed')
  assert(same(original_settings(pc),state.settings) and state.settings.MapSize==state.map_size,'radar_client_authored_map_contract_changed')
  local count,bound=0,0
  for _,widget in ipairs(FindAllOf('UI_Game_Map_C') or {}) do
   if valid(widget) and same(widget:GetWorld(),state.world) and same(widget:GetOwningPlayer(),pc) then
    count=count+1;local key=widget:GetAddress()
    local previous=state.widgets[key]
    if previous and (not valid(previous.widget) or previous.name~=widget:GetFullName()) then state.widgets[key]=nil end
    if not state.widgets[key] and valid(widget.MapTexture) and valid(widget.Material) then
     local prior=widget.MinimapCapture
     assert(not valid(prior) or same(prior,state.capture),'radar_client_foreign_widget_capture')
     state.widgets[key]={widget=widget,name=widget:GetFullName(),prior=prior}
     widget.MinimapCapture=state.capture
     widget:UpdateSublevel() -- normal original settings/scale/zoom/texture initialization
     assert(finite(widget.CachedMapScale) and math.abs(widget.CachedMapScale-1024/state.map_size)<1e-8,'radar_client_native_widget_scale_mismatch')
     assert(same(widget.MapTexture.Brush.ResourceObject,widget.Material),'radar_client_native_material_binding_mismatch')
     report('BASE_RADAR_CLIENT_WIDGET_BOUND|widget='..widget:GetFullName()..'|cachedScale='..widget.CachedMapScale..'|mapScale='..widget.MapScale)
    end
    if state.widgets[key] then
     assert(same(widget.MinimapCapture,state.capture) and same(widget.MapTexture.Brush.ResourceObject,widget.Material),'radar_client_widget_binding_changed')
     if bind_native_radars(widget,state.widgets[key]) then bound=bound+1 end
    end
   end
  end
  state.widgets_seen=count;state.widgets_bound=bound
  return count>0 and bound==count
 end
 function service.owned() return state end
 function service.retire(reason)
  if retired then return false end
  retired=true
  -- The exact owned client world/process remains the capture's native lifetime
  -- owner. Keep the resource record until that owner confirms teardown; do not
  -- destroy a still-bound capture or clear a native widget during map travel.
  if state then state.retired_reason=tostring(reason or 'caller');state.engine_records_retained=true end
  report('BASE_RADAR_CLIENT_RETIRED|reason='..tostring(reason or 'caller')..'|engineRecordsRetained=true')
  return true
 end
 return service
end

end)()
local releaseRadarBlueprintContracts=(function()
-- Original complete schemas; CPF_Parm-derived zero-argument calls.
return {["UpdateTexture"]={["path"]="/Game/UI/Components/Game/UI_Game_Map.UI_Game_Map_C:UpdateTexture",["parameters"]=0,["fields"]={["CallFunc_GetLevelTexture_Texture"]="ObjectProperty",["CallFunc_IsValid_ReturnValue"]="BoolProperty",["CallFunc_IsValid_ReturnValue_1"]="BoolProperty"}},["UpdateSublevel"]={["path"]="/Game/UI/Components/Game/UI_Game_Map.UI_Game_Map_C:UpdateSublevel",["parameters"]=0,["fields"]={["CallFunc_GetWorldSettings_ReturnValue"]="ObjectProperty",["CallFunc_Divide_DoubleDouble_ReturnValue"]="DoubleProperty",["CallFunc_Multiply_DoubleDouble_ReturnValue"]="DoubleProperty",["CallFunc_GetGameState_ReturnValue"]="ObjectProperty",["CallFunc_SelectFloat_ReturnValue"]="DoubleProperty",["CallFunc_Multiply_VectorFloat_ReturnValue"]="StructProperty",["CallFunc_Conv_VectorToVector2D_ReturnValue"]="StructProperty",["CallFunc_Add_Vector2DVector2D_ReturnValue"]="StructProperty",["CallFunc_Divide_DoubleDouble_B_ImplicitCast"]="DoubleProperty",["K2Node_VariableSet_DefaultMaxZoom_ImplicitCast"]="DoubleProperty",["CallFunc_SelectFloat_B_ImplicitCast"]="DoubleProperty",["CallFunc_SelectFloat_A_ImplicitCast"]="DoubleProperty",["CallFunc_Multiply_VectorFloat_B_ImplicitCast"]="DoubleProperty"}},["BindRadarSensors"]={["path"]="/Game/UI/Components/Game/UI_Game_Map.UI_Game_Map_C:BindRadarSensors",["parameters"]=0,["fields"]={["Temp_int_Array_Index_Variable"]="IntProperty",["CallFunc_Create_ReturnValue"]="ObjectProperty",["Temp_int_Loop_Counter_Variable"]="IntProperty",["CallFunc_AddChildToCanvas_ReturnValue"]="ObjectProperty",["CallFunc_Add_IntInt_ReturnValue"]="IntProperty",["CallFunc_GetObjectClass_ReturnValue"]="ClassProperty",["CallFunc_Map_Find_Value"]="DoubleProperty",["CallFunc_Map_Find_ReturnValue"]="BoolProperty",["Temp_real_Variable"]="DoubleProperty",["CallFunc_Conv_DoubleToVector_ReturnValue"]="StructProperty",["Temp_bool_Variable"]="BoolProperty",["CallFunc_GetAllActorsOfClass_OutActors"]="ArrayProperty",["CallFunc_Array_Get_Item"]="ObjectProperty",["K2Node_Select_Default"]="DoubleProperty",["CallFunc_MakeVector2D_ReturnValue"]="StructProperty",["CallFunc_K2_GetActorLocation_ReturnValue"]="StructProperty",["CallFunc_IsValid_ReturnValue"]="BoolProperty",["CallFunc_Multiply_VectorVector_ReturnValue"]="StructProperty",["CallFunc_Conv_VectorToVector2D_ReturnValue"]="StructProperty",["CallFunc_Array_Length_ReturnValue"]="IntProperty",["CallFunc_Add_Vector2DVector2D_ReturnValue"]="StructProperty",["CallFunc_Less_IntInt_ReturnValue"]="BoolProperty",["CallFunc_Conv_DoubleToVector_InDouble_ImplicitCast"]="DoubleProperty"}}}

end)()
local releasePrimaryAssemblyFactory=(function()
-- Exact map assembly owner, from the canonical shared map descriptor.
return function(env)
 local valid,signature,scope=assert(env.valid),assert(env.signature),assert(env.scope)
 return function(context,descriptor)
  scope();assert(valid(context) and type(descriptor)=='table' and type(descriptor.world)=='string' and type(descriptor.assembly_asset)=='string','primary_assembly_explicit_descriptor_required')
  assert(context:GetFullName():find(descriptor.world,1,true),'primary_assembly_selected_world_required')
  signature('/Script/Engine.PrimitiveComponent:GetCollisionEnabled',{{'ReturnValue','ByteProperty',0}})
  signature('/Script/Engine.PrimitiveComponent:GetCollisionObjectType',{{'ReturnValue','ByteProperty',0}})
  local world=context:GetWorld();local selected,component=nil,nil
  for _,actor in ipairs(FindAllOf('StaticMeshActor') or {}) do
   if valid(actor) and actor:GetWorld():GetAddress()==world:GetAddress() then
    local c=actor.StaticMeshComponent;local mesh=valid(c) and c.StaticMesh or nil
    if valid(mesh) and mesh:GetFullName()=='StaticMesh '..descriptor.assembly_asset then
     assert(not selected,'primary_assembly_duplicate_exact_asset')
     assert(c:GetOwner():GetAddress()==actor:GetAddress() and c:GetWorld():GetAddress()==world:GetAddress() and c:GetCollisionEnabled()~=0 and c:GetCollisionObjectType()==0,'primary_assembly_native_static_collision_required')
     selected,component=actor,c
    end
   end
  end
  assert(selected,'primary_assembly_exact_asset_not_found');return selected,component
 end
end

end)()
local releaseNativeWorldSettingsFactory=(function()
-- The original UILibrary selects UWorld's actual native settings object.
-- One production owner for host and client descriptor/readback checks.
return function(env)
 local valid,signature,scope,report=assert(env.valid),assert(env.signature),assert(env.scope),assert(env.report)
 local library=nil;local emitted={}
 return function(context,descriptor)
  scope();assert(valid(context) and type(descriptor)=='table' and context:GetFullName():find(descriptor.world,1,true),'native_settings_selected_context_required')
  signature('/Script/ValhallaUI.UILibrary:GetWorldSettings',{{'WorldContextObject','ObjectProperty',0},{'ReturnValue','ObjectProperty',8}})
  if not valid(library) then library=StaticFindObject('/Script/ValhallaUI.Default__UILibrary') end
  assert(valid(library) and library:GetFullName()=='UILibrary /Script/ValhallaUI.Default__UILibrary','native_settings_original_library_required')
  local settings=library:GetWorldSettings(context);local world=context:GetWorld()
  assert(valid(settings) and valid(world) and settings:GetWorld():GetAddress()==world:GetAddress(),'native_settings_actual_same_world_owner_required')
  assert(descriptor.native_world_settings_class=='/Script/Valhalla.ValWorldSettings' and settings:GetClass():GetFullName()=='Class '..descriptor.native_world_settings_class,'native_settings_original_class_differs_from_descriptor')
  local size=settings.MapSize
  assert(type(size)=='number' and size==size and size>0 and size<math.huge and (descriptor.native==true or size==descriptor.map_size_cm),'native_settings_map_size_differs_from_descriptor')
  local read,name=pcall(function() return settings.MapName:ToString() end)
  if descriptor.native and (not read or type(name)~='string' or not name:match('%S'))then name=descriptor.name;read=true end
  if read then assert(type(name)=='string' and name:match('%S'),'native_settings_authored_map_name_empty') else name='unknown_native_text_readback' end
  local key=world:GetAddress()..'|'..settings:GetAddress()..'|'..settings:GetFullName()
  if not emitted[key] then
   emitted[key]=true
   report('BASE_WORLD_SETTINGS_NATIVE|map='..descriptor.name..'|size='..size..'|class='..descriptor.native_world_settings_class..'|mapName='..name:gsub('[\r\n|]',' '))
  end
  return settings
 end
end

end)()
local releaseRadarRuntimeFactory=(function()
-- Normal network clients only. Actual remote world owns map selection.
return function(env)
 local valid,report,scope=assert(env.valid),assert(env.report),assert(env.scope)
 local descriptors=assert(env.map_descriptors);local service=nil;local identity=nil;local retired={}
 local selectAssembly=assert(env.primary_assembly_factory)(env)
 local guard=assert(env.guard_factory)(env)
 local nativeSettings=assert(env.world_settings_guard_factory)(env)
 local runtime={}
 function runtime.tick(pc,gs)
  scope();guard(pc,gs)
  assert(not pc:HasAuthority() and not gs:HasAuthority(),'radar_runtime_network_client_required')
  local selected=nil;local count=0
  for _,descriptor in pairs(descriptors) do
   if gs:GetFullName():find(descriptor.world,1,true) then selected=descriptor;count=count+1 end
  end
  assert(count==1,'radar_runtime_exactly_one_actual_remote_map_required')
  if selected.native then return true end
  assert(selected.native_world_settings_class=='/Script/Valhalla.ValWorldSettings','radar_runtime_original_authored_settings_contract_required')
  local world=pc:GetWorld();local key=gs:GetFullName()..'|'..gs:GetAddress()..'|'..world:GetAddress()
  if identity~=key then
   if service then service.retire('remote_world_changed');retired[#retired+1]=service end
   local e={};for k,v in pairs(env) do e[k]=v end
   e.world_prefix=selected.world;e.client_context_guard=guard;e.descriptor=selected;e.world_settings_guard=nativeSettings
   e.projection={orthographic_width_per_map_size=1,source_reference='Original UI_Game_Map MapScale1024/MapSize and authored native ValWorldSettings; shared release source provenance'}
   e.find_assembly=function(context,state) return selectAssembly(state,selected) end
   service=assert(env.helper_factory)(e);identity=key
  end
  return service.tick(pc,gs)
 end
 function runtime.owned() return {current=service,identity=identity,retired=retired} end
 return runtime
end

end)()
local releaseRadarRuntime=releaseRadarRuntimeFactory({valid=valid,report=report,scope=scope,signature=signature,
 map_descriptors=mapDefinitions,guard_factory=releaseRadarGuardFactory,helper_factory=releaseRadarHelperFactory,
 primary_assembly_factory=releasePrimaryAssemblyFactory,world_settings_guard_factory=releaseNativeWorldSettingsFactory,blueprint_contracts=releaseRadarBlueprintContracts})

local function client_tick(sys)
    if joined and os.time()-lastJoin>=30 then
        local modes=FindAllOf('TopGameMode_Topaz') or {}
        if #modes==1 and valid(modes[1]) and modes[1]:GetFullName():find('/Game/Maps/Active/Drydock/Arena_Drydock_P.Arena_Drydock_P:',1,true) and sys:IsStandalone(modes[1]) then
            joined=false;report('RECONNECTING_TO_FIXED_SERVER')
        end
    end
    if not joined then
        local modes=FindAllOf("TopGameMode_Topaz") or {};if #modes~=1 or not valid(modes[1]) then return end
        local gm=modes[1]
        assert(gm:GetClass():GetFullName()==MODE and gm:GetFullName():find("/Game/Maps/Active/Drydock/Arena_Drydock_P.Arena_Drydock_P:",1,true) and gm:HasAuthority() and sys:IsStandalone(gm)==true,"initial_standalone_drydock_required")
        signature("/Script/Engine.GameplayStatics:OpenLevel",{{"WorldContextObject","ObjectProperty",0},{"LevelName","NameProperty",8},{"bAbsolute","BoolProperty",16},{"Options","StrProperty",24}})
        local name=FName(DESTINATION);assert(name:ToString()==DESTINATION)
        joined=true;lastJoin=os.time();report("JOIN_REQUESTED")
        loaded("/Script/Engine.Default__GameplayStatics","GameplayStatics /Script/Engine.Default__GameplayStatics"):OpenLevel(gm,name,true,SPECTATOR_ROLE=="spectator" and "SpectatorOnly=1" or "")
        return
    end
    local gs=state();if not gs or gs:HasAuthority() then return end
    configure_geometry(gs)
    if clientWorld~=gs:GetFullName() then clientWorld=gs:GetFullName();report("CLIENT_WORLD|"..clientWorld) end
    local pcs=FindAllOf("ValPlayerController") or {};if #pcs~=1 or not valid(pcs[1]) then return end
    local pc=pcs[1];if not pc:IsLocalPlayerController() or pc:HasAuthority() or not valid(pc.PlayerState) then return end
    configure_weather(gs,pc)
    local ps=pc.PlayerState
    if SPECTATOR_ROLE=="spectator" then
        if not spectatorRuntime then spectatorRuntime=assert(loadfile(@@SPECTATOR_RUNTIME@@))()({valid=valid,scope=scope,signature=signature,report=report,lease_id=SPECTATOR_LEASE,watch_id=SPECTATOR_WATCH,material_factory=assert(loadfile(@@SPECTATOR_MATERIAL_RUNTIME@@))()})end
        spectatorRuntime.tick(pc,ps,gs);return
    end
    assert(SPECTATOR_ROLE=="player","unknown_client_role")
    local plc=pc.PlayerLoadoutComponent;if not valid(plc) then return end
    local r=player_record(pc,ps)
    if valid(pc.Pawn) and pc.Pawn.bInitialized==true then observe_markers(pc,ps,gs);releaseRadarRuntime.tick(pc,gs);if not r.ready then r.ready=true;report("REMOTE_PAWN_READY|role=client") end;return end
    if r.selectionAttempted or valid(pc.Pawn) or (ps.r_TeamId~=1 and ps.r_TeamId~=2) or not plc:IsComponentReady() then return end
    local choices=plc.r_PlayerLoadouts;if choices:GetArrayNum()==0 then return end;assert(choices:GetArrayNum()<=64)
    local chosen=nil
    choices:ForEach(function(i,element)
        assert(i<64);local item=element:get();assert(item:GetFullName()=="ScriptStruct /Script/Valhalla.PlayerLoadout")
        local id=item.LoadoutId;assert(type(id)=="number" and id%1==0 and id>0);if chosen==nil then chosen=id end
    end)
    assert(chosen~=nil)
    signature("/Script/Valhalla.PlayerLoadoutComponent:RequestLoadout",{{"LoadoutId","IntProperty",0}})
    r.selectionAttempted=true;plc:RequestLoadout(chosen);report("LOADOUT_REQUESTED|"..chosen)
end
local schedule
schedule=function()
    if stopped then return end
    assert(nextHandle==nil)
    local owned
    local function callback()
        if stopped then return end
        local ok,why=pcall(function()
            assert(owned~=nil and owned==nextHandle);nextHandle=nil
            client_tick(scope())
            schedule()
        end)
        if not ok then stopped=true;report("RUNTIME_ERROR|"..tostring(why)) end
    end
    local ok,handle=pcall(ExecuteInGameThreadWithDelay,1000,callback)
    if not ok or type(handle)~="number" or handle%1~=0 then stopped=true;report("RUNTIME_ERROR|timer_registration_unknown_no_retry");return end
    owned=handle;nextHandle=handle
end
report("RUNTIME_LOADED|client");schedule()
