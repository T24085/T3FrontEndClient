return function(env)
    local valid, scope, report = env.valid, env.scope, env.report
    local geometry = assert(loadfile(env.route_geometry))()
    local function same(a, b)
        return valid(a) and valid(b) and a:GetAddress() == b:GetAddress()
    end
    local function distance(a, b)
        return math.sqrt((a.X-b.X)^2 + (a.Y-b.Y)^2 + (a.Z-b.Z)^2)
    end
    local function vector(a)
        return {X=a.X, Y=a.Y, Z=a.Z}
    end
    local function score(gs, team)
        local result
        gs.r_CurrentTeamScores:ForEach(function(_, element)
            local row = element:get()
            if row.TeamNum == (team or 1) then result = row.Score end
        end)
        return assert(result, 'training_blue_score_missing')
    end
    local prefix = env.lane and ('lane-'..env.lane..'-') or ''
    local function write_csv(name, body)
        local base = env.path .. '/' .. prefix .. name
        local file = assert(io.open(base .. '.tmp', 'w'))
        assert(file:write(body, '\n'))
        assert(file:close())
        assert(os.rename(base .. '.tmp', base .. '.csv'))
    end
    local started = false
    return function(gm, gs, pawn, controller, defenders)
        if started then return end
        local team = env.team or 1
        local enemy_team = 3-team
        assert(gm:HasAuthority() and pawn:HasAuthority() and pawn.PlayerState.bIsABot
            and pawn.PlayerState.r_bPlayerBot and (team == 1 or team == 2) and pawn:GetTeamId() == team, 'training_bot_scope')
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
        local enemy, home = flags[enemy_team], stands[team]
        assert(valid(enemy) and valid(home) and valid(stands[enemy_team]), 'training_flags_missing')
        local enemy_position, home_position = vector(enemy:K2_GetActorLocation()), vector(home:K2_GetActorLocation())
        local enemy_stand_position = env.approach_reward and vector(stands[enemy_team]:K2_GetActorLocation())
        local home_dx, home_dy = home_position.X-enemy_position.X, home_position.Y-enemy_position.Y
        local home_range = math.sqrt(home_dx^2+home_dy^2)
        assert(home_range > 100, 'training_flag_axis_missing')
        local hx, hy = home_dx/home_range, home_dy/home_range
        local defense
        if defenders then
            defense = assert(loadfile(env.defense_script))()(env, stands[enemy_team], defenders, hx, hy)
        end
        local reuse = env.verify_reuse and assert(loadfile(env.reuse_script))()(env, world, pawn, defenders)
        local starts = {}
        for _, start in ipairs(FindAllOf('TopPlayerStart') or {}) do
            if same(start:GetWorld(), world) and start.TeamNumber == team then
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
        local initial_blue, initial_red
        local screening = env.lane ~= nil
        local no_braking = env.no_braking == true
        local finished = false
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
            local profile = fields[10]
            local pass = fields[11]
            local guidance = fields[12]
            assert((#fields == 9 or (#fields >= 10 and #fields <= 12 and (screening or no_braking or defense and defense.configure)))
                and starts[spawn] and math.abs(offset) <= (screening and 240 or 100) and duration >= 3 and duration <= 90
                and pulse >= 0 and pulse <= 1.25 and period >= 1.5 and period <= 6
                and (ski == 0 or ski == 1) and math.abs(turn) <= 20
                and approach >= 2000 and approach <= 6000
                and flank%1 == 0 and math.abs(flank) <= 2, 'training_invalid_trial')
            assert(not pass or pass==0 or (pass>=3000 and pass<=(env.long_runups and 12500 or 9000) and flank~=0), 'training_invalid_flag_pass')
            assert(not guidance or (pass and pass>0 and guidance%1==0 and guidance>=1
                and guidance<=(env.speed_sweep and 6 or 2)), 'training_invalid_pass_guidance')
            if reuse and id > 1 then
                assert(score(gs) == initial_blue and score(gs,2) == initial_red,
                    'training_reuse_unverified|match_score_changed')
                assert(not defense or defense.quiesce(), 'training_reuse_unverified|defender_combat')
            end
            if env.adaptive_defense then
                assert(profile and profile > 0 and profile%1==0 and defense and defense.configure,
                    'invalid_adaptive_defense_profile')
                defense.configure(profile)
            elseif screening or no_braking then assert(profile==0, 'unexpected_training_defense_profile')
            elseif profile then defense.configure(profile) end
            release()
            if env.reset_contact then env.reset_contact() end
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
            local waypoints = geometry.waypoints(enemy_position,hx,hy,flank,pass)
            trial = {settle=now, at=at, facing=facing, spawn=spawn, retries=0,
                duration=duration, pulse=pulse, period=period, ski=ski==1,
                turn=math.rad(turn), approach=approach, displacement=0, jet_frames=0, ski_frames=0,
                distance_out=0, distance_return=0, seconds_out=0, seconds_return=0, peak_speed=0,
                waypoints=waypoints, waypoint=1, trace={}, next_sample=0, pass=pass,
                recovered=false, closest_pass=math.huge, guidance=guidance}
        end
        local function sample_trace(elapsed, p, v, carrying, phase, dead)
            trial.trace[#trial.trace+1] = ('%.3f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.2f,%d,%d,%d,%s'):format(
                elapsed,p.X,p.Y,p.Z,v.X,v.Y,v.Z,dead and 0 or pawn:GetEnergy(),
                not dead and movement:IsSkiing() and 1 or 0,not dead and movement.bIsJetpackActive and 1 or 0,carrying and 1 or 0,phase)
        end
        local function frame()
            scope()
            if screening and finished then return end
            local now = clock:GetTimeSeconds(gm)
            local alive = same(controller.Pawn,pawn) and same(pawn:GetWorld(),world) and pawn:GetHealth()>0
            if not alive and not ((defense or screening) and trial and trial.started) then
                error(reuse and id > 1 and 'training_reuse_unverified|capper_changed' or 'training_pawn_changed')
            end
            if not trial then
                if now < poll then return end
                poll = now + .1
                local file = io.open(env.path .. '/' .. prefix .. 'trial-' .. id .. '.csv', 'r')
                if not file then return end
                local line = file:read('*l')
                file:close()
                start_trial(line, now)
                return
            end
            local at = alive and pawn:K2_GetActorLocation() or trial.last_at
            if not trial.started then
                local speed = movement.Velocity
                local energy = pawn:GetEnergy()
                local warm = reuse and id > 1
                local both_flags_home = not warm or (stands[1]:IsFlagAtHome() and stands[2]:IsFlagAtHome())
                if warm and now-trial.settle > 8 then
                    error('training_reuse_unverified|'..(trial.reset_reason or 'flags_or_ground'))
                end
                if both_flags_home and movement:IsMovingOnGround() and math.sqrt(speed.X^2+speed.Y^2+speed.Z^2) <= 30
                    and energy >= 98 and stands[2]:IsFlagAtHome()
                    and (not defense or defense.ready(pawn, now)) then
                    if distance(at, trial.at) >= 300 then
                        assert(trial.retries < 2, warm and 'training_reuse_unverified|capper_position'
                            or 'training_reset_position_spawn_'..trial.spawn)
                        trial.retries = trial.retries + 1
                        place(trial.at, trial.facing, trial.spawn)
                        report('BOT_TRAIN_RESET_RETRY|'..id)
                        return
                    end
                    if reuse then
                        if not warm then initial_blue, initial_red = score(gs), score(gs,2) end
                        local inspected, clean, reason = pcall(reuse, warm)
                        if not inspected then
                            reason = 'state_unavailable'
                            if not warm then env.report('BOT_TRAIN_REUSE_UNAVAILABLE|'..tostring(clean)) end
                            clean = false
                        end
                        if not warm and reason == 'pawn_resources_or_input' and now-trial.settle < 3 then
                            return
                        end
                        if warm and not clean then
                            trial.reset_reason = reason
                            return
                        end
                        if warm then write_csv('verified-reset-'..id, '1') end
                    end
                    trial.started, trial.energy, trial.origin, trial.before = now, energy, vector(at), score(gs,team)
                    trial.initial = distance(at, enemy_position)
                    trial.closest = trial.initial
                    if defense then
                        defense.reset(pawn, now, score(gs,2))
                    end
                    report(('BOT_TRAIN_RESET|%d|energy=%.1f'):format(id, energy))
                else
                    if warm then return end
                    local flag_home = stands[2]:IsFlagAtHome()
                    assert(now-trial.settle <= (flag_home and 90 or 85), 'training_reset_settle_timeout')
                    return
                end
            end
            local elapsed = now - trial.started
            local contact, overlap
            if screening then contact, overlap = env.contact(trial.on_flythrough) end
            if screening then assert(not valid(enemy:GetOwner()), 'screen_flag_was_picked_up') end
            local carrying = alive and same(enemy:GetOwner(),pawn)
            local velocity = alive and movement.Velocity or trial.last_velocity
            local speed = math.sqrt(velocity.X^2+velocity.Y^2)
            if enemy_stand_position and alive and not contact and not carrying and not trial.pickup then
                geometry.sample_approach(trial,geometry.stand_distance(at,enemy_stand_position),.036*speed)
            end
            if alive then
                trial.last_at, trial.last_velocity = vector(at), vector(velocity)
            end
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
                if enemy_stand_position and trial.approach_entry and not trial.recovered
                    and geometry.stand_distance(at,enemy_stand_position)<=800 then
                    trial.pickup_entry,trial.pickup_peak=trial.approach_entry,trial.approach_peak
                end
                trial.grab_energy = pawn:GetEnergy()
                trial.skiing_flythrough_grab = trial.on_flythrough and movement:IsSkiing()
                sample_trace(elapsed,at,velocity,carrying,trial.recovered and 'recovery_grab' or 'grab')
                report(('BOT_TRAIN_PICKUP|%d|seconds=%.2f'):format(id, elapsed))
            end
            local captured = trial.pickup and score(gs,team) > trial.before
            if trial.was_carrying and not carrying and not captured and alive then
                sample_trace(elapsed,at,velocity,false,'flag_lost')
            end
            trial.was_carrying = carrying
            if defense and alive then defense.tick(pawn, carrying, now) end
            if carrying then
                local remaining = distance(at, home_position)
                trial.home_closest = math.min(trial.home_closest or remaining, remaining)
            end
            local to_flag=distance(at,enemy_position)
            trial.closest = math.min(trial.closest,to_flag)
            if trial.pass and (not trial.pickup or elapsed==trial.pickup) and not trial.recovered
                and to_flag<trial.closest_pass then
                trial.closest_pass,trial.closest_speed=to_flag,.036*speed
            end
            trial.displacement = math.max(trial.displacement, distance(at, trial.origin))
            if alive and movement.bIsJetpackActive then trial.jet_frames = trial.jet_frames + 1 end
            if alive and movement:IsSkiing() then trial.ski_frames = trial.ski_frames + 1 end
            if captured or contact or ((screening or no_braking) and trial.recovered) or not alive or elapsed >= trial.duration then
                if alive then
                    if overlap then
                        sample_trace(overlap.time-trial.started, {X=overlap.x,Y=overlap.y,Z=overlap.z},
                            {X=contact[2]/.036,Y=contact[3]/.036,Z=contact[4]/.036}, false, 'screen_overlap')
                    else
                        sample_trace(elapsed,at,velocity,carrying,contact and 'screen_contact' or captured and 'cap'
                            or no_braking and trial.recovered and 'missed_pass' or 'timeout')
                    end
                    release()
                    movement:StopMovementImmediately()
                elseif at then
                    local death = same(controller.Pawn,pawn) and same(pawn:GetWorld(),world)
                    sample_trace(elapsed,death and pawn:K2_GetActorLocation() or at,
                        velocity,false,death and 'death' or 'death_last_seen',true)
                end
                write_csv('trace-'..id, 'seconds,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,vz_cm_s,energy,ski,jet,carrying,phase\n'
                    ..table.concat(trial.trace,'\n'))
                if defense then write_csv('defense-'..id, defense.finish(pawn, not alive, score(gs,2))) end
                if trial.pass then
                    local pass_data = {trial.recovered and 1 or 0,trial.closest_pass,trial.closest_speed}
                    if env.long_runups then
                        pass_data[4] = trial.skiing_flythrough_grab and 1 or 0
                    end
                    if env.speed_sweep then
                        pass_data[5] = trial.best_pass and 1 or 0
                        if trial.best_pass then
                            for _, value in ipairs(trial.best_pass) do pass_data[#pass_data+1] = value end
                        end
                    end
                    write_csv('pass-'..id, table.concat(pass_data,','))
                end
                if screening then
                    if contact and overlap and trial.approach_entry and
                        geometry.stand_distance({X=overlap.x,Y=overlap.y},enemy_stand_position)<=800 then
                        contact[6],contact[7]=trial.approach_entry,trial.approach_peak
                    end
                    write_csv('contact-'..id, contact and table.concat(contact, ',') or '0')
                end
                if enemy_stand_position and not screening then
                    write_csv('approach-'..id, trial.pickup_entry and
                        table.concat({trial.pickup_entry,trial.pickup_peak},',') or '0')
                end
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
                finished = screening and not env.screen_reuse
                return
            end
            local waypoint = not trial.pickup and trial.waypoints[trial.waypoint]
            local final_entry = trial.pass and trial.pass>0 and trial.waypoint==#trial.waypoints
            local entry_radius = final_entry and 1150 or 1800
            if waypoint and (waypoint.X-at.X)^2+(waypoint.Y-at.Y)^2 < entry_radius^2 then
                trial.waypoint = trial.waypoint + 1
                waypoint = trial.waypoints[trial.waypoint]
            end
            local along=(at.X-enemy_position.X)*hx+(at.Y-enemy_position.Y)*hy
            local flythrough=trial.pass and trial.pass>0 and not trial.recovered and not trial.pickup and not waypoint
            if flythrough and along>750 then
                trial.recovered=true
                flythrough=false
                report('BOT_TRAIN_FLAG_PASS_MISSED|'..id)
            end
            trial.on_flythrough = flythrough
            if env.speed_sweep and flythrough and (not trial.best_pass or to_flag<trial.best_pass[1]) then
                local cross=-(at.X-enemy_position.X)*hy+(at.Y-enemy_position.Y)*hx
                trial.best_pass={to_flag,.036*speed,.036*(velocity.X*hx+velocity.Y*hy),
                    cross,at.Z-enemy_position.Z}
            end
            if elapsed >= trial.next_sample then
                sample_trace(elapsed,at,velocity,carrying,waypoint and ('waypoint'..trial.waypoint)
                    or (carrying and 'return' or flythrough and 'flythrough' or trial.recovered and 'recovery' or 'approach'))
                trial.next_sample = elapsed + .2
            end
            local target = carrying and home_position or waypoint or vector(enemy:K2_GetActorLocation())
            local dx, dy = target.X-at.X, target.Y-at.Y
            local range = math.sqrt(dx*dx+dy*dy)
            local closing = (dx*velocity.X+dy*velocity.Y)/math.max(range,1)
            local precision = not no_braking and not flythrough and not waypoint and range < trial.approach
            local turning = not no_braking and carrying and closing < -550
            local heading = math.atan(dy,dx) + (precision and 0 or trial.turn)
            if flythrough then
                -- Steer across the desired line without commanding a lower forward speed.
                local cross=-(at.X-enemy_position.X)*hy+(at.Y-enemy_position.Y)*hx
                local cross_speed=-velocity.X*hy+velocity.Y*hx
                local correction=math.atan(-cross-.35*cross_speed,math.max(650,-along))
                heading=math.atan(hy,hx)+math.max(-.55,math.min(.55,correction))
            elseif precision then
                local desired = math.min(900, range * 2.5)
                local correction_x = math.cos(heading)*desired-velocity.X
                local correction_y = math.sin(heading)*desired-velocity.Y
                if correction_x^2+correction_y^2 > 1 then heading = math.atan(correction_y,correction_x) end
            end
            local climbing = target.Z-at.Z > 160 and range < 2100
            if flythrough and trial.guidance then
                heading,climbing = geometry.flythrough(enemy_position,at,velocity,hx,hy,trial.guidance)
            end
            if no_braking then heading = geometry.limit_turn(heading,velocity) end
            local rising = trial.pulse > 0 and not turning
                and ((flythrough and climbing and (trial.guidance or not movement:IsMovingOnGround()))
                    or (not flythrough and (not precision or climbing) and elapsed % trial.period < trial.pulse))
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
                if not finished then ExecuteInGameThreadAfterFrames(1,tick) end
            else
                pcall(release)
                report('BOT_TRAIN_ERROR|'..tostring(why):sub(1,400))
            end
        end
        report((screening and ('BOT_SCREEN_READY|'..env.lane..'|') or 'BOT_TRAIN_READY|') .. #starts)
        ExecuteInGameThreadAfterFrames(1,tick)
    end
end
