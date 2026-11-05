-- Owns conversion from native world projection to this HUD canvas's DPI units.
return function(env)
 local valid=env.valid
 local layout=StaticFindObject('/Script/UMG.Default__WidgetLayoutLibrary')
 assert(valid(layout),'widget_layout_library_required')
 return function(entry,pc,flag,worldTarget)
  local widget=entry.widget;local slot=widget.Slot
  if not valid(slot) then return false end
  if not entry.layoutReady then
   slot:SetAutoSize(true);slot:SetAlignment({X=0.5,Y=0.5})
   slot:SetAnchors({Minimum={X=0,Y=0},Maximum={X=0,Y=0}})
   widget:ForceLayoutPrepass();entry.layoutReady=true
  end
  local viewport=layout:GetViewportSize(pc);local dpi=layout:GetViewportScale(pc)
  local desired=widget:GetDesiredSize()
  if dpi<=0 or desired.X<=0 or desired.Y<=0 then return false end
  local width,height=viewport.X/dpi,viewport.Y/dpi
  local edgeX,edgeY=(width-desired.X)/2-8,(height-desired.Y)/2-8
  if edgeX<=0 or edgeY<=0 then return false end
  -- The original widget's Tick resolves the holder mesh, flag location and its
  -- VectorOffset. Preserve that target instead of reinterpreting a carried flag.
  local target=worldTarget
  if target==nil then
   local location=flag:K2_GetActorLocation();target={X=location.X,Y=location.Y,Z=location.Z+200}
  end
  local out={};local front=pc:ProjectWorldLocationToScreen(target,out,true)
  local x,y
  if front then
   local screen=out.ScreenLocation or out
   x=screen.X/dpi-width/2;y=screen.Y/dpi-height/2
  else
   local camera=pc.PlayerCameraManager;if not valid(camera) then return false end
   local origin,rotation=camera:GetCameraLocation(),camera:GetCameraRotation()
   local yaw,pitch=math.rad(rotation.Yaw),math.rad(rotation.Pitch)
   local dx,dy,dz=target.X-origin.X,target.Y-origin.Y,target.Z-origin.Z
   x=-math.sin(yaw)*dx+math.cos(yaw)*dy
   y=math.sin(pitch)*math.cos(yaw)*dx+math.sin(pitch)*math.sin(yaw)*dy-math.cos(pitch)*dz
   if math.abs(x)+math.abs(y)<0.0001 then y=1 end
  end
  local factor=math.min(edgeX/math.max(math.abs(x),0.0001),edgeY/math.max(math.abs(y),0.0001))
  if front then factor=math.min(1,factor) end
  slot:SetPosition({X=width/2+x*factor,Y=height/2+y*factor})
  return true,(not front or factor<1)
 end
end
