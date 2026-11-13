return function(env)
    local valid, scope, report = env.valid, env.scope, env.report
    local function same(a, b)
        return valid(a) and valid(b) and a:GetAddress() == b:GetAddress()
    end
    local function distance(a, b)
        return math.sqrt((a.X-b.X)^2 + (a.Y-b.Y)^2 + (a.Z-b.Z)^2)
    end
    local function vector(a)
        return {X=a.X, Y=a.Y, Z=a.Z}
    end
    local function score(gs)
        local result
        gs.r_CurrentTeamScores:ForEach(function(_, element)
            local row = element:get()
            if row.TeamNum == 1 then result = row.Score end
        end)
        return assert(result, 'training_blue_score_missing')
    end
    local function write_csv(name, body)
        local base = env.path .. '/' .. name
        local file = assert(io.open(base .. '.tmp', 'w'))
        assert(file:write(body, '\n'))
        assert(file:close())
        assert(os.rename(base .. '.tmp', base .. '.csv'))
    end
    local started = false
    return function(gm, gs, pawn, controller)
        if started then return end
        assert(gm:HasAuthority() and pawn:HasAuthority() and pawn.PlayerState.bIsABot
            and pawn.PlayerState.r_bPlayerBot and pawn:GetTeamId() == 1, 'training_bot_scope')
        started = true
        local world = gm:GetWorld()
        local clock = StaticFindObject('/Script/Engine.Default__GameplayStatics')
        local events = StaticFindObject('/Script/GameplayAbilities.Default__AbilitySystemBlueprintLibrary')
        assert(valid(clock) and valid(events) and EngineTickAvailable, 'training_engine_services')
        local movement = pawn.CharacterMovement
        local brain = controller:GetStateTreeComponent()
        local slot = {TagName=FName('EquipSlot.Jetpack')}
        local jet = pawn:GetEquippedAbility(slot, false)
        assert(jet.Handle >= 0 and valid(brain) and brain:IsRunning(), 'training_bot_ready')
        local stop_tag = {TagName=FName('State.Jetpacking.StopAI')}
        local flags, stands = {}, {}
        for _, flag in ipairs(FindAllOf('TopPickup_Flag') or {}) do
            if same(flag:GetWorld(), world) then flags[flag.r_TeamId] = flag end
        end
        for _, stand in ipairs(FindAllOf('TopFlagStand') or {}) do
            if same(stand:GetWorld(), world) then stands[stand.TeamNum] = stand end
        end
        local enemy, home = flags[2], stands[1]
        assert(valid(enemy) and valid(home) and valid(stands[2]), 'training_flags_missing')
        local enemy_position, home_position = vector(enemy:K2_GetActorLocation()), vector(home:K2_GetActorLocation())
        local home_dx, home_dy = home_position.X-enemy_position.X, home_position.Y-enemy_position.Y
        local home_range = math.sqrt(home_dx^2+home_dy^2)
        assert(home_range > 100, 'training_flag_axis_missing')
        local hx, hy = home_dx/home_range, home_dy/home_range
        local function flag_relative(homeward, lateral)
            return {X=enemy_position.X+hx*homeward-hy*lateral,
                Y=enemy_position.Y+hy*homeward+hx*lateral,Z=enemy_position.Z}
        end
        local starts = {}
        for _, start in ipairs(FindAllOf('TopPlayerStart') or {}) do
            if same(start:GetWorld(), world) and start.TeamNumber == 1 then
                local location = vector(start:K2_GetActorLocation())
                starts[#starts+1] = location
            end
        end
        assert(#starts >= 2, 'training_spawn_choices_missing')
        table.sort(starts, function(a, b)
            if a.X ~= b.X then return a.X < b.X end
            if a.Y ~= b.Y then return a.Y < b.Y end
            return a.Z < b.Z
        end)
        local signature = env.signature
        signature('/Script/AIModule.BrainComponent:StopLogic', {{'Reason','StrProperty',0}})
        signature('/Script/Engine.Pawn:AddMovementInput',{
            {'WorldDirection','StructProperty',0},{'ScaleValue','FloatProperty',24},{'bForce','BoolProperty',28}})
        signature('/Script/Valhalla.ValCharacterMovementComponent:SetWantsToSki',{{'bEnabled','BoolProperty',0}})
        signature('/Script/Engine.Actor:K2_TeleportTo',{
            {'DestLocation','StructProperty',0},{'DestRotation','StructProperty',24},{'ReturnValue','BoolProperty',48}})
        signature('/Script/Engine.Controller:SetControlRotation',{{'NewRotation','StructProperty',0}})
        signature('/Script/GameplayAbilities.AbilitySystemComponent:TryActivateAbility',{
            {'AbilityToActivate','StructProperty',0},{'bAllowRemoteActivation','BoolProperty',4},{'ReturnValue','BoolProperty',5}})
        signature('/Script/GameplayAbilities.AbilitySystemBlueprintLibrary:SendGameplayEventToActor',{
            {'Actor','ObjectProperty',0},{'EventTag','StructProperty',8},{'Payload','StructProperty',16}})
        brain:StopLogic('Local High Octane training')
        local trial, id, poll, jet_on, ski_on = nil, 1, 0, false, false
        local function release()
            if jet_on then events:SendGameplayEventToActor(pawn, stop_tag, {});jet_on = false end
            if ski_on then movement:SetWantsToSki(false);ski_on = false end
        end
        local function place(at, facing, spawn)
            movement:StopMovementImmediately()
            if not pawn:K2_TeleportTo(at, facing) then
                local raised = {X=at.X,Y=at.Y,Z=at.Z+pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()}
                assert(pawn:K2_TeleportTo(raised, facing), 'training_teleport_failed_spawn_'..spawn)
            end
            controller:SetControlRotation(facing)
            movement:StopMovementImmediately()
        end
        local function start_trial(line, now)
            local fields = {}
            for item in line:gmatch('[^,]+') do fields[#fields+1] = tonumber(item) end
            local spawn, offset, duration, pulse, period, ski, turn, approach, flank = table.unpack(fields)
            assert(#fields == 9 and starts[spawn] and math.abs(offset) <= 100 and duration >= 3 and duration <= 90
                and pulse >= 0 and pulse <= 1.25 and period >= 1.5 and period <= 6
                and (ski == 0 or ski == 1) and math.abs(turn) <= 20
                and approach >= 2000 and approach <= 6000
                and flank%1 == 0 and math.abs(flank) <= 2, 'training_invalid_trial')
            release()
            if same(enemy:GetOwner(), pawn) then
                enemy:Drop(false,false,false)
                assert(not same(enemy:GetOwner(),pawn), 'training_flag_drop_failed')
            end
            local p = starts[spawn]
            local dx, dy = enemy_position.X-p.X, enemy_position.Y-p.Y
            local length = math.sqrt(dx*dx+dy*dy)
            assert(length > 100, 'training_spawn_at_objective')
            local at = {X=p.X-dy*offset/length, Y=p.Y+dx*offset/length, Z=p.Z+30}
            local facing = {Pitch=0,Yaw=math.deg(math.atan(dy,dx)),Roll=0}
            place(at, facing, spawn)
            local waypoints = {}
            if flank ~= 0 then
                local side = flank > 0 and 1 or -1
                waypoints[1] = flag_relative(-2500,side*5500)
                if math.abs(flank) == 2 then waypoints[2] = flag_relative(-5500,0) end
            end
            trial = {settle=now, at=at, facing=facing, spawn=spawn, retries=0,
                duration=duration, pulse=pulse, period=period, ski=ski==1,
                turn=math.rad(turn), approach=approach, displacement=0, jet_frames=0, ski_frames=0,
                distance_out=0, distance_return=0, seconds_out=0, seconds_return=0, peak_speed=0,
                waypoints=waypoints, waypoint=1, trace={}, next_sample=0}
        end
        local function sample_trace(elapsed, p, v, carrying, phase)
            trial.trace[#trial.trace+1] = ('%.3f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.2f,%d,%d,%d,%s'):format(
                elapsed,p.X,p.Y,p.Z,v.X,v.Y,v.Z,pawn:GetEnergy(),
                movement:IsSkiing() and 1 or 0,movement.bIsJetpackActive and 1 or 0,carrying and 1 or 0,phase)
        end
        local function frame()
            scope()
            assert(same(controller.Pawn,pawn) and same(pawn:GetWorld(),world) and pawn:GetHealth()>0,
                'training_pawn_changed')
            local now = clock:GetTimeSeconds(gm)
            if not trial then
                if now < poll then return end
                poll = now + .1
                local file = io.open(env.path .. '/trial-' .. id .. '.csv', 'r')
                if not file then return end
                local line = file:read('*l')
                file:close()
                start_trial(line, now)
                return
            end
            local at = pawn:K2_GetActorLocation()
            if not trial.started then
                local speed = movement.Velocity
                local energy = pawn:GetEnergy()
                if movement:IsMovingOnGround() and math.sqrt(speed.X^2+speed.Y^2+speed.Z^2) <= 30
                    and energy >= 98 and stands[2]:IsFlagAtHome() then
                    if distance(at, trial.at) >= 300 then
                        assert(trial.retries < 2, 'training_reset_position_spawn_'..trial.spawn)
                        trial.retries = trial.retries + 1
                        place(trial.at, trial.facing, trial.spawn)
                        report('BOT_TRAIN_RESET_RETRY|'..id)
                        return
                    end
                    trial.started, trial.energy, trial.origin, trial.before = now, energy, vector(at), score(gs)
                    trial.initial = distance(at, enemy_position)
                    trial.closest = trial.initial
                    report(('BOT_TRAIN_RESET|%d|energy=%.1f'):format(id, energy))
                else
                    local flag_home = stands[2]:IsFlagAtHome()
                    assert(now-trial.settle <= (flag_home and 90 or 85), 'training_reset_settle_timeout')
                    return
                end
            end
            local elapsed = now - trial.started
            local carrying = same(enemy:GetOwner(),pawn)
            local velocity = movement.Velocity
            local speed = math.sqrt(velocity.X^2+velocity.Y^2)
            trial.peak_speed = math.max(trial.peak_speed, speed)
            if trial.last_sample then
                local dt = now - trial.last_sample
                local distance = (trial.last_speed + speed) * .5 * dt
                if trial.last_carrying then
                    trial.distance_return = trial.distance_return + distance
                    trial.seconds_return = trial.seconds_return + dt
                else
                    trial.distance_out = trial.distance_out + distance
                    trial.seconds_out = trial.seconds_out + dt
                end
            end
            trial.last_sample, trial.last_speed, trial.last_carrying = now, speed, trial.last_carrying or carrying
            if carrying and not trial.pickup then
                trial.pickup = elapsed
                trial.grab_speed = .036 * speed
                trial.grab_homeward = .036 * (velocity.X*hx + velocity.Y*hy)
                trial.grab_energy = pawn:GetEnergy()
                sample_trace(elapsed,at,velocity,carrying,'grab')
                report(('BOT_TRAIN_PICKUP|%d|seconds=%.2f'):format(id, elapsed))
            end
            local captured = trial.pickup and score(gs) > trial.before
            if carrying then
                local remaining = distance(at, home_position)
                trial.home_closest = math.min(trial.home_closest or remaining, remaining)
            end
            trial.closest = math.min(trial.closest, distance(at, enemy_position))
            trial.displacement = math.max(trial.displacement, distance(at, trial.origin))
            if movement.bIsJetpackActive then trial.jet_frames = trial.jet_frames + 1 end
            if movement:IsSkiing() then trial.ski_frames = trial.ski_frames + 1 end
            if captured or elapsed >= trial.duration then
                release()
                movement:StopMovementImmediately()
                sample_trace(elapsed,at,velocity,carrying,captured and 'cap' or 'timeout')
                write_csv('trace-'..id, 'seconds,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,vz_cm_s,energy,ski,jet,carrying,phase\n'
                    ..table.concat(trial.trace,'\n'))
                write_csv('result-'..id, table.concat({id, captured and 1 or 0, trial.pickup and 1 or 0,
                    elapsed, trial.initial, trial.closest, trial.displacement,
                    trial.jet_frames, trial.ski_frames, trial.energy, trial.pickup or -1,
                    trial.home_closest or -1,
                    .036*(trial.distance_out+trial.distance_return)/math.max(elapsed,.001),
                    .036*trial.peak_speed,
                    trial.seconds_out > 0 and .036*trial.distance_out/trial.seconds_out or -1,
                    trial.seconds_return > 0 and .036*trial.distance_return/trial.seconds_return or -1,
                    trial.grab_speed or -1,trial.grab_homeward or 0,trial.grab_energy or -1},','))
                report('BOT_TRAIN_TRIAL|' .. id)
                trial, id = nil, id + 1
                return
            end
            local waypoint = not trial.pickup and trial.waypoints[trial.waypoint]
            if waypoint and (waypoint.X-at.X)^2+(waypoint.Y-at.Y)^2 < 1800^2 then
                trial.waypoint = trial.waypoint + 1
                waypoint = trial.waypoints[trial.waypoint]
            end
            if elapsed >= trial.next_sample then
                sample_trace(elapsed,at,velocity,carrying,waypoint and ('waypoint'..trial.waypoint)
                    or (carrying and 'return' or 'approach'))
                trial.next_sample = elapsed + .2
            end
            local target = carrying and home_position or waypoint or vector(enemy:K2_GetActorLocation())
            local dx, dy = target.X-at.X, target.Y-at.Y
            local range = math.sqrt(dx*dx+dy*dy)
            local closing = (dx*velocity.X+dy*velocity.Y)/math.max(range,1)
            local precision = not waypoint and range < trial.approach
            local turning = carrying and closing < -550
            local heading = math.atan(dy,dx) + (precision and 0 or trial.turn)
            if precision then
                local desired = math.min(900, range * 2.5)
                local correction_x = math.cos(heading)*desired-velocity.X
                local correction_y = math.sin(heading)*desired-velocity.Y
                if correction_x^2+correction_y^2 > 1 then heading = math.atan(correction_y,correction_x) end
            end
            local climbing = target.Z-at.Z > 160 and range < 2100
            local rising = trial.pulse > 0 and not turning and (not precision or climbing)
                and elapsed % trial.period < trial.pulse
            if rising and not jet_on and pawn:GetEnergy() >= 10 then
                jet_on = pawn.AbilitySystemComponent:TryActivateAbility(jet, false)
            elseif not rising and jet_on then
                events:SendGameplayEventToActor(pawn,stop_tag,{})
                jet_on = false
            end
            local wants_ski = trial.ski and not precision and not turning
            if ski_on ~= wants_ski then movement:SetWantsToSki(wants_ski);ski_on = wants_ski end
            pawn:AddMovementInput({X=math.cos(heading),Y=math.sin(heading),Z=0},1,true)
        end
        local function tick()
            local ok, why = pcall(frame)
            if ok then
                ExecuteInGameThreadAfterFrames(1,tick)
            else
                pcall(release)
                report('BOT_TRAIN_ERROR|'..tostring(why):sub(1,400))
            end
        end
        report('BOT_TRAIN_READY|' .. #starts)
        ExecuteInGameThreadAfterFrames(1,tick)
    end
end
