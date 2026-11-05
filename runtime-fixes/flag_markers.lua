-- Temporary private-client policy: collapse only the original floating-flag
-- overlay container. No marker widgets, projection hooks or timers are created.
return function(env)
 local valid,scope,report=assert(env.valid),assert(env.scope),assert(env.report)
 local lastPanel
 local function same(a,b)
  return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()and a:GetFullName()==b:GetFullName()
 end
 return function(pc,ps,gs)
  scope()
  if not valid(pc)or not valid(ps)or not valid(gs)or pc:HasAuthority()or not pc:IsLocalPlayerController()then return end
  if not same(pc.PlayerState,ps)or not same(pc:GetWorld(),gs:GetWorld())then return end
  local parent
  for _,overlay in ipairs(FindAllOf('UI_Game_Overlays_C')or{})do
   if valid(overlay)and overlay:GetFullName():find('/Engine/Transient.',1,true)and same(overlay:GetWorld(),pc:GetWorld())and valid(overlay.Flags)then
    assert(not parent,'multiple_runtime_flag_hud_containers')
    parent=overlay.Flags
   end
  end
  if not parent then return end
  assert(same(parent:GetWorld(),pc:GetWorld()),'flag_overlay_container_world_changed')
  -- ESlateVisibility::Collapsed, already used by the original flag widgets.
  -- Hiding their parent also suppresses any original native child markers.
  parent:SetVisibility(1)
  local identity=parent:GetFullName()..'|'..tostring(parent:GetAddress())
  if identity~=lastPanel then
   lastPanel=identity
   report('FLAG_MARKERS_HIDDEN|scope=floating_flag_overlay_container|widgetsCreated=0|projectionHooks=0')
  end
 end
end
