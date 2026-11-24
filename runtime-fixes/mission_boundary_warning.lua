-- Local presentation for an authored boundary. No match state is changed.
return function(env)
 local valid,scope,report=assert(env.valid),assert(env.scope),assert(env.report)
 local now=env.now or os.time
 local state
 local prefix='T3MissionWarning'
 local max_vertices=32
 local out_of_bounds='OUT OF BOUNDS  ·  RETURN TO THE PLAY AREA'
 local flag_grace='RETURN TO THE FLAG AREA  ·  FLAG RETURN TIMER ACTIVE'
 local flag_messages={
  t3flagboundarydrop='FLAG DROPPED AT THE MISSION BOUNDARY',
  t3flagboundaryreturn='FLAG RETURNED HOME  ·  OUT OF BOUNDS',
 }
 local hook_attempted=false
 local function same(a,b)
  return a~=nil and b~=nil and valid(a) and valid(b)
     and a:GetAddress()==b:GetAddress() and a:GetFullName()==b:GetFullName()
 end
 local function tagged(actor,name)return actor:ActorHasTag(FName(prefix..name))end
 local function signature(path,fields)
  local fn=StaticFindObject(path)
  assert(valid(fn) and fn:GetFullName()=='Function '..path,'boundary_warning_function_required='..path)
  local count=0
  fn:ForEachProperty(function(prop)
   count=count+1
   local field=assert(fields[count],'boundary_warning_signature_changed='..path)
   assert(prop:GetFullName()==field[2]..' '..path..':'..field[1] and prop:GetOffset_Internal()==field[3],
          'boundary_warning_signature_changed='..path)
  end)
  assert(count==#fields,'boundary_warning_signature_changed='..path)
 end
 local function numbered(actor,prefix,min)
  local number
  for i=min,max_vertices do
   if tagged(actor,prefix..i)then
    assert(not number,'ambiguous_boundary_warning_marker')
    number=i
   end
  end
  return assert(number,'missing_boundary_warning_marker')
 end
 local function point(actor)
  local p=actor:K2_GetActorLocation()
  for _,axis in ipairs({'X','Y','Z'})do
   assert(type(p[axis])=='number' and math.abs(p[axis])<=1e7,'invalid_boundary_warning_location')
  end
  return {X=p.X,Y=p.Y,Z=p.Z}
 end
 local function cross(ax,ay,bx,by)return ax*by-ay*bx end
 local function next_index(i,vertices)return i%#vertices+1 end
 local function contains(zone,p)
  if (zone.floor and p.Z<zone.floor) or (zone.ceiling and p.Z>zone.ceiling) then return false end
  local vertices,inside=zone.vertices,false
  for i,a in ipairs(vertices)do
   local b=vertices[next_index(i,vertices)]
   local side=cross(b.X-a.X,b.Y-a.Y,p.X-a.X,p.Y-a.Y)
   if side==0 and p.X>=math.min(a.X,b.X) and p.X<=math.max(a.X,b.X)
      and p.Y>=math.min(a.Y,b.Y) and p.Y<=math.max(a.Y,b.Y) then return true end
   if (a.Y>p.Y)~=(b.Y>p.Y) and (side>0)==(b.Y>a.Y) then inside=not inside end
  end
  return inside
 end
 local function crossed_notch(zone,a,b)
  -- The endpoints may both be in bounds on a fast pass through a concave notch.
  local dx,dy=b.X-a.X,b.Y-a.Y
  if dx==0 and dy==0 then return false end
  local vertices,cuts=zone.vertices,{0,1}
  for i,c in ipairs(vertices) do
   local d=vertices[next_index(i,vertices)]
   local ex,ey=d.X-c.X,d.Y-c.Y
   local denominator=cross(dx,dy,ex,ey)
   if denominator~=0 then
    local t=cross(c.X-a.X,c.Y-a.Y,ex,ey)/denominator
    local u=cross(c.X-a.X,c.Y-a.Y,dx,dy)/denominator
    if t>0 and t<1 and u>=0 and u<=1 then cuts[#cuts+1]=t end
   end
  end
  table.sort(cuts)
  for i=2,#cuts do
   if cuts[i]-cuts[i-1]>1e-7 then
    local t=(cuts[i-1]+cuts[i])/2
    if not contains(zone,{X=a.X+t*dx,Y=a.Y+t*dy,Z=a.Z+t*(b.Z-a.Z)}) then return true end
   end
  end
  return false
 end
 local function read_zone(world)
  local cue
  for _,actor in ipairs(FindAllOf('AmbientSound') or {})do
   if valid(actor) and same(actor:GetWorld(),world) and (tagged(actor,'Cue') or tagged(actor,'FilteredCue'))then
    assert(not cue,'duplicate_boundary_warning_cue')
    cue=actor
   end
  end
  if not cue then return end
  local component=cue.AudioComponent
  assert(valid(component) and same(component:GetOwner(),cue) and valid(component.Sound),
         'boundary_warning_cue_required')
  local size=numbered(cue,'Count',3)
  local zone={vertices={},cue=cue,audio=component}
  local filtered=tagged(cue,'FilteredCue')
  local foot,vehicle=tagged(cue,'WarnFoot'),tagged(cue,'WarnVehicle')
  assert(filtered~=tagged(cue,'Cue') and (filtered and foot~=vehicle or not filtered and not foot and not vehicle),
         'invalid_boundary_warning_audience')
  if filtered then
   signature('/Script/Engine.Actor:GetAttachParentActor',{{'ReturnValue','ObjectProperty',0}})
   signature('/Script/Engine.PrimitiveComponent:GetCollisionObjectType',{{'ReturnValue','ByteProperty',0}})
   zone.audience=foot and 'foot' or 'vehicle'
   zone.character=StaticFindObject('/Script/Valhalla.ValCharacter')
   zone.pawn=StaticFindObject('/Script/Engine.Pawn')
   zone.primitive=StaticFindObject('/Script/Engine.PrimitiveComponent')
   zone.wheeled=StaticFindObject('/Script/ChaosVehicles.WheeledVehiclePawn')
   assert(valid(zone.character) and valid(zone.pawn) and valid(zone.primitive),
          'boundary_warning_audience_types_required')
  end
  for _,actor in ipairs(FindAllOf('TargetPoint') or {})do
   if valid(actor) and same(actor:GetWorld(),world) and tagged(actor,'')then
    if tagged(actor,'Floor') or tagged(actor,'Ceiling')then
     local cap=tagged(actor,'Floor') and 'floor' or 'ceiling'
     assert(not zone[cap],'duplicate_boundary_warning_cap')
     zone[cap]=point(actor).Z
    else
     local i=numbered(actor,'Vertex',1)
     assert(i<=size and not zone.vertices[i],'duplicate_boundary_warning_vertex')
     zone.vertices[i]=point(actor)
    end
   end
  end
  for i=1,size do assert(zone.vertices[i],'missing_boundary_warning_vertex') end
  assert(tagged(cue,'Floor')==(zone.floor~=nil) and tagged(cue,'Ceiling')==(zone.ceiling~=nil),
         'missing_boundary_warning_cap')
  assert(not zone.floor or not zone.ceiling or zone.floor<zone.ceiling,'invalid_boundary_warning_height')
  return zone
 end
 local function is_vehicle(zone,world,actor)
  if not valid(actor) or not same(actor:GetWorld(),world) or not actor:IsA(zone.pawn) then return false end
  if valid(zone.wheeled) and actor:IsA(zone.wheeled) then return true end
  local root=actor.RootComponent
  return valid(root) and root:IsA(zone.primitive) and same(root:GetOwner(),actor) and root:GetCollisionObjectType()==6
 end
 local function warning_actor(zone,world,pawn)
  if not zone.audience then return pawn end
  if pawn:IsA(zone.character) then
   local parent=pawn:GetAttachParentActor()
   if is_vehicle(zone,world,parent) then
    if zone.audience=='vehicle' then return parent end
   elseif zone.audience=='foot' then return pawn end
  elseif zone.audience=='vehicle' and is_vehicle(zone,world,pawn) then return pawn end
 end
 local function detach(row)
  if row and row.label and valid(row.label)then row.label:RemoveFromParent()end
  if row then row.label,row.text=nil,nil end
 end
 local function canvas(world)
  local cls=StaticFindObject('/Script/UMG.CanvasPanel')
  if not valid(cls)then return end
  for _,overlay in ipairs(FindAllOf('UI_Game_Overlays_C') or {})do
   if valid(overlay) and overlay:GetFullName():find('/Engine/Transient.',1,true)
      and same(overlay:GetWorld(),world) and valid(overlay.Flags)then
    local parent=overlay.Flags:GetParent()
    for _=1,12 do
     if not valid(parent)then break end
     if parent:IsA(cls)then return parent,overlay end
     parent=parent:GetParent()
    end
   end
  end
 end
 local function show(row,text)
  local panel,overlay=canvas(row.world)
  if not panel then detach(row);return end
  if valid(row.label) and same(row.label:GetParent(),panel)then
   if row.text~=text then row.label:SetText(FText(text));row.text=text end
   return
  end
  detach(row)
  local cls=StaticFindObject('/Script/UMG.TextBlock')
  assert(valid(cls),'boundary_warning_text_block_required')
  local label=StaticConstructObject(cls,overlay)
  assert(valid(label),'boundary_warning_create_failed')
  row.label,row.text=label,text
  label:SetText(FText(text))
  label:SetColorAndOpacity({SpecifiedColor={R=1,G=0.65,B=0.19,A=1},ColorUseRule=0})
  label:SetShadowColorAndOpacity({R=0,G=0,B=0,A=0.95})
  label:SetShadowOffset({X=2,Y=2})
  label:SetVisibility(4) -- SelfHitTestInvisible
  local slot=panel:AddChildToCanvas(label)
  assert(valid(slot),'boundary_warning_canvas_slot_required')
  local anchor={X=0.5,Y=0.26}
  slot:SetAnchors({Minimum=anchor,Maximum=anchor})
  slot:SetAlignment({X=0.5,Y=0.5})
  slot:SetAutoSize(true)
  slot:SetPosition({X=0,Y=0})
  slot:SetZOrder(50)
 end
 local function tick(row)
  local pc,ps,zone=row.pc,row.ps,row.zone
  if not valid(pc) or not valid(ps) or not pc:IsLocalPlayerController() or not same(pc.PlayerState,ps)
     or not same(pc:GetWorld(),row.world)then
   detach(row);return false
  end
  local pawn=pc.Pawn
  if not valid(pawn) or not same(pawn:GetWorld(),row.world) or ps.r_bDead==true then
   row.pawn,row.warning_actor,row.last,row.hold,row.notice,row.grace=nil,nil,nil,nil,nil,nil
   detach(row);return true
  end
  if not same(row.pawn,pawn)then
   row.pawn,row.warning_actor,row.last,row.hold=pawn,nil,nil,nil
   detach(row)
  end
  local warning
  if zone and valid(zone.cue) and same(zone.cue:GetWorld(),row.world)then
   local sampled=warning_actor(zone,row.world,pawn)
   if not same(row.warning_actor,sampled) then
    row.warning_actor,row.last,row.hold=sampled,nil,nil
   end
   if sampled then
    local at=point(sampled)
    local inside=contains(zone,at)
    if row.last and row.inside and (not inside or crossed_notch(zone,row.last,at))then
     if inside then row.hold=now()+3 end
     assert(valid(zone.audio) and same(zone.audio:GetOwner(),zone.cue),'boundary_warning_cue_changed')
     zone.audio:Play(0)
     report('MISSION_BOUNDARY_WARNING|crossed=true')
    end
    row.last,row.inside=at,inside
    if not inside or row.hold and now()<row.hold then warning=out_of_bounds end
   end
  end
  if row.grace then warning=flag_grace end
  local notice=row.notice
  if notice and now()<notice.expires then warning=notice.text else row.notice=nil end
  if warning then show(row,warning) else detach(row)end
  return true
 end
 local function hook_flag_notices(world)
  local found=false
  for _,marker in ipairs(FindAllOf('TargetPoint') or {})do
   if valid(marker) and same(marker:GetWorld(),world)
      and (marker:ActorHasTag(FName('T3MissionFlagMin')) or marker:ActorHasTag(FName('T3MissionFlagPolygon')))then
    found=true;break
   end
  end
  if not found then return false end
  if not hook_attempted then
   hook_attempted=true
   local installed,why=pcall(function()
    local path='/Script/Engine.PlayerController:ClientMessage'
    signature(path,{{'S','StrProperty',0},{'Type','NameProperty',16},{'MsgLifeTime','FloatProperty',24}})
    local pre,post=RegisterHook(path,function()end,function(context,_,kind)
     local row=state
     if not row or not row.flag_notices then return end
     local ok,problem=pcall(function()
      scope()
      local pc=context:get()
      if not same(pc,row.pc) or not same(pc:GetWorld(),row.world) or not pc:IsLocalPlayerController()
         or not same(pc.PlayerState,row.ps) then return end
      local tag=kind:get():ToString():lower()
      local text=flag_messages[tag]
      if text then
       row.grace=nil
       row.notice={text=text,expires=now()+4}
       report('MISSION_FLAG_LIMIT_NOTICE_RECEIVED')
      elseif tag=='t3flagboundarygrace' then
       row.grace=true
       row.notice=nil
       report('MISSION_FLAG_LIMIT_GRACE_NOTICE_RECEIVED')
      elseif tag=='t3flagboundarygracecleared' then
       row.grace=nil
       report('MISSION_FLAG_LIMIT_GRACE_NOTICE_CLEARED')
      end
     end)
     if not ok then report('MISSION_FLAG_LIMIT_HUD_UNAVAILABLE|'..tostring(problem):sub(1,260)) end
    end)
    assert(type(pre)=='number' and type(post)=='number','boundary_flag_notice_hook_required')
   end)
   if not installed then report('MISSION_FLAG_LIMIT_HUD_UNAVAILABLE|'..tostring(why):sub(1,260)) end
  end
  return true
 end
 local function schedule(row)
  local handle=ExecuteInGameThreadWithDelay(100,function()
   if state~=row then return end
   local ok,why=pcall(function()
    scope()
    if tick(row)then schedule(row)end
   end)
   if not ok then detach(row);report('MISSION_BOUNDARY_WARNING_UNAVAILABLE|'..tostring(why):sub(1,300))end
  end)
  assert(type(handle)=='number','boundary_warning_timer_required')
 end
 return function(pc,ps)
  if not valid(pc) or not valid(ps) or not pc:IsLocalPlayerController() or not same(pc.PlayerState,ps)then return end
  local world=pc:GetWorld()
  if not valid(world)then return end
  if state and same(state.pc,pc) and same(state.ps,ps) and same(state.world,world)then return end
  detach(state)
  state={pc=pc,ps=ps,world=world}
  local ok,why=pcall(function()
   scope()
   state.flag_notices=hook_flag_notices(world)
   local read,zone=pcall(read_zone,world)
   if read then state.zone=zone
   else report('MISSION_BOUNDARY_WARNING_UNAVAILABLE|'..tostring(zone):sub(1,300))end
   if state.zone or state.flag_notices then schedule(state)end
   if state.zone then report('MISSION_BOUNDARY_WARNING_READY')end
  end)
  if not ok then report('MISSION_BOUNDARY_WARNING_UNAVAILABLE|'..tostring(why):sub(1,300))end
 end
end
