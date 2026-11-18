-- Client-local splash animations for the Damnation 2026 water overlay.
local INTERVAL_MS = 50
local SPLASH_SECONDS = 0.85
local MIN_SPEED = 350 -- cm/s

local function contact(previous, current, surface, dt)
    local before = previous.Z - surface.z
    local after = current.Z - surface.z
    local change = after - before
    if math.abs(change) < MIN_SPEED * dt then return end
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
    return x, y, math.abs(change) / dt
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
    assert(#surfaces == 77 and #slots == 12, 'Damnation water overlay is incomplete')
    return surfaces, slots
end

local function factory(env)
    local valid, report = env.valid, env.report
    local current_world
    return function(game_state)
        if not game_state:GetFullName():find('/Arena_Damnation_2026_P.', 1, true) then return end
        local world = game_state:GetWorld()
        local world_address = world:GetAddress()
        if current_world == world_address then return end
        current_world = world_address

        local ok, problem = pcall(function()
            local surfaces, slots = discover(world, valid)
            if not surfaces then return end
            local gameplay = StaticFindObject('/Script/Engine.Default__GameplayStatics')
            local materials = StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary')
            local character_class = StaticFindObject('/Script/Valhalla.ValCharacter')
            local age_parameter = FName('SplashAge')
            local empty_name = FName('None')
            local rotation = {Pitch=0, Yaw=0, Roll=0}
            local previous, next_slot, last = {}, 0, nil
            assert(valid(gameplay) and valid(materials) and valid(character_class))

            local function splash(x, y, z, speed, now)
                next_slot = next_slot % #slots + 1
                local slot = slots[next_slot]
                local actor = slot.actor
                if not slot.material then
                    local mesh = actor.StaticMeshComponent
                    slot.material = materials:CreateDynamicMaterialInstance(actor, mesh:GetMaterial(0), empty_name, 0)
                    assert(valid(slot.material), 'Damnation splash material failed to initialize')
                    mesh:SetMaterial(0, slot.material)
                end
                slot.time = now
                local size = math.min(1.55, 0.66 + speed / 4600)
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
                        local age = (now-slot.time)/SPLASH_SECONDS
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
                                        local x, y, speed = contact(old, sample, surface, dt)
                                        if x then
                                            local z = surface.z
                                            local hit = not surface.ski or surface.ski:K2_LineTraceComponent(
                                                {X=x,Y=y,Z=z+50}, {X=x,Y=y,Z=z-50}, true, false, false, {}, {}, {}, {})
                                            if hit then
                                                splash(x, y, z, speed, now)
                                                sample.next_splash = now + .20
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
                    if success then tick() else report('DAMNATION_WATER_ERROR|'..tostring(reason)) end
                end)
            end
            report('DAMNATION_WATER_READY|surfaces='..#surfaces..'|splash_pool='..#slots)
            tick()
        end)
        if not ok then report('DAMNATION_WATER_ERROR|'..tostring(problem)) end
    end
end

return factory, contact
