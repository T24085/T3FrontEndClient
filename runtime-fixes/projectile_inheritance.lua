return function(api)
 local valid, report = api.valid, api.report
 local world, own, roster
 local profiles, predicted = {}, {}
 local installed, failed
 local hook = '/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'

 local function same(a,b)
  return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()
 end

 local function read_profile(path)
  local stream = io.open(path,'rb')
  if not stream then return end
  local raw = stream:read(2049) or ''
  stream:close()
  assert(#raw <= 2048 and raw:sub(1,14)=='T3PROJECTILE1\n' and raw:sub(-1)=='\n',
         'invalid projectile settings file')
  local settings = {}
  for line in raw:sub(15):gmatch('([^\n]*)\n') do
   local key, forward, lateral = line:match('^([a-z0-9]+)|(%d%d?%d?)|(%d%d?%d?)$')
   forward, lateral = tonumber(forward), tonumber(lateral)
   assert(key and api.keys[key] and not settings[key] and forward <= 100 and lateral <= 100,
          'invalid projectile settings row')
   settings[key] = {forward / 100, lateral / 100}
  end
  return settings
 end

 local function profile(pawn,controller)
  if own then
   if not same(controller,own) or not controller:IsLocalPlayerController() then return end
   return profiles.localPlayer
  end
  if controller:IsLocalPlayerController() then return end
  local ps = controller.PlayerState
  if not valid(ps) or not same(ps.PawnPrivate,pawn) then return end
  local raw = ps.SavedNetworkAddress
  local address = raw and (type(raw)=='string' and raw or raw:ToString())
  if not address or not roster or not roster[address] or not address:match('^%d+%.%d+%.%d+%.%d+$') then return end
  if not profiles[address] then
   profiles[address]=read_profile(api.directory..'/'..address..'.txt')
  end
  return profiles[address]
 end

 local function apply(_,param)
  if not world or not valid(world) then return end
  local projectile = param:get()
  if not valid(projectile) or not projectile:HasAuthority() or not same(projectile:GetWorld(),world) then return end
  local weapon = api.classes[projectile:GetClass():GetFullName()]
  if not weapon then return end
  local pawn = projectile.Instigator
  if not valid(pawn) or not same(pawn:GetWorld(),world) then return end
  local controller = pawn.Controller
  if not valid(controller) or not same(controller.Pawn,pawn) then return end
  local settings = profile(pawn,controller)
  local axes = settings and settings[weapon]
  if not axes then return end
  local category = projectile.ProjectileVelocityInheritanceCategory
  local forward = projectile.InheritForwardVelocityPercent
  local lateral = projectile.InheritLateralVelocityPercent
  assert(type(category)=='number' and type(forward)=='number' and type(lateral)=='number',
         'projectile inheritance property layout changed')
  local ok,why = pcall(function()
   projectile.InheritForwardVelocityPercent=axes[1]
   projectile.InheritLateralVelocityPercent=axes[2]
   projectile.ProjectileVelocityInheritanceCategory=0
  end)
  if not ok then
   projectile.InheritForwardVelocityPercent=forward
   projectile.InheritLateralVelocityPercent=lateral
   projectile.ProjectileVelocityInheritanceCategory=category
   error(why)
  end
  if own then predicted[projectile:GetAddress()] = true end
 end

 local function finish(_, param)
  if not own then return end
  local projectile = param:get()
  if not valid(projectile) then return end
  local address = projectile:GetAddress()
  if not predicted[address] then return end
  predicted[address] = nil
  if not same(projectile:GetWorld(),world) then return end
  local movement = projectile.ProjectileMovement
  assert(valid(movement), 'predicted projectile movement is missing')
  local limit, velocity = movement.MaxSpeed, movement.Velocity
  local squared = velocity.X*velocity.X + velocity.Y*velocity.Y + velocity.Z*velocity.Z
  if limit > 0 and squared > limit*limit then
   -- Authority clamps at launch, before the predicting move component ticks.
   local factor = limit / math.sqrt(squared)
   movement.Velocity = {X=velocity.X*factor,Y=velocity.Y*factor,Z=velocity.Z*factor}
  end
 end

 local function guarded(callback)
  return function(...)
   local ok,why=pcall(callback,...)
   if not ok and not failed then
    failed=true
    report('PROJECTILE_INHERITANCE_ERROR|'..tostring(why):sub(1,250))
   end
  end
 end

 return function(active,controller,current_roster)
  if not valid(active) then return end
  if not same(world,active) then
   world, profiles, predicted = active, {}, {}
   if api.file then profiles.localPlayer = assert(read_profile(api.file),'missing projectile settings file') end
  end
  own, roster = controller, current_roster
  if not installed then
   api.scope()
   api.signature(hook,{{'Projectile','ObjectProperty',0},{'Transform','StructProperty',16},
                       {'ReturnValue','ObjectProperty',112}})
   RegisterHook(hook,guarded(apply),guarded(finish))
   installed=true
  end
 end
end
