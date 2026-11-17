-- Viewer-local completion of the original Val spectator camera. Never grants
-- gameplay possession, changes the viewed player's server, or creates a pawn.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 local passive=env.passive==true
 local pc,ps,world,rig,nextHandle;local stopped=false;local started=false
 local ready=false;local lastNext=0;local lastTarget=nil
 local preferredThird=true
 local renderedThird=nil
 local skiPlaceholder=nil
 local lastHudScan=nil
 local materials=nil
 local retired={}
 local service={};local now=env.now or os.time
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()and a:GetFullName()==b:GetFullName()end
 local function identity(a)return a:GetFullName()..'|'..tostring(a:GetAddress())end
 local function restore_placeholder()
  local saved=skiPlaceholder
  skiPlaceholder=nil
  if saved and valid(saved.widget)and identity(saved.widget)==saved.identity
   and same(saved.widget:GetWorld(),world)and saved.widget:GetVisibility()==1 then
   saved.widget:SetVisibility(saved.visibility)
  end
 end
 local function ski_row(widget,textClass)
  local row=widget:GetParent()
  if not valid(row)or not row:IsA(StaticFindObject('/Script/UMG.PanelWidget')) then return false end
  local count=row:GetChildrenCount()
  if count<2 or count>6 then return false end
  for index=0,count-1 do
   local sibling=row:GetChildAt(index)
   if valid(sibling)and sibling:IsA(textClass)and sibling:GetText():ToString():upper()=='SKI TOGGLE' then return true end
  end
  return false
 end
 local function update_ski_hud()
  if skiPlaceholder then
   local widget=skiPlaceholder.widget
   if not valid(widget)or identity(widget)~=skiPlaceholder.identity
    or widget:GetText():ToString()~='Text Block' then restore_placeholder() end
   if skiPlaceholder then return end
  end
  local stamp=now()
  if stamp==lastHudScan then return end
  lastHudScan=stamp
  local textClass=StaticFindObject('/Script/UMG.TextBlock')
  if not valid(textClass)then return end
  local blocks=FindAllOf('TextBlock')or{}
  if #blocks>2048 then return end
  for _,widget in ipairs(blocks)do
   if valid(widget)and same(widget:GetWorld(),world)and widget:GetText():ToString()=='Text Block'
    and ski_row(widget,textClass)then
    local visibility=widget:GetVisibility()
    if visibility~=1 then
     skiPlaceholder={widget=widget,identity=identity(widget),visibility=visibility}
     widget:SetVisibility(1) -- ESlateVisibility::Collapsed
    end
    return
   end
  end
 end
 local function local_context()
  return valid(pc)and valid(ps)and same(pc.PlayerState,ps)and pc:IsLocalPlayerController()
   and not pc:HasAuthority()and same(pc:GetWorld(),world)and same(ps:GetWorld(),world)
 end
 local function guard()
  scope();assert(not stopped and local_context(),'spectator_client_context_changed')
  assert(ps:IsOnlyASpectator()and not valid(pc.Pawn),'spectator_client_observer_only_required')
 end
 local function prime()
  local callback=StaticFindObject('/Script/Topaz.TopGameMode_Topaz:OnGeneratorOnline');assert(valid(callback),'spectator_client_property_initializer_required')
  callback:ForEachProperty(function(p)assert(type(p.GetPropertyClass)=='function'and p:GetPropertyClass():GetFullName()=='Class /Script/Topaz.TopGenerator','spectator_client_object_binding_required')end)
  signature('/Script/Engine.PlayerState:IsOnlyASpectator',{{'ReturnValue','BoolProperty',0}})
  signature('/Script/Engine.Controller:GetViewTarget',{{'ReturnValue','ObjectProperty',0}})
  signature('/Script/Valhalla.ValCharacter:GetThirdPersonCameraAlpha',{{'ReturnValue','FloatProperty',0}})
  signature('/Script/Engine.PlayerCameraManager:GetCameraLocation',{{'ReturnValue','StructProperty',0}})
  signature('/Script/Engine.SceneComponent:K2_GetComponentLocation',{{'ReturnValue','StructProperty',0}})
  signature('/Script/Valhalla.ValPlayerController:ServerRequestStartSpectating',{})
  signature('/Script/Valhalla.ValPlayerController:ServerSpectateNext',{{'Direction','IntProperty',0}})
  signature('/Script/Engine.PlayerController:ServerViewSelf',{{'TransitionParams','StructProperty',0}})
  signature('/Script/Topaz.TopPlayerController:IsThirdPerson',{{'ReturnValue','BoolProperty',0}})
  signature('/Script/Topaz.TopPlayerController:ToggleThirdPerson',{})
  signature('/Script/Engine.PlayerController:GetSpectatorPawn',{{'ReturnValue','ObjectProperty',0}})
  signature('/Script/Engine.PlayerController:SetViewTargetWithBlend',{{'NewViewTarget','ObjectProperty',0},{'BlendTime','FloatProperty',8},{'BlendFunc','ByteProperty',12},{'BlendExp','FloatProperty',16},{'bLockOutgoing','BoolProperty',20}})
  signature('/Script/Engine.Actor:AddComponentByClass',{{'Class','ClassProperty',0},{'bManualAttachment','BoolProperty',8},{'RelativeTransform','StructProperty',16},{'bDeferredFinish','BoolProperty',112},{'ReturnValue','ObjectProperty',120}})
  signature('/Script/Engine.SceneComponent:K2_AttachToComponent',{{'Parent','ObjectProperty',0},{'SocketName','NameProperty',8},{'LocationRule','EnumProperty',16},{'RotationRule','EnumProperty',17},{'ScaleRule','EnumProperty',18},{'bWeldSimulatedBodies','BoolProperty',19},{'ReturnValue','BoolProperty',20}})
  signature('/Script/Engine.SceneComponent:K2_SetWorldRotation',{{'NewRotation','StructProperty',0},{'bSweep','BoolProperty',24},{'SweepHitResult','StructProperty',32},{'bTeleport','BoolProperty',264}})
  signature('/Script/Engine.Pawn:GetBaseAimRotation',{{'ReturnValue','StructProperty',0}})
  signature('/Script/Engine.ActorComponent:K2_DestroyComponent',{{'Object','ObjectProperty',0}})
  signature('/Script/Engine.Actor:K2_GetComponentsByClass',{{'ComponentClass','ClassProperty',0},{'ReturnValue','ArrayProperty',8}})
  local character=StaticFindObject('/Script/Valhalla.ValCharacter');assert(valid(character),'spectator_native_character_required')
  local fields={FirstPersonCameraComponent={'ObjectProperty',2024},ThirdPersonCameraBoom={'ObjectProperty',2032},ThirdPersonCameraComponent={'ObjectProperty',2040},bForceOnlySpectatorToThirdPerson={'BoolProperty',6896}}
  character:ForEachProperty(function(p)
   local name=p:GetFName():ToString();local expected=fields[name]
   if expected then assert(p:GetFullName()==expected[1]..' /Script/Valhalla.ValCharacter:'..name and p:GetOffset_Internal()==expected[2],'spectator_camera_field_changed='..name);fields[name]=nil end
  end);assert(next(fields)==nil,'spectator_camera_fields_required')
  local controller=StaticFindObject('/Script/Valhalla.ValPlayerController');assert(valid(controller),'spectator_native_controller_required')
  local idleField=false
  controller:ForEachProperty(function(p)
   if p:GetFName():ToString()=='AFKTimer'then
    assert(not idleField and p:GetFullName()=='FloatProperty /Script/Valhalla.ValPlayerController:AFKTimer'and p:GetOffset_Internal()==3924,'spectator_idle_field_changed');idleField=true
   end
  end);assert(idleField,'spectator_idle_field_required')
 end
 local function component_inventory(target)
  local raw=target:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.ActorComponent'))
  assert(type(raw)=='table'and #raw<=256,'spectator_camera_component_inventory_bound')
  local components={}
  -- UE4SS 1ba38db4 converts a returned object array to a Lua table of
  -- RemoteUnrealParam elements. Unwrap at this boundary; these parameters
  -- are not UObjects and do not provide IsValid/GetFullName themselves.
  for i,parameter in ipairs(raw)do
   assert(type(parameter)=='userdata'and type(parameter.get)=='function','spectator_camera_component_parameter_required')
   local component=parameter:get()
   assert(component and type(component.IsValid)=='function'and valid(component),'spectator_camera_component_object_required')
   assert(same(component:GetOwner(),target),'spectator_camera_inventory_owner_changed')
   components[i]=component
  end
  return components
 end
 local function release_rig()
  if materials then materials.retire()end
  if not rig then return true end
  local r=rig;local target=r.target
  local components=nil
  if valid(target)and identity(target)==r.identity then
   components=component_inventory(target)
  end
  if components and #components>=1 then
   -- The native camera manager may cache the component selected on entering
   -- a view target. Leave this exact actor before destroying that component.
   if valid(pc)and same(pc:GetViewTarget(),target)then
    assert(same(pc:GetWorld(),world)and pc:IsLocalPlayerController()and not pc:HasAuthority()and valid(pc.PlayerState)and pc.PlayerState:IsOnlyASpectator()and not valid(pc.Pawn),'spectator_camera_release_context_changed')
    local spectator=pc:GetSpectatorPawn()
    assert(valid(spectator)and same(spectator:GetWorld(),world),'spectator_camera_release_pawn_required')
    pc:SetViewTargetWithBlend(spectator,0,0,0,false)
    assert(same(pc:GetViewTarget(),spectator),'spectator_camera_release_view_unconfirmed')
   end
   -- A stored Lua wrapper is not a native lifetime guarantee. Never put an
   -- invalid original back into a reflected camera field during restoration.
   if r.camera and same(target.ThirdPersonCameraComponent,r.camera)then target.ThirdPersonCameraComponent=valid(r.originalCamera)and r.originalCamera or nil end
   if r.arm and same(target.ThirdPersonCameraBoom,r.arm)then target.ThirdPersonCameraBoom=valid(r.originalArm)and r.originalArm or nil end
   if r.changedForce and target.bForceOnlySpectatorToThirdPerson==false then target.bForceOnlySpectatorToThirdPerson=r.originalForce end
   for i=1,2 do local component,wanted;if i==1 then component,wanted=r.camera,r.cameraIdentity else component,wanted=r.arm,r.armIdentity end
    local present=false
    for _,current in ipairs(components)do if valid(current)and identity(current)==wanted then present=true end end
    if present then
     assert(valid(component)and identity(component)==wanted,'spectator_camera_component_identity_changed')
     assert(same(component:GetOwner(),target),'spectator_camera_cleanup_owner_changed')
     local address,name=component:GetAddress(),component:GetFullName()
     component:K2_DestroyComponent(component)
     -- ProcessEvent skips garbage objects, so calling IsBeingDestroyed on a
     -- destroyed wrapper returns an unusable default. The live actor owns the
     -- component inventory; verify removal there without querying the garbage.
     -- Refresh the owner's inventory for the next component too. The old
     -- snapshot still contains the camera just destroyed above; its garbage
     -- wrapper must never be queried while removing the arm.
     components=component_inventory(target)
     assert(#components>=1,'spectator_camera_component_inventory_bound')
     for _,current in ipairs(components)do
      assert(not(valid(current)and current:GetAddress()==address and current:GetFullName()==name),'spectator_camera_cleanup_unconfirmed')
     end
    end
   end
  else
   -- A destroyed actor no longer executes reflected queries, while UE4SS can
   -- still expose its garbage wrappers until native GC. Retain that exact
   -- ownership separately; never edit a replacement actor or claim cleanup.
   assert(#retired<64,'spectator_retired_camera_capacity_restart_viewer')
   retired[#retired+1]=r
   report('SPECTATOR_CAMERA_CLEANUP_PENDING|lease='..env.lease_id..'|count='..#retired)
  end
  rig=nil;return true
 end
 local function cleanup()
  restore_placeholder()
  return release_rig()
 end
 local function sweep_retired()
  for i=#retired,1,-1 do local r=retired[i]
   if not valid(r.target)and not valid(r.camera)and not valid(r.arm)then table.remove(retired,i)end
  end
 end
 local function target_rig(target)
  if rig and same(rig.target,target)then return end
  release_rig()
  assert(not target:HasAuthority()and same(target:GetWorld(),world),'spectator_camera_remote_replica_required')
  local r={target=target,identity=identity(target),originalCamera=target.ThirdPersonCameraComponent,originalArm=target.ThirdPersonCameraBoom,originalForce=target.bForceOnlySpectatorToThirdPerson}
  assert(type(r.originalForce)=='boolean','spectator_original_camera_policy_required')
  rig=r -- Retain every component immediately, even if later setup fails.
  if r.originalForce then target.bForceOnlySpectatorToThirdPerson=false;r.changedForce=true end
  -- Rendered remote avatars can have native camera subobjects that never
  -- update their transforms. Preserve them, but always bind one explicitly
  -- owned viewer-local rig instead of treating existence as camera readiness.
  local transform={Rotation={X=0,Y=0,Z=0,W=1},Translation={X=0,Y=0,Z=64},Scale3D={X=1,Y=1,Z=1}}
  r.arm=target:AddComponentByClass(StaticFindObject('/Script/Engine.SpringArmComponent'),false,transform,false)
  if valid(r.arm)then r.armIdentity=identity(r.arm)end
  assert(valid(r.arm)and same(r.arm:GetOwner(),target),'spectator_local_arm_creation_failed')
  r.arm.TargetArmLength=300;r.arm.bDoCollisionTest=true;r.arm.bUsePawnControlRotation=true
  transform.Translation.Z=0
  r.camera=target:AddComponentByClass(StaticFindObject('/Script/Engine.CameraComponent'),false,transform,false)
  if valid(r.camera)then r.cameraIdentity=identity(r.camera)end
  assert(valid(r.camera)and same(r.camera:GetOwner(),target),'spectator_local_camera_creation_failed')
  assert(r.camera:K2_AttachToComponent(r.arm,FName('SpringEndpoint'),0,0,0,false),'spectator_local_camera_attach_failed')
  target.ThirdPersonCameraBoom=r.arm;target.ThirdPersonCameraComponent=r.camera
  assert(same(target.ThirdPersonCameraBoom,r.arm)and same(target.ThirdPersonCameraComponent,r.camera),'spectator_local_camera_binding_failed')
 end
 local function current_target()
  local target=pc:GetViewTarget()
  local stateClass=StaticFindObject('/Script/Engine.PlayerState')
  if valid(target)and target:IsA(stateClass)then target=target.PawnPrivate end
  local characterClass=StaticFindObject('/Script/Valhalla.ValCharacter')
  if valid(target)and target:IsA(characterClass)and same(target:GetWorld(),world)and target.bInitialized==true
   and not same(target,pc.Pawn) then
   -- Replicated initialization can precede the PlayerState's pawn update.
   -- This boundary owns readiness; consumers must not assert through that lag.
   local state=target.PlayerState
   if valid(state)and not same(state,ps)and same(state:GetWorld(),world)and same(state.PawnPrivate,target)then return target end
  end
  return nil
 end
 local function refresh_camera(target)
  local spectator=pc:GetSpectatorPawn();assert(valid(spectator)and same(spectator:GetWorld(),world),'spectator_native_camera_pawn_required')
  -- Val's camera manager caches its component when the view target changes.
  -- Re-enter the same native target after installing a viewer-local rig or
  -- changing perspective; no server target or possession is changed.
  pc:SetViewTargetWithBlend(spectator,0,0,0,false)
  pc:SetViewTargetWithBlend(target,0,0,0,false)
 end
 local function select_perspective()
  local changed=pc:IsThirdPerson()~=preferredThird
  if changed then pc:ToggleThirdPerson()end
  assert(pc:IsThirdPerson()==preferredThird,'spectator_requested_perspective_required')
  return changed
 end
 local function update_presentation(target)
  -- The mode flag changes before the camera finishes blending. Use its
  -- distance from the eye camera so a close camera also works at walls.
  local threshold=renderedThird and 65 or 90
  local alpha=target:GetThirdPersonCameraAlpha()
  assert(type(alpha)=='number'and alpha>=0 and alpha<=1,'spectator_camera_alpha_invalid')
  local third=alpha>=threshold/300
  local eye=target.FirstPersonCameraComponent
  local manager=pc.PlayerCameraManager
  if valid(eye)and valid(manager)and same(eye:GetOwner(),target)then
   local camera=manager:GetCameraLocation()
   local origin=eye:K2_GetComponentLocation()
   local dx,dy,dz=camera.X-origin.X,camera.Y-origin.Y,camera.Z-origin.Z
   local distanceSquared=dx*dx+dy*dy+dz*dz
   -- A camera frame from the outgoing target can be one tick behind.
   if distanceSquared<=600*600 then third=distanceSquared>=threshold*threshold end
  end
  if third~=renderedThird then
   materials.apply(target,third)
   renderedThird=third
  else
   materials.poll(target,third)
  end
 end
 function service.action(action)
  if stopped or not pc then return end
  guard()
  if action=='next'or action=='previous'then pc:ServerSpectateNext(action=='next'and 1 or -1)
  elseif action=='first'or action=='third'then
   preferredThird=action=='third'
   local changed=select_perspective()
   local target=current_target()
   if changed and target and same(rig and rig.target,target)then refresh_camera(target)end
   report('SPECTATOR_VIEW|mode='..action)
  else error('spectator_unknown_camera_action')end
 end
 local function refresh_ski_hud()
  local hudOk,hudError=pcall(update_ski_hud)
  if not hudOk then
   report('SPECTATOR_HUD_SKIPPED|'..tostring(hudError))
   update_ski_hud=function()end
  end
 end
 local function follow()
  guard()
  refresh_ski_hud()
  -- The observer's selection survives native resets and target handoffs.
  local perspectiveChanged=select_perspective()
  -- Watching is intentionally passive. The original local AFK clock also
  -- kicks observer-only controllers; exempt this exact admitted viewer while
  -- its native spectator context remains valid, without manufacturing input
  -- or changing any ordinary player's AFK policy.
  local idle=pc.AFKTimer
  assert(type(idle)=='number'and idle==idle and idle>=0 and idle<math.huge,'spectator_idle_timer_invalid')
  pc.AFKTimer=0
  sweep_retired();local target=current_target()
  if not target then
   release_rig();lastTarget=nil;renderedThird=nil
   if now()-lastNext>=2 then lastNext=now();pc:ServerSpectateNext(1)end
   return
  end
  local changed=lastTarget~=identity(target)
  if changed then
   target_rig(target);lastTarget=identity(target);renderedThird=nil
  end
  if changed or perspectiveChanged then
   refresh_camera(target)
  end
  if changed then
   report('SPECTATOR_TARGET|lease='..env.lease_id..'|watch='..env.watch_id..'|player='..target:GetFullName())
  end
  update_presentation(target)
  if not ready then ready=true;report('SPECTATOR_READY|lease='..env.lease_id..'|watch='..env.watch_id..'|mode='..(preferredThird and'third'or'first'))end
 end
 local schedule
 schedule=function()
  if stopped then return end
  assert(not nextHandle,'spectator_duplicate_timer')
  local owned
  local function callback()
   if stopped then return end
   local ok,why=pcall(function()assert(owned==nextHandle,'spectator_timer_identity_changed');nextHandle=nil;follow();schedule()end)
   if not ok then
    stopped=true;local cleaned,reason=pcall(cleanup)
    report('RUNTIME_ERROR|spectator_camera|'..tostring(why)..(cleaned and''or'|cleanup_retained='..tostring(reason)))
   end
  end
  owned=ExecuteInGameThreadWithDelay(20,callback)
  assert(type(owned)=='number'and owned%1==0,'spectator_timer_registration_unknown');nextHandle=owned
 end
 local function key_action(action)
  return function()
   if stopped then return end
   ExecuteInGameThread(function()
    if stopped then return end
    local ok,why=pcall(function()
     guard()
     if pc.bShowMouseCursor==true then return end
     local selected=action
     if action=='toggle'then selected=preferredThird and 'first' or 'third'end
     service.action(selected)
    end)
    if not ok then stopped=true;local cleaned,reason=pcall(cleanup);report('RUNTIME_ERROR|spectator_input|'..tostring(why)..(cleaned and''or'|cleanup_retained='..tostring(reason)))end
   end)
  end
 end
 function service.tick(controller,state,gameState)
  assert(not passive,'spectator_lease_runtime_required')
  if not started then
   prime();pc=controller;ps=state;world=pc:GetWorld();guard()
   assert(same(gameState:GetWorld(),world),'spectator_game_state_world_required')
   assert(type(env.material_factory)=='function','spectator_material_factory_required')
   materials=env.material_factory({pc=pc,valid=valid,scope=scope,signature=signature,report=report})
   assert(type(materials)=='table'and type(materials.apply)=='function'and type(materials.poll)=='function'and type(materials.retire)=='function'and type(materials.owned)=='function','spectator_material_runtime_required')
   -- Retiring a local rig leaves the camera on the native spectator pawn.
   -- Reset the server's view target through its spectator-only RPC as well;
   -- otherwise a one-player server can suppress the unchanged target update
   -- when this viewer starts again. Reliable RPC order preserves the reset.
   select_perspective()
   started=true;pc:ServerViewSelf({BlendTime=0,BlendFunction=0,BlendExp=2,bLockOutgoing=false})
   pc:ServerRequestStartSpectating()
   RegisterKeyBind(Key.LEFT_MOUSE_BUTTON,key_action('next'))
   RegisterKeyBind(Key.RIGHT_MOUSE_BUTTON,key_action('previous'))
   RegisterKeyBind(Key.MIDDLE_MOUSE_BUTTON,key_action('toggle'))
   report('SPECTATOR_CONTROLS|left_click=next_player|right_click=previous_player|middle_click=toggle_camera')
   report('SPECTATOR_IDLE_POLICY|scope=local_observer_only')
   schedule()
  end
  guard()
 end
 function service.observe_native(controller,state,gameState)
  scope()
  assert(passive,'spectator_passive_runtime_required')
  if stopped or nextHandle then return end
  if started and (not same(controller,pc)or not same(state,ps)or not same(controller:GetWorld(),world))then
   started=false;materials=nil;lastTarget=nil;renderedThird=nil
  end
  pc,ps,world=controller,state,controller:GetWorld()
  if not local_context()or not same(gameState:GetWorld(),world)or ps:IsOnlyASpectator()
   or ps.r_bDead~=true or not current_target()then return end
  if not started then
   signature('/Script/Engine.Controller:GetViewTarget',{{'ReturnValue','ObjectProperty',0}})
   signature('/Script/Valhalla.ValCharacter:GetThirdPersonCameraAlpha',{{'ReturnValue','FloatProperty',0}})
   signature('/Script/Engine.PlayerCameraManager:GetCameraLocation',{{'ReturnValue','StructProperty',0}})
   signature('/Script/Engine.SceneComponent:K2_GetComponentLocation',{{'ReturnValue','StructProperty',0}})
   materials=env.material_factory({pc=pc,valid=valid,scope=scope,signature=signature,report=report,passive=true})
   started=true
  end
  local update
  update=function()
   nextHandle=nil
   if stopped then return end
   local ok,why=pcall(function()
    scope()
    local target
    if local_context()and not ps:IsOnlyASpectator()and ps.r_bDead==true then target=current_target()end
    if not target then
     restore_placeholder()
     if local_context()then materials.retire()end
     lastTarget=nil;renderedThird=nil
     return
    end
    if lastTarget~=identity(target)then
     materials.retire()
     lastTarget=identity(target);renderedThird=nil
     report('NATIVE_SPECTATOR_TARGET|'..target:GetFullName())
    end
    refresh_ski_hud()
    update_presentation(target)
    nextHandle=ExecuteInGameThreadWithDelay(20,update)
    assert(type(nextHandle)=='number','native_spectator_timer_registration_unknown')
   end)
   if not ok then
    stopped=true
    if local_context()then pcall(cleanup)end
    report('NATIVE_SPECTATOR_PRESENTATION_ERROR|'..tostring(why))
   end
  end
  update()
 end
 function service.retire()scope();cleanup();sweep_retired();stopped=true;return #retired==0 and(not materials or #materials.owned()==0)end
 function service.owned()return {rig=rig,retired=retired,materials=materials and materials.owned()or{},pc=pc,world=world,stopped=stopped}end
 return service
end
