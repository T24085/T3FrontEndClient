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
    local function write_result(id, result)
        local base = env.path .. '/result-' .. id
        local file = assert(io.open(base .. '.tmp', 'w'))
        assert(file:write(table.concat(result, ','), '\n'))
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
        signature('/Script/Topaz.TopPickup_Flag:ForceReturnFlag',{{'ReturningCharacter','ObjectProperty',0}})
        brain:StopLogic('Local High Octane training')
        local trial, id, poll, jet_on, ski_on = nil, 1, 0, false, false
        local function release()
            if jet_on then events:SendGameplayEventToActor(pawn, stop_tag, {});jet_on = false end
            if ski_on then movement:SetWantsToSki(false);ski_on = false end
        end
        local function restore_flag()
            if same(enemy:GetOwner(), pawn) then enemy:Drop(false,false,false) end
            if not stands[2]:IsFlagAtHome() then enemy:ForceReturnFlag(nil) end
        end
        local function start_trial(line, now)
            local fields = {}
            for item in line:gmatch('[^,]+') do fields[#fields+1] = tonumber(item) end
            local spawn, offset, duration, pulse, period, ski, turn = table.unpack(fields)
            assert(#fields == 7 and starts[spawn] and math.abs(offset) <= 100 and duration >= 3 and duration <= 90
                and pulse >= 0 and pulse <= 1.25 and period >= 1.5 and period <= 6
                and (ski == 0 or ski == 1) and math.abs(turn) <= 20, 'training_invalid_trial')
            release()
            restore_flag()
            local p = starts[spawn]
            local dx, dy = enemy_position.X-p.X, enemy_position.Y-p.Y
            local length = math.sqrt(dx*dx+dy*dy)
            assert(length > 100, 'training_spawn_at_objective')
            local at = {X=p.X-dy*offset/length, Y=p.Y+dx*offset/length, Z=p.Z+30}
            local facing = {Pitch=0,Yaw=math.deg(math.atan(dy,dx)),Roll=0}
            movement:StopMovementImmediately()
            local placed = pawn:K2_TeleportTo(at, facing)
            if not placed then
                at.Z = at.Z + pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()
                placed = pawn:K2_TeleportTo(at, facing)
            end
            assert(placed, 'training_teleport_failed_spawn_'..spawn)
            controller:SetControlRotation(facing)
            movement:StopMovementImmediately()
            trial = {settle=now, at=at, duration=duration, pulse=pulse, period=period, ski=ski==1,
                turn=math.rad(turn), pickup=false, displacement=0, jet_frames=0, ski_frames=0}
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
                    assert(distance(at, trial.at) < 300, 'training_reset_position')
                    trial.started, trial.energy, trial.origin, trial.before = now, energy, vector(at), score(gs)
                    trial.initial = distance(at, enemy_position)
                    trial.closest = trial.initial
                    report(('BOT_TRAIN_RESET|%d|energy=%.1f'):format(id, energy))
                else
                    assert(now-trial.settle <= 12, 'training_reset_settle_timeout')
                    return
                end
            end
            local elapsed = now - trial.started
            local carrying = same(enemy:GetOwner(),pawn)
            trial.pickup = trial.pickup or carrying
            local captured = trial.pickup and score(gs) > trial.before
            trial.closest = math.min(trial.closest, distance(at, enemy_position))
            trial.displacement = math.max(trial.displacement, distance(at, trial.origin))
            if movement.bIsJetpackActive then trial.jet_frames = trial.jet_frames + 1 end
            if movement:IsSkiing() then trial.ski_frames = trial.ski_frames + 1 end
            if captured or elapsed >= trial.duration then
                release()
                movement:StopMovementImmediately()
                write_result(id, {id, captured and 1 or 0, trial.pickup and 1 or 0,
                    elapsed, trial.initial, trial.closest, trial.displacement,
                    trial.jet_frames, trial.ski_frames, trial.energy})
                report('BOT_TRAIN_TRIAL|' .. id)
                trial, id = nil, id + 1
                return
            end
            local target = carrying and home_position or enemy_position
            local dx, dy = target.X-at.X, target.Y-at.Y
            local heading = math.atan(dy,dx) + trial.turn
            local rising = trial.pulse > 0 and elapsed % trial.period < trial.pulse
            if rising and not jet_on and pawn:GetEnergy() >= 10 then
                jet_on = pawn.AbilitySystemComponent:TryActivateAbility(jet, false)
            elseif not rising and jet_on then
                events:SendGameplayEventToActor(pawn,stop_tag,{})
                jet_on = false
            end
            if ski_on ~= trial.ski then movement:SetWantsToSki(trial.ski);ski_on = trial.ski end
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
