return function(env)
    local path, scope, valid, report = env.path, env.scope, env.valid, env.report
    local jet_class = 'BlueprintGeneratedClass /Game/Abilities/Devices/Jet_Pack/GA_Jetpack.GA_Jetpack_C'
    local owner, jet_input, clock, last_sample, segment = nil, nil, nil, nil, 0
    local started, stopped = false, false
    local rows = {}

    local function flush()
        local file = assert(io.open(path, 'a'))
        local ok, why = file:write(table.concat(rows, '\n'), '\n')
        local closed, close_error = file:close()
        assert(ok, why)
        assert(closed, close_error)
        rows = {}
    end

    local function sample(pc, gs)
        local pawn = pc.Pawn
        local ps = pc.PlayerState
        if not valid(pawn) or not valid(ps) or not pawn.bInitialized or pawn:GetHealth() <= 0 then
            owner = nil
            return
        end
        local team = ps.r_TeamId
        if env.team and team ~= env.team then
            owner = nil
            return
        end
        local asc, movement = pawn.AbilitySystemComponent, pawn.CharacterMovement
        if not valid(asc) or not valid(movement) then return end
        local key = tostring(pawn:GetAddress()) .. '|' .. pawn:GetFullName()
        if key ~= owner then
            jet_input = nil
            asc.ActivatableAbilities.Items:ForEach(function(_, element)
                local spec = element:get()
                if valid(spec.Ability) and spec.Ability:GetClass():GetFullName() == jet_class then
                    jet_input = spec.InputID
                end
            end)
            if type(jet_input) ~= 'number' or jet_input < 0 then return end
            owner, last_sample, segment = key, nil, segment + 1
        end
        local now = clock:GetTimeSeconds(gs)
        if last_sample and now <= last_sample then return end
        last_sample = now
        local jet_pressed = false
        asc.ActivatableAbilities.Items:ForEach(function(_, element)
            local spec = element:get()
            if spec.InputID == jet_input and spec.InputPressed then jet_pressed = true end
        end)
        local p, v = pawn:K2_GetActorLocation(), movement.Velocity
        local direction, view = pawn:GetLastMovementInputVector(), pc:GetControlRotation()
        rows[#rows + 1] = string.format(
            '%d,%.4f,%d,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d,%.4f,%.4f,%d,%d',
            segment, now, team, p.X, p.Y, p.Z, v.X, v.Y, v.Z, view.Yaw, view.Pitch,
            pawn:GetEnergy(), movement:IsMovingOnGround() and 1 or 0, direction.X, direction.Y,
            movement.bWantsToSki and 1 or 0, jet_pressed and 1 or 0)
        if #rows >= 10 then
            flush()
            if not started then started = true; report('BOT_DEMO_RECORDING') end
        end
    end

    local function schedule(pc, gs)
        ExecuteInGameThreadWithDelay(50, function()
            if stopped then return end
            local ok, why = pcall(function()
                scope()
                if not valid(pc) or not valid(gs) or not pc:IsLocalPlayerController() or pc:HasAuthority() then
                    if #rows > 0 then flush() end
                    stopped = true
                    return
                end
                sample(pc, gs)
                schedule(pc, gs)
            end)
            if not ok then
                stopped = true
                report('BOT_DEMO_ERROR|' .. tostring(why):sub(1, 350))
            end
        end)
    end

    return function(pc, gs)
        assert(gs:GetFullName():find(env.world, 1, true), 'training_map_mismatch')
        clock = StaticFindObject('/Script/Engine.Default__GameplayStatics')
        assert(valid(clock), 'training_game_clock_missing')
        schedule(pc, gs)
    end
end
