-- Local cosmetic motion for the separately cooked Blizzard level.
-- Team objectives, pawn movement and weather lighting remain owned by the map/game.
return function(env)
 local valid,report=env.valid,env.report
 local package='/Game/Maps/Community/Snowblind/Arena_Snowblind_Blizzard_P'
 local prefix=package..'.Arena_Snowblind_Blizzard_P:'
 local states={}
 return function(context,pc)
  if not valid(context) or context:HasAuthority() or not context:GetFullName():find(prefix,1,true) then return end
  if not valid(pc) or not pc:IsLocalPlayerController() or pc:HasAuthority() then return end
  local world=context:GetWorld()
  if not valid(world) or pc:GetWorld():GetAddress()~=world:GetAddress() then return end
  local key=context:GetFullName()..'|'..string.format('%x',context:GetAddress())
  if states[key] then return end
  local clouds={}
  for _,actor in ipairs(FindAllOf('StaticMeshActor') or {}) do
   if valid(actor) and actor:GetWorld():GetAddress()==world:GetAddress() then
    local index=actor:GetFullName():match('^StaticMeshActor '..prefix:gsub('([^%w])','%%%1')..'PersistentLevel%.Snowblind_Snowfall_(%d+)$')
    if index then
     index=tonumber(index)
     assert(index>=0 and index<48,'snowfall_group_index_changed')
     clouds[#clouds+1]={actor=actor,index=index,speed=180+(index*37)%201,yaw=(index%4)*90}
    end
   end
  end
  assert(#clouds==48,'snowfall_expected_48_cooked_groups_got_'..#clouds)
  table.sort(clouds,function(a,b) return a.index<b.index end)
  for index,cloud in ipairs(clouds) do assert(cloud.index==index-1,'snowfall_group_identity_repeated') end
  local gameplay=StaticFindObject('/Script/Engine.Default__GameplayStatics')
  assert(valid(gameplay),'snowfall_gameplay_statics_missing')
  states[key]=true
  local last=nil
  local ticks=0
  local function tick()
   ExecuteInGameThreadWithDelay(20,function()
    if not valid(context) or not valid(pc) or not valid(world) then return end
    if context:GetWorld():GetAddress()~=world:GetAddress() or pc:GetWorld():GetAddress()~=world:GetAddress() then return end
    local ok,why=pcall(function()
     env.scope()
     local manager=pc.PlayerCameraManager
     if not valid(manager) then return end
     local location=manager:GetCameraLocation()
     local now=gameplay:GetTimeSeconds(context)
     local dt=last and math.max(0,math.min(now-last,1)) or 0
     last=now
     for _,cloud in ipairs(clouds) do
      assert(valid(cloud.actor),'snowfall_owned_group_lost')
      local old=cloud.z or (location.Z-1900+(cloud.index+.5)*4500/48)
      cloud.z=location.Z-1900+((old-cloud.speed*dt-(location.Z-1900))%4500)
      local dx=now*(240+(cloud.index*7)%220)+(cloud.index*317)%8000
      local dy=now*(-110+(cloud.index*11)%180)+(cloud.index*683)%8000
      local x=math.floor((location.X-dx)/8000+.5)*8000+dx
      local y=math.floor((location.Y-dy)/8000+.5)*8000+dy
      assert(cloud.actor:K2_TeleportTo({X=x,Y=y,Z=cloud.z},{Pitch=0,Yaw=cloud.yaw,Roll=0}),'snowfall_group_move_failed')
     end
     ticks=ticks+1
     if ticks%200==0 then report('SNOWFALL_SAMPLE|style=blizzard|ticks='..ticks..'|dt='..string.format('%.3f',dt)) end
    end)
    if not ok then report('SNOWFALL_ERROR|'..tostring(why));return end
    tick()
   end)
  end
  report('SNOWFALL_READY|style=blizzard|groups=48|requested_interval_ms=20|local_cosmetic=true')
  tick()
 end
end
