-- Viewer-local completion of the original Val spectator camera. Never grants
-- gameplay possession, changes the viewed player's server, or creates a pawn.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 local passive=env.passive==true
 local pc,ps,world,rig,nextHandle;local stopped=false;local started=false;local primed=false
 local ready=false;local lastNext=0;local lastTarget=nil
 local preferredThird=true
 local renderedThird=nil
 local cameraRefresh=false
 local modeRetryAt=nil
 local skiPlaceholder=nil
 local lastHudScan=nil
 local materials=nil
 local retired={}
 local service={};local now=env.now or os.time
 local chaseDistance,chaseHeight=580,48
 local cameraProbe,surfaceMargin=16,8
 local comfortableDistance=300
 local cameraAngles={{-14,0},{-34,0},{-26,55},{-26,-55}}
 local noColor={R=0,G=0,B=0,A=0}
 local chaseTrace='/Script/Engine.KismetSystemLibrary:SphereTraceSingleForObjects'
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
 local function observer_context()
  return local_context() and ps:IsOnlyASpectator() and not valid(pc.Pawn)
 end
 local function prime()
  if primed then return end
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
  signature('/Script/Engine.SceneComponent:K2_SetWorldLocationAndRotation',{{'NewLocation','StructProperty',0},{'NewRotation','StructProperty',24},
   {'bSweep','BoolProperty',48},{'SweepHitResult','StructProperty',56},{'bTeleport','BoolProperty',288}})
  signature('/Script/Engine.SceneComponent:SetAbsolute',{{'bNewAbsoluteLocation','BoolProperty',0},{'bNewAbsoluteRotation','BoolProperty',1},{'bNewAbsoluteScale','BoolProperty',2}})
  signature('/Script/Engine.SceneComponent:K2_SetWorldRotation',{{'NewRotation','StructProperty',0},
   {'bSweep','BoolProperty',24},{'SweepHitResult','StructProperty',32},{'bTeleport','BoolProperty',264}})
  signature('/Script/Engine.Pawn:GetBaseAimRotation',{{'ReturnValue','StructProperty',0}})
  signature(chaseTrace,{{'WorldContextObject','ObjectProperty',0},{'Start','StructProperty',8},{'End','StructProperty',32},
   {'Radius','FloatProperty',56},{'ObjectTypes','ArrayProperty',64},{'bTraceComplex','BoolProperty',80},
   {'ActorsToIgnore','ArrayProperty',88},{'DrawDebugType','ByteProperty',104},{'OutHit','StructProperty',112},
   {'bIgnoreSelf','BoolProperty',344},{'TraceColor','StructProperty',348},{'TraceHitColor','StructProperty',364},
   {'DrawTime','FloatProperty',380},{'ReturnValue','BoolProperty',384}})
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
  primed=true
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
 local function viewed_pawn()
  local target=pc:GetViewTarget()
  if valid(target) and target:IsA(StaticFindObject('/Script/Engine.PlayerState')) then return target.PawnPrivate end
  return target
 end
 local function spectator_pawn()
  local spectator=pc:GetSpectatorPawn()
  if valid(spectator) and same(spectator:GetWorld(),world) then return spectator end
 end
 local function release_rig()
  if not rig then
   if materials then materials.retire()end
   return true
  end
  local r=rig;local target=r.target
  local components=nil
  if valid(target)and identity(target)==r.identity then
   components=component_inventory(target)
  end
  if components and #components>=1 then
   -- The native camera manager may cache the component selected on entering
   -- a view target. Leave this exact actor before destroying that component.
   if valid(pc) and same(viewed_pawn(),target) then
    if not observer_context() then return false end
    local spectator=spectator_pawn()
    if not spectator then return false end
    pc:SetViewTargetWithBlend(spectator,0,0,0,false)
    if not same(pc:GetViewTarget(),spectator) then return false end
   end
  end
  if materials then materials.retire()end
  if components and #components>=1 then
   -- A stored Lua wrapper is not a native lifetime guarantee. Never put an
   -- invalid original back into a reflected camera field during restoration.
   if r.camera and same(target.ThirdPersonCameraComponent,r.camera)then target.ThirdPersonCameraComponent=valid(r.originalCamera)and r.originalCamera or nil end
   if r.arm and same(target.ThirdPersonCameraBoom,r.arm)then target.ThirdPersonCameraBoom=valid(r.originalArm)and r.originalArm or nil end
   if r.changedForce and target.bForceOnlySpectatorToThirdPerson==false then target.bForceOnlySpectatorToThirdPerson=r.originalForce end
   if r.first and same(target.FirstPersonCameraComponent,r.first) then
    target.FirstPersonCameraComponent=valid(r.nativeEye) and r.nativeEye or nil
   end
   for _,entry in ipairs({{r.first,r.firstIdentity},{r.camera,r.cameraIdentity},{r.arm,r.armIdentity}})do
    local component,wanted=entry[1],entry[2]
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
   if not valid(r.target)and not valid(r.first)and not valid(r.camera)and not valid(r.arm)then table.remove(retired,i)end
  end
 end
 local function allow_first_person(r)
  if not r.target.bForceOnlySpectatorToThirdPerson then return false end
  r.originalForce=true;r.changedForce=true
  r.target.bForceOnlySpectatorToThirdPerson=false
  return true
 end
 local function target_rig(target)
  if rig and same(rig.target,target)then return true end
  if not release_rig() then return false end
  assert(not target:HasAuthority()and same(target:GetWorld(),world),'spectator_camera_remote_replica_required')
  local r={target=target,identity=identity(target),originalCamera=target.ThirdPersonCameraComponent,originalArm=target.ThirdPersonCameraBoom,originalForce=target.bForceOnlySpectatorToThirdPerson}
  assert(type(r.originalForce)=='boolean','spectator_original_camera_policy_required')
  rig=r -- Retain every component immediately, even if later setup fails.
  allow_first_person(r)
  -- Rendered remote avatars can have native camera subobjects that never
  -- update their transforms. Preserve them, but always bind one explicitly
  -- owned viewer-local rig instead of treating existence as camera readiness.
  local transform={Rotation={X=0,Y=0,Z=0,W=1},Translation={X=0,Y=0,Z=0},Scale3D={X=1,Y=1,Z=1}}
  r.arm=target:AddComponentByClass(StaticFindObject('/Script/Engine.SpringArmComponent'),false,transform,false)
  if valid(r.arm)then r.armIdentity=identity(r.arm)end
  assert(valid(r.arm)and same(r.arm:GetOwner(),target),'spectator_local_arm_creation_failed')
  r.arm.TargetArmLength=chaseDistance
  r.arm.bDoCollisionTest=false
  r.arm.bUsePawnControlRotation=false
  r.camera=target:AddComponentByClass(StaticFindObject('/Script/Engine.CameraComponent'),false,transform,false)
  if valid(r.camera)then r.cameraIdentity=identity(r.camera)end
  assert(valid(r.camera)and same(r.camera:GetOwner(),target),'spectator_local_camera_creation_failed')
  local root=target.RootComponent
  assert(valid(root)and same(root:GetOwner(),target),'spectator_local_camera_root_required')
  r.camera:SetAbsolute(false,true,false)
  assert(r.camera:K2_AttachToComponent(root,FName('None'),0,0,0,false),'spectator_local_camera_attach_failed')
  target.ThirdPersonCameraBoom=r.arm;target.ThirdPersonCameraComponent=r.camera
  assert(same(target.ThirdPersonCameraBoom,r.arm)and same(target.ThirdPersonCameraComponent,r.camera),'spectator_local_camera_binding_failed')
  return true
 end
 local function update_first_person(r)
  local target=r.target
  local eye=target.FirstPersonCameraComponent
  if same(eye,r.first) then eye=r.nativeEye end
  if not valid(eye) or not same(eye:GetOwner(),target) then return false end
  if not valid(r.first) then
   local transform={Rotation={X=0,Y=0,Z=0,W=1},Translation={X=0,Y=0,Z=0},Scale3D={X=1,Y=1,Z=1}}
   r.first=target:AddComponentByClass(StaticFindObject('/Script/Engine.CameraComponent'),false,transform,false)
   assert(valid(r.first) and same(r.first:GetOwner(),target),'spectator_local_eye_creation_failed')
   r.firstIdentity=identity(r.first)
  end
  if not same(target.FirstPersonCameraComponent,r.first) then
   -- Attachment follows the native eye position at render cadence. Only
   -- rotate the viewer-owned camera, using the remote pawn's replicated aim.
   r.first:SetAbsolute(false,true,false)
   assert(r.first:K2_AttachToComponent(eye,FName('None'),2,0,0,false),'spectator_local_eye_attach_failed')
   r.nativeEye=eye
   target.FirstPersonCameraComponent=r.first
   cameraRefresh=true
  end
  local fov=eye.FieldOfView
  if type(fov)=='number' and fov>0 and fov<180 then r.first.FieldOfView=fov end
  local aim=target:GetBaseAimRotation()
  r.first:K2_SetWorldRotation({Pitch=aim.Pitch,Yaw=aim.Yaw,Roll=aim.Roll},false,{},true)
  return true
 end
 local function chase_endpoint(pivot,pitch,yaw,length)
  local p,y=math.rad(pitch),math.rad(yaw)
  local horizontal=length*math.cos(p)
  return {X=pivot.X-horizontal*math.cos(y),Y=pivot.Y-horizontal*math.sin(y),Z=pivot.Z-length*math.sin(p)}
 end
 local function chase_clearance(sys,r,pivot,pitch,yaw)
  local endpoint=chase_endpoint(pivot,pitch,yaw,chaseDistance)
  local hit={}
  -- WorldStatic only. A carried flag or nearby pawn must not retract the camera.
  if not sys:SphereTraceSingleForObjects(r.target,pivot,endpoint,cameraProbe,{0},true,{r.target},0,hit,true,noColor,noColor,0)then
   return chaseDistance
  end
  local time=hit.Time
  assert(type(time)=='number'and time>=0 and time<=1,'spectator_chase_trace_time_invalid')
  return math.max(0,chaseDistance*time-surfaceMargin)
 end
 local function update_chase(r)
  local sys=StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
  assert(valid(sys),'spectator_chase_system_library_required')
  local yaw=r.target:GetBaseAimRotation().Yaw
  local origin=r.target.RootComponent:K2_GetComponentLocation()
  local pivot={X=origin.X,Y=origin.Y,Z=origin.Z+chaseHeight}
  local bestDistance,bestPitch,bestYaw=-1,cameraAngles[1][1],yaw
  for _,angle in ipairs(cameraAngles)do
   local pitch,heading=angle[1],yaw+angle[2]
   local distance=chase_clearance(sys,r,pivot,pitch,heading)
   if distance>bestDistance then bestDistance,bestPitch,bestYaw=distance,pitch,heading end
   if bestDistance>=comfortableDistance then break end
  end
  -- Retract immediately for an obstacle and ease back as clearance returns.
  local length=r.chaseLength and math.min(bestDistance,r.chaseLength+45)or bestDistance
  r.chaseLength=length
  r.arm.TargetArmLength=length
  -- Remote actor components can retain the spring arm's initial socket pose.
  -- Write the checked viewpoint directly to the owned camera component.
  local location=chase_endpoint(pivot,bestPitch,bestYaw,length)
  r.camera:K2_SetWorldLocationAndRotation(location,{Pitch=bestPitch,Yaw=bestYaw,Roll=0},false,{},true)
 end
 local function current_target()
  local target=viewed_pawn()
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
  local spectator=spectator_pawn()
  if not spectator then return false end
  -- Val's camera manager caches its component when the view target changes.
  -- Re-enter the same native target after installing a viewer-local rig or
  -- changing perspective; no server target or possession is changed.
  pc:SetViewTargetWithBlend(spectator,0,0,0,false)
  if not same(pc:GetViewTarget(),spectator) then return false end
  pc:SetViewTargetWithBlend(target,0,0,0,false)
  return same(viewed_pawn(),target)
 end
 local function select_perspective()
  if pc:IsThirdPerson()==preferredThird then
   modeRetryAt=nil
   return true
  end
  cameraRefresh=true
  local stamp=now()
  if modeRetryAt and stamp<modeRetryAt then return false end
  pc:ToggleThirdPerson()
  if pc:IsThirdPerson()==preferredThird then
   modeRetryAt=nil
   return true
  end
  -- A native spectator transition can defer this toggle. Retry at most
  -- once per second while preserving the requested camera mode.
  modeRetryAt=stamp+1
  return false
 end
 local function native_third_person(target)
  -- The native death camera owns its perspective and can pass close to the
  -- remote avatar during blends and when moving around walls.
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
  return third
 end
 local function update_presentation(target)
  -- In spectator mode the selected view owns the body mask. Spring-arm
  -- collision can otherwise make chase view apply the first-person cutout.
  local third=preferredThird
  if passive then third=native_third_person(target)end
  if third~=renderedThird then
   materials.apply(target,third)
   renderedThird=third
  else
   materials.poll(target,third)
  end
 end
 local function apply_view(target)
  if allow_first_person(rig) then cameraRefresh=true end
  if not select_perspective() then return false end
  if preferredThird then
   update_chase(rig)
  elseif not update_first_person(rig) then
   return false
  end
  if cameraRefresh and not refresh_camera(target) then return false end
  cameraRefresh=false
  update_presentation(target)
  return true
 end
 function service.action(action)
  scope()
  if stopped or not observer_context() then return end
  if action=='next'or action=='previous'then pc:ServerSpectateNext(action=='next'and 1 or -1)
  elseif action=='first'or action=='third'then
   preferredThird=action=='third'
   cameraRefresh=true;modeRetryAt=nil
   local target=current_target()
   if target and same(rig and rig.target,target) then apply_view(target)
   else select_perspective()end
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
  scope()
  if not observer_context() then
   cameraRefresh=true
   return
  end
  refresh_ski_hud()
  -- Watching is intentionally passive. The original local AFK clock also
  -- kicks observer-only controllers; exempt this exact admitted viewer while
  -- its native spectator context remains valid, without manufacturing input
  -- or changing any ordinary player's AFK policy.
  local idle=pc.AFKTimer
  assert(type(idle)=='number'and idle==idle and idle>=0 and idle<math.huge,'spectator_idle_timer_invalid')
  pc.AFKTimer=0
  sweep_retired();local target=current_target()
  if not target then
   select_perspective()
   if release_rig() then lastTarget=nil;renderedThird=nil end
   if now()-lastNext>=2 then lastNext=now();pc:ServerSpectateNext(1)end
   return
  end
  local changed=lastTarget~=identity(target)
  if changed then
   if not target_rig(target) then return end
   lastTarget=identity(target);renderedThird=nil;cameraRefresh=true
   report('SPECTATOR_TARGET|lease='..env.lease_id..'|watch='..env.watch_id..'|player='..target:GetFullName())
  end
  if not apply_view(target) then return end
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
 local function key_action(action,mouse)
  return function()
   if stopped then return end
   ExecuteInGameThread(function()
    if stopped then return end
    local ok,why=pcall(function()
     if mouse and (not observer_context() or pc.bShowMouseCursor==true) then return end
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
  scope()
  if not started then
   pc=controller;ps=state;world=pc:GetWorld()
   if not local_context() or not same(gameState:GetWorld(),world)then return end
   prime()
   if not observer_context() then return end
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
   RegisterKeyBind(Key.LEFT_MOUSE_BUTTON,key_action('next',true))
   RegisterKeyBind(Key.RIGHT_MOUSE_BUTTON,key_action('previous',true))
   RegisterKeyBind(Key.MIDDLE_MOUSE_BUTTON,key_action('toggle',true))
   RegisterKeyBind(Key.F7,key_action('first'))
   RegisterKeyBind(Key.F8,key_action('third'))
   report('SPECTATOR_CONTROLS|left_click=next_player|right_click=previous_player|middle_click=toggle_camera|F7=first_person|F8=third_person')
   report('SPECTATOR_IDLE_POLICY|scope=local_observer_only')
   schedule()
  end
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
 function service.retire()
  scope()
  local cleaned=cleanup()
  sweep_retired()
  stopped=true
  return cleaned and #retired==0 and(not materials or #materials.owned()==0)
 end
 function service.owned()return {rig=rig,retired=retired,materials=materials and materials.owned()or{},pc=pc,world=world,stopped=stopped}end
 return service
end
