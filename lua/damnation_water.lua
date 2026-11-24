-- Client-local splashes for map-authored liquids and collidable community water.
local INTERVAL_MS = 50
local SPLASH_SECONDS = 0.85
local MIN_SPEED = 350 -- cm/s
local WATER_LANDING_SPEED = 120

local function contact(previous, current, surface, dt)
    local before = previous.Z - surface.z
    local after = current.Z - surface.z
    local change = after - before
    local direction = before < 0 and 'exit' or 'enter'
    local threshold = surface.profile and (direction=='exit' and surface.profile.exit or surface.profile.minimum)
        or surface.minimum or MIN_SPEED
    if dt<=0 or math.abs(change)<threshold*dt then return end
    if surface.ski then
        -- The capsule stops above the plane when it contacts the ski surface.
        if before <= 28 or after > 28 then return end
    elseif (before >= 0) == (after >= 0) then
        return
    end
    local alpha = math.max(0, math.min(1, -before / change))
    local x = previous.X + (current.X - previous.X) * alpha
    local y = previous.Y + (current.Y - previous.Y) * alpha
    if x < surface.xmin or x > surface.xmax or y < surface.ymin or y > surface.ymax then return end
    return x, y, math.abs(change) / dt, direction
end

local function discover(world, valid)
    local surfaces, slots = {}, {}
    local function visit(class, callback)
        for _, actor in ipairs(FindAllOf(class) or {}) do
            if valid(actor) and actor:GetWorld():GetAddress() == world:GetAddress() then
                actor.Tags:ForEach(function(_, tag) callback(actor, tag:get():ToString()) end)
            end
        end
    end
    visit('StaticMeshActor', function(actor, tag)
        if tag == 'DamnationSplash' then
            slots[#slots + 1] = {actor=actor}
        elseif tag:match('^DamnationSkiWater%d%d$') then
            local p = actor:K2_GetActorLocation()
            -- Each original lake lies within its 2150.4 m terrain tile.
            surfaces[#surfaces + 1] = {ski=actor.StaticMeshComponent, z=p.Z,
                xmin=p.X-107520, xmax=p.X+107520, ymin=p.Y-107520, ymax=p.Y+107520}
        end
    end)
    if #slots == 0 then return end -- An older map overlay is installed.
    visit('WaterBodyCustom', function(actor, tag)
        local width, length = tag:match('^DamnationBasin:(%d+):(%d+)$')
        if width then
            local p = actor:K2_GetActorLocation()
            surfaces[#surfaces + 1] = {z=p.Z, xmin=p.X, xmax=p.X+tonumber(width),
                ymin=p.Y-tonumber(length), ymax=p.Y}
        end
    end)
    if #surfaces ~= 77 or #slots ~= 12 then return end
    return surfaces, slots
end

local water_materials = {
    ['/Game/Community/Stonehenge/Wildlands2026/Materials/M_Lake.M_Lake']=true,
    ['/Game/Community/Biomes2026/Materials/M_Scarabrae_Lake.M_Scarabrae_Lake']=true,
    ['/Game/Community/Biomes2026/Materials/M_Snowblind_Lake.M_Snowblind_Lake']=true,
    ['/Game/Community/Rollercoaster/Oasis2026/Materials/M_OasisWater.M_OasisWater']=true,
    ['/Game/Community/Damnation2026Shoreline/M_Damnation_LakeSurface.M_Damnation_LakeSurface']=true,
    ['/Game/Community/Damnation2026WaterMotion/M_Damnation_AnimatedWater.M_Damnation_AnimatedWater']=true,
    ['/Game/Community/RaindanceT2/Edition2026/Water/M_RT2_Water.M_RT2_Water']=
        '/Game/Community/RaindanceT2/Edition2026/Water/SM_RT2_WaterSurface.SM_RT2_WaterSurface',
}

local function object_path(object, valid)
    if valid(object) then return object:GetFullName():match('%S+$') end
end

local function discover_water(world, valid)
    local system=StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
    if not valid(system) then return end
    local surfaces={}
    for _,actor in ipairs(FindAllOf('StaticMeshActor') or {}) do
        if valid(actor) and actor:GetWorld():GetAddress()==world:GetAddress() then
            local mesh=actor.StaticMeshComponent
            if valid(mesh) then
                local water=water_materials[object_path(mesh:GetMaterial(0),valid)]
                local collision=water and mesh:GetCollisionEnabled()~=0
                local sheet=type(water)=='string' and water==object_path(mesh.StaticMesh,valid)
                if collision or sheet then
                    local origin,extent={},{}
                    system:GetComponentBounds(mesh,origin,extent,{})
                    origin,extent=origin.Origin or origin,extent.BoxExtent or extent
                    -- The authored rectangular sheet has no gameplay collision. Only
                    -- accept it as a crossing plane when its bounds are horizontal.
                    if extent.X and extent.Y and extent.X>0 and extent.Y>0 and (collision or extent.Z<=1) then
                        surfaces[#surfaces+1]={ski=collision and mesh or nil,z=origin.Z+extent.Z,minimum=WATER_LANDING_SPEED,
                            xmin=origin.X-extent.X,xmax=origin.X+extent.X,
                            ymin=origin.Y-extent.Y,ymax=origin.Y+extent.Y}
                    end
                end
            end
        end
    end
    if #surfaces>0 then return surfaces,{} end
end

-- Native movement samples drive local, map-authored liquid effects.
local defaults = {
    minimum=367.5, medium=735, hard=2205, exit=367.5, inner=1500, range=10000,
    cooldown=.20, life=.85, gain={easy=.50, medium=.71, hard=.89, exit=.42},
    sounds={}, pitch_jitter=.06, volume_jitter=.10,
}
local land_water='/Game/Audio/SFX/PC/Player_Movement/Player_Land/Waves/Land_Water/'
local stock_water = {
    inner=defaults.inner,range=defaults.range,gain=defaults.gain,
    pitch_jitter=defaults.pitch_jitter,volume_jitter=defaults.volume_jitter,
    medium=735,hard=2205,
    sounds={easy=land_water..'Land_Water_01.Land_Water_01',
            medium=land_water..'Land_Water_02.Land_Water_02',
            hard=land_water..'Land_Water_03.Land_Water_03',
            exit=land_water..'Land_Water_01.Land_Water_01'},
}
local stock_splash='/Game/VFX/Abilities/Sprint/NS_Sprint_Footstep_WaterSplash_A.NS_Sprint_Footstep_WaterSplash_A'
local bounds = {
    minimum={1,10000}, medium={1,10000}, hard={1,10000}, exit={1,10000},
    inner={0,30000}, range={1,30000}, cooldown={.05,2}, life={.2,3},
    pitch_jitter={0,.25}, volume_jitter={0,.25},
}
local tiers = {easy=true,medium=true,hard=true,exit=true}

local function finite(n)
    return type(n)=='number' and n>-math.huge and n<math.huge
end

local function asset_path(path)
    assert(type(path)=='string' and #path<=240 and path:match('^/Game/Community/[%w_/]+%.[%w_]+$'),
           'liquid_asset_path_invalid')
    return path
end

local function merge_profile(base, patch)
    assert(type(patch)=='table','liquid_profile_table_required')
    local result={}
    for key,value in pairs(base) do result[key]=value end
    for key,value in pairs(patch) do
        local range=bounds[key]
        if range then
            assert(finite(value) and value>=range[1] and value<=range[2],'liquid_profile_number_invalid:'..key)
            result[key]=value
        elseif key=='sounds' or key=='gain' then
            assert(type(value)=='table','liquid_profile_tiers_required')
            local parts={}
            for tier,entry in pairs(result[key]) do parts[tier]=entry end
            for tier,entry in pairs(value) do
                assert(tiers[tier],'liquid_profile_tier_unknown')
                if key=='sounds' then
                    parts[tier]=asset_path(entry)
                else
                    assert(finite(entry) and entry>=0 and entry<=1,'liquid_profile_gain_invalid')
                    parts[tier]=entry
                end
            end
            result[key]=parts
        elseif key=='attenuation' or key=='concurrency' then
            result[key]=asset_path(value)
        else
            error('liquid_profile_field_unknown:'..tostring(key))
        end
    end
    assert(result.minimum<=result.medium and result.medium<=result.hard and result.inner<result.range,
           'liquid_profile_threshold_order')
    return result
end

local function named(value)
    return type(value)=='string' and #value<=64 and value:match('^[%w_]+$')
end

local function count_list(values,limit)
    assert(type(values)=='table','liquid_list_required')
    local count=0
    for i in pairs(values) do
        assert(type(i)=='number' and i%1==0 and i>=1 and i<=limit,'liquid_list_out_of_bounds')
        count=count+1
    end
    for n=1,count do assert(values[n]~=nil,'liquid_list_not_contiguous') end
    return count
end

local function liquid_profiles(packs, report)
    local profiles={stagnant_water=defaults,river_water=defaults}
    if packs==nil then return profiles end
    local ok,count=pcall(count_list,packs,8)
    if not ok then report('LIQUID_PROFILE_SKIPPED|'..tostring(count));return profiles end
    for i=1,count do
        local pack=packs[i]
        local loaded,problem=pcall(function()
            assert(type(pack)=='table' and pack.format==1 and type(pack.profiles)=='table','liquid_profile_pack_invalid')
            local pending={}
            local entries=0
            for name,value in pairs(pack.profiles) do
                entries=entries+1
                assert(entries<=16 and named(name),'liquid_profile_pack_entry_invalid')
                pending[name]=merge_profile(profiles[name] or defaults,value)
            end
            for name,value in pairs(pending) do profiles[name]=value end
        end)
        if not loaded then report('LIQUID_PROFILE_SKIPPED|pack='..i..'|'..tostring(problem)) end
    end
    return profiles
end

local function authored_surface(item,profiles)
    assert(type(item)=='table' and named(item.id) and named(item.splash_pool_tag),'liquid_identity_invalid')
    local profile=assert(profiles[item.liquid_type],'liquid_type_unknown')
    local lo,hi,z=item.box_min_cm,item.box_max_cm,item.surface_z_cm
    assert(count_list(lo,3)==3 and count_list(hi,3)==3 and finite(z),'liquid_bounds_invalid')
    for i=1,3 do assert(finite(lo[i]) and finite(hi[i]) and lo[i]<hi[i],'liquid_box_invalid') end
    assert(z>=lo[3] and z<=hi[3],'liquid_surface_outside_box')
    local tint
    if item.tint~=nil then
        assert(count_list(item.tint,3)==3,'liquid_tint_invalid')
        for _,v in ipairs(item.tint) do assert(finite(v) and v>=0 and v<=1,'liquid_tint_out_of_range') end
        tint={X=item.tint[1],Y=item.tint[2],Z=item.tint[3]}
    end
    -- The first Quagmire cook carries map-local wave assets until the shared
    -- profile pack supplies its own paths. Map overrides always apply last.
    if type(item.proposed_global_assets)=='table' and item.proposed_global_assets.sounds~=nil then
        profile=merge_profile(merge_profile(defaults,{sounds=item.proposed_global_assets.sounds}),profile)
    end
    if item.overrides~=nil then profile=merge_profile(profile,item.overrides) end
    local water=item.liquid_type=='stagnant_water' or item.liquid_type=='river_water'
    return {id=item.id,tag=item.splash_pool_tag,xmin=lo[1],xmax=hi[1],ymin=lo[2],ymax=hi[2],z=z,water=water,
            profile=profile,tint=tint}
end

local function discover_authored(descriptor,world,valid,report)
    local profiles=liquid_profiles(descriptor.liquid_profile_packs,report)
    local count=count_list(descriptor.liquids,32)
    local surfaces,allSlots,pools,ids={},{},{},{}
    for i=1,count do
        local ok,row=pcall(authored_surface,descriptor.liquids[i],profiles)
        if ok and not ids[row.id] then
            ids[row.id]=true
            pools[row.tag]=pools[row.tag] or {next=0,slots={}}
            row.pool=pools[row.tag]
            surfaces[#surfaces+1]=row
        else
            report('LIQUID_ENTRY_SKIPPED|index='..i..'|'..(ok and 'duplicate id' or tostring(row)))
        end
    end
    if #surfaces==0 then return end
    for _,actor in ipairs(FindAllOf('StaticMeshActor') or {}) do
        if valid(actor) and not actor.bReplicates and actor:GetWorld():GetAddress()==world:GetAddress() then
            local mesh=actor.StaticMeshComponent
            if valid(mesh) and mesh:GetCollisionEnabled()==0 then
                local owned=false
                actor.Tags:ForEach(function(_,tag)
                    local pool=pools[tag:get():ToString()]
                    if not owned and pool and #pool.slots<64 then
                        local slot={actor=actor}
                        pool.slots[#pool.slots+1]=slot
                        allSlots[#allSlots+1]=slot
                        owned=true
                    end
                end)
            end
        end
    end
    for tag,pool in pairs(pools) do
        if #pool.slots==0 then report('LIQUID_POOL_UNAVAILABLE|tag='..tag) end
    end
    return surfaces,allSlots
end

local function splash_tier(profile,speed,direction)
    if direction=='exit' then return 'exit' end
    if speed>=profile.hard then return 'hard' end
    if speed>=profile.medium then return 'medium' end
    return 'easy'
end

local function asset_loader(valid,report)
    local unavailable={}
    return function(path, expected)
        if not path then return end
        local key=expected..'|'..path
        if unavailable[key] then return end
        local class=StaticFindObject(expected)
        if not valid(class) then return end
        local asset=StaticFindObject(path)
        if not valid(asset) then
            local ok,loaded=pcall(LoadAsset,path)
            asset=ok and loaded or nil
        end
        if valid(asset) and asset:IsA(class) then return asset end
        unavailable[key]=true
        report('LIQUID_ASSET_UNAVAILABLE|'..path)
    end
end

local function spatial_audio(valid,report,load)
    return function(gameplay,context,pc,profile,tier,location,rotation,fallback_sound)
        local camera=valid(pc) and pc.PlayerCameraManager
        if not valid(camera) then return end
        local listener=camera:GetCameraLocation()
        local dx,dy,dz=listener.X-location.X,listener.Y-location.Y,listener.Z-location.Z
        local distance=math.sqrt(dx*dx+dy*dy+dz*dz)
        if distance>=profile.range then return end
        local sound=load(profile.sounds[tier],'/Script/Engine.SoundBase')
            or load(fallback_sound,'/Script/Engine.SoundBase')
        if not sound then return end
        local attenuation=load(profile.attenuation,'/Script/Engine.SoundAttenuation')
        local concurrency=load(profile.concurrency,'/Script/Engine.SoundConcurrency')
        local range_gain=attenuation and 1 or math.min(1,(profile.range-distance)/(profile.range-profile.inner))
        local volume=profile.gain[tier]*range_gain*(1+profile.volume_jitter*(2*math.random()-1))
        local pitch=1+profile.pitch_jitter*(2*math.random()-1)
        local ok,component=pcall(gameplay.SpawnSoundAtLocation,gameplay,context,sound,location,rotation,
                                 volume,pitch,0,attenuation,concurrency,true)
        if not ok then report('LIQUID_AUDIO_ERROR|'..tostring(component)) end
        return ok and valid(component)
    end
end

local function play_stock_splash(valid,report,load,context,location,rotation,size)
    local fx=load(stock_splash,'/Script/Niagara.NiagaraSystem')
    local niagara=StaticFindObject('/Script/Niagara.Default__NiagaraFunctionLibrary')
    if fx and valid(niagara) then
        local ok,component=pcall(function()
            return niagara:SpawnSystemAtLocation(context,fx,location,rotation,
                {X=size,Y=size,Z=size},true,true,0,true)
        end)
        if not ok then report('WATER_SPLASH_FX_ERROR|'..tostring(component)) end
        return ok and valid(component)
    end
end

local function factory(env)
    local valid, report = env.valid, env.report
    local current_world
    local load=asset_loader(valid,report)
    local play_audio=spatial_audio(valid,report,load)
    return function(game_state,pc)
        local name=game_state:GetFullName()
        local descriptor
        for _,row in pairs(env.descriptors or {}) do
            if row.liquids~=nil and type(row.world)=='string' and name:find(row.world,1,true) then
                descriptor=row
                break
            end
        end
        if not descriptor and not name:find('/Game/Maps/Community/',1,true) then return end
        local world = game_state:GetWorld()
        local world_address = world:GetAddress()
        if current_world == world_address then return end
        current_world = world_address
        local error_prefix=descriptor and 'LIQUID_ERROR|' or 'WATER_SPLASH_ERROR|'

        local ok, problem = pcall(function()
            local surfaces,slots
            if descriptor then surfaces,slots=discover_authored(descriptor,world,valid,report)
            elseif name:find('/Arena_Damnation_2026_P.',1,true) then surfaces,slots=discover(world,valid) end
            local stock=not surfaces
            if stock then surfaces,slots=discover_water(world,valid) end
            if not surfaces then return end
            local gameplay = StaticFindObject('/Script/Engine.Default__GameplayStatics')
            local materials = StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary')
            local character_class = StaticFindObject('/Script/Valhalla.ValCharacter')
            local age_parameter = FName('SplashAge')
            local empty_name = FName('None')
            local rotation = {Pitch=0, Yaw=0, Roll=0}
            local previous, next_slot, last = {}, 0, nil
            assert(valid(gameplay) and valid(character_class) and (#slots==0 or valid(materials)))

            local event_count=0
            local function splash(surface,x,y,z,speed,now,direction)
                local profile=surface.profile or stock_water
                local tier=splash_tier(profile,speed,direction)
                local fallback_sound=surface.water and stock_water.sounds[tier] or nil
                local sound_spawned=play_audio(gameplay,game_state,pc,profile,tier,{X=x,Y=y,Z=z},rotation,fallback_sound)
                local size=math.min(1.55,0.66+speed/4600)
                if stock or surface.water and #surface.pool.slots==0 then
                    local fx_spawned=play_stock_splash(valid,report,load,game_state,{X=x,Y=y,Z=z+6},rotation,size)
                    event_count=event_count+1
                    if event_count<=64 then
                        report('WATER_SPLASH|tier='..tier..'|fx='..tostring(fx_spawned==true)
                               ..'|audio='..tostring(sound_spawned==true))
                    end
                    return
                end
                local slot
                if surface.profile then
                    event_count=event_count+1
                    if event_count<=64 then
                        report('LIQUID_SPLASH|id='..surface.id..'|tier='..tier..'|speed_cm_s='..math.floor(speed))
                    end
                    local pool=surface.pool
                    if #pool.slots==0 then return end
                    pool.next=pool.next % #pool.slots + 1
                    slot=pool.slots[pool.next]
                else
                    next_slot=next_slot % #slots + 1
                    slot=slots[next_slot]
                end
                local actor = slot.actor
                if not slot.material then
                    local mesh = actor.StaticMeshComponent
                    slot.material = materials:CreateDynamicMaterialInstance(actor, mesh:GetMaterial(0), empty_name, 0)
                    assert(valid(slot.material), 'liquid splash material failed to initialize')
                    mesh:SetMaterial(0, slot.material)
                end
                slot.time,slot.life = now,profile.life or SPLASH_SECONDS
                if surface.tint then slot.material:SetVectorParameterValue(FName('SplashColor'),surface.tint) end
                actor:SetActorScale3D({X=size, Y=size, Z=size})
                actor:K2_TeleportTo({X=x, Y=y, Z=z+23}, rotation)
                slot.material:SetScalarParameterValue(age_parameter, 0.07)
                actor:SetActorHiddenInGame(false)
            end

            local function update()
                local now = gameplay:GetTimeSeconds(game_state)
                local dt = last and now-last or 0
                last = now
                for _, slot in ipairs(slots) do
                    if slot.time then
                        local age = (now-slot.time)/slot.life
                        if age >= 1 then
                            slot.actor:SetActorHiddenInGame(true)
                            slot.time = nil
                        else
                            slot.material:SetScalarParameterValue(age_parameter, math.max(.07, age))
                        end
                    end
                end

                local observed = {}
                game_state.PlayerArray:ForEach(function(_, item)
                    local player = item:get()
                    if valid(player) and player:GetWorld():GetAddress() == world_address then
                        local pawn = player:GetPawn()
                        if valid(pawn) and pawn:IsA(character_class) and pawn.bInitialized == true then
                            local key = pawn:GetAddress()
                            local p = pawn:K2_GetActorLocation()
                            local sample = {X=p.X, Y=p.Y, Z=p.Z-pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()}
                            observed[key] = sample
                            local old = previous[key]
                            if old and dt > 0 and dt < .23 and now >= (old.next_splash or 0) then
                                local dx, dy, dz = sample.X-old.X, sample.Y-old.Y, sample.Z-old.Z
                                if dx*dx + dy*dy + dz*dz <= (40000*dt+250)^2 then
                                    for _, surface in ipairs(surfaces) do
                                        local x, y, speed, direction = contact(old, sample, surface, dt)
                                        if x then
                                            local z = surface.z
                                            local hit = not surface.ski or valid(surface.ski) and surface.ski:K2_LineTraceComponent(
                                                {X=x,Y=y,Z=z+50}, {X=x,Y=y,Z=z-50}, true, false, false, {}, {}, {}, {})
                                            if hit then
                                                if surface.profile then
                                                    if not surface.failed then
                                                        local ok,why=pcall(splash,surface,x,y,z,speed,now,direction)
                                                        if not ok then
                                                            surface.failed=true
                                                            report('LIQUID_ENTRY_SKIPPED|id='..surface.id..'|'..tostring(why))
                                                        end
                                                    end
                                                else splash(surface,x,y,z,speed,now,direction) end
                                                sample.next_splash = now + (surface.profile and surface.profile.cooldown or .20)
                                                break
                                            end
                                        end
                                    end
                                end
                            elseif old then
                                sample.next_splash = old.next_splash
                            end
                        end
                    end
                end)
                previous = observed
            end

            local function tick()
                ExecuteInGameThreadWithDelay(INTERVAL_MS, function()
                    if not valid(game_state) or not valid(world) or current_world ~= world_address then return end
                    local success, reason = pcall(update)
                    if success then tick() else report(error_prefix..tostring(reason)) end
                end)
            end
            report((stock and 'WATER_SPLASH_READY' or descriptor and 'LIQUID_READY|map='..descriptor.name or 'DAMNATION_WATER_READY')
                   ..'|surfaces='..#surfaces..'|splash_pool='..#slots)
            tick()
        end)
        if not ok then report(error_prefix..tostring(problem)) end
    end
end

return factory, contact, authored_surface, liquid_profiles, splash_tier
