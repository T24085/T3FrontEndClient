-- Local movement practice, using a surveyed hill or the native spawn heading.
return function(env)
    local valid, signature = env.valid, env.signature
    return function(gm, gs, entries)
        env.scope()
        assert(gm:HasAuthority() and #entries == env.blue+env.red and EngineTickAvailable, 'flight_roster')
        local clock = StaticFindObject('/Script/Engine.Default__GameplayStatics')
        local events = StaticFindObject('/Script/GameplayAbilities.Default__AbilitySystemBlueprintLibrary')
        assert(valid(clock) and valid(events), 'flight_engine_services')
        local world = gm:GetWorld():GetAddress()
        local slot = {TagName=FName('EquipSlot.Jetpack')}
        local stop_tag = {TagName=FName('State.Jetpacking.StopAI')}
        signature('/Script/Engine.PrimitiveComponent:IgnoreActorWhenMoving',
            {{'Actor','ObjectProperty',0},{'bShouldIgnore','BoolProperty',8}})
        signature('/Script/Valhalla.ValPickup:SetPickupActive', {{'bActive','BoolProperty',0}})
        signature('/Script/AIModule.BrainComponent:StopLogic', {{'Reason','StrProperty',0}})
        signature('/Script/Engine.Pawn:AddMovementInput',
            {{'WorldDirection','StructProperty',0},{'ScaleValue','FloatProperty',24},{'bForce','BoolProperty',28}})
        signature('/Script/Valhalla.ValCharacterMovementComponent:SetWantsToSki', {{'bEnabled','BoolProperty',0}})
        signature('/Script/GameplayAbilities.AbilitySystemComponent:TryActivateAbility',
            {{'AbilityToActivate','StructProperty',0},{'bAllowRemoteActivation','BoolProperty',4},{'ReturnValue','BoolProperty',5}})
        signature('/Script/GameplayAbilities.AbilitySystemBlueprintLibrary:SendGameplayEventToActor',
            {{'Actor','ObjectProperty',0},{'EventTag','StructProperty',8},{'Payload','StructProperty',16}})
        local function publish(name, value)
            local prefix = env.wave > 1 and ('wave-'..env.wave..'-') or ''
            local filename = env.path..'/'..prefix..name
            local file = assert(io.open(filename..'.tmp','w'))
            assert(file:write(value,'\n'));assert(file:close())
            assert(os.rename(filename..'.tmp', filename..'.csv'))
        end

        local flags = {}
        for _, flag in ipairs(FindAllOf('TopPickup_Flag') or {}) do
            if valid(flag) and flag:GetWorld():GetAddress() == world then
                assert(not valid(flag:GetOwner()), 'flight_flag_owned')
                flags[#flags+1] = {flag=flag,active=flag.r_bPickupActive}
                flag:SetPickupActive(false)
                assert(not flag.r_bPickupActive,'flight_flag_disable_failed')
            end
        end
        local hills
        local recovery = env.hill_kind == 'recovery'
        if env.hill_kind then
            env.hill_courses = env.hill_courses or assert(loadfile(env.hill_script))().survey(env,entries)
            hills = env.hill_courses
            if env.hill_kind == 'uphill' or recovery then
                signature('/Script/Engine.Actor:K2_TeleportTo',
                    {{'DestLocation','StructProperty',0},{'DestRotation','StructProperty',24},{'ReturnValue','BoolProperty',48}})
                signature('/Script/Engine.Controller:SetControlRotation',{{'NewRotation','StructProperty',0}})
            end
        end
        if recovery then
            signature('/Script/Engine.Character:LaunchCharacter',
                {{'LaunchVelocity','StructProperty',0},{'bXYOverride','BoolProperty',24},{'bZOverride','BoolProperty',25}})
        end
        local uphill = env.hill_kind == 'uphill'
        local lanes = {}
        for index, entry in ipairs(entries) do
            local pawn, controller = entry.pawn, entry.controller
            assert(valid(pawn) and valid(controller) and pawn:HasAuthority()
                and pawn:GetWorld():GetAddress() == world and pawn.PlayerState.bIsABot
                and pawn:GetTeamId() == entry.team, 'flight_pawn_scope')
            local brain, jet = controller:GetStateTreeComponent(), pawn:GetEquippedAbility(slot, false)
            assert(valid(brain) and brain:IsRunning() and jet.Handle >= 0, 'flight_pawn_not_ready')
            local plan = assert(env.flight_plan[index], 'flight_profile_missing')
            assert((plan.ski == 0 or plan.ski == 1) and plan.pulse >= 0 and plan.pulse <= 1.25
                and plan.period >= 1.5 and plan.period <= 6, 'flight_profile_invalid')
            assert(not env.strict_flight or (plan.ski == 1 and (env.hill_kind == 'downhill' or plan.pulse > 0)),
                'flight_movement_required')
            local origin = pawn:K2_GetActorLocation()
            local hill = hills and hills[index]
            local yaw = hill and (hill.yaw+(uphill and 180 or 0)) or entry.training_facing.Yaw
            brain:StopLogic('Local flight practice')
            pawn.bCanBeDamaged = false
            lanes[index] = {pawn=pawn, controller=controller, movement=pawn.CharacterMovement, jet=jet,
                origin={X=origin.X,Y=origin.Y,Z=origin.Z}, heading={X=math.cos(math.rad(yaw)),Y=math.sin(math.rad(yaw)),Z=0}, yaw=yaw, plan=plan, hill=hill,
                jetting=false, skiing=false, next_sample=0,
                trace={'seconds,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,vz_cm_s,energy,ski,jet,carrying,phase,grounded,forward_m,heading_deg,course_drop_m,cross_m'}}
        end
        if uphill then
            for index, lane in ipairs(lanes) do
                local last = lane.hill.last
                local bottom = {X=last.X,Y=last.Y,Z=last.Z+lane.pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()+8}
                local facing = {Pitch=0,Yaw=lane.yaw,Roll=0}
                lane.target = bottom
                assert(lane.pawn:K2_TeleportTo(bottom,facing),'hill_start_placement_failed|slot='..index)
                lane.controller:SetControlRotation(facing)
                lane.movement:StopMovementImmediately()
            end
        end
        for i, a in ipairs(lanes) do
            for j=i+1,#lanes do
                local b = lanes[j]
                a.pawn.CapsuleComponent:IgnoreActorWhenMoving(b.pawn,true)
                b.pawn.CapsuleComponent:IgnoreActorWhenMoving(a.pawn,true)
            end
        end
        local function jet_input(lane, rising)
            if rising and not lane.jetting and lane.pawn:GetEnergy() >= 16 then
                lane.jetting = lane.pawn.AbilitySystemComponent:TryActivateAbility(lane.jet,false)
            elseif lane.jetting and not rising then
                events:SendGameplayEventToActor(lane.pawn,stop_tag,{})
                lane.jetting = false
            end
        end
        local function finish(lane)
            lane.done = true
            jet_input(lane,false)
            lane.movement:SetWantsToSki(false)
            lane.movement:StopMovementImmediately()
        end
        local function sample(lane, elapsed)
            local pawn, movement = lane.pawn, lane.movement
            local at, velocity = pawn:K2_GetActorLocation(), movement.Velocity
            local grounded, energy = movement:IsMovingOnGround(), pawn:GetEnergy()
            local dx,dy = at.X-lane.origin.X,at.Y-lane.origin.Y
            local forward = (dx*lane.heading.X+dy*lane.heading.Y)/100
            local lateral = (-dx*lane.heading.Y+dy*lane.heading.X)/100
            local ended = forward >= env.course_m or elapsed >= env.seconds or (lane.hill and math.abs(lateral) > (recovery and 24 or 12))
            if elapsed >= lane.next_sample or ended then
                lane.trace[#lane.trace+1] = ('%.3f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.2f,%d,%d,0,%s,%d,%.3f,%.3f,%.3f,%.3f'):format(
                    elapsed,at.X,at.Y,at.Z,velocity.X,velocity.Y,velocity.Z,energy,
                    movement:IsSkiing() and 1 or 0,movement.bIsJetpackActive and 1 or 0,
                    grounded and 'ground' or 'air',grounded and 1 or 0,forward,lane.yaw,
                    lane.hill and lane.hill.drop/100 or 0,lateral)
                lane.next_sample = elapsed+.2
            end
            return ended, lateral
        end
        local placed = clock:GetTimeSeconds(gm)
        local begin
        if not uphill then
            if not recovery then
                for _, lane in ipairs(lanes) do sample(lane,0) end
            end
            begin = placed
        end
        local function prepare_recovery(lane, now)
            local pawn, movement = lane.pawn, lane.movement
            assert(now-placed < 15, 'flight_recovery_setup_timeout')
            if not lane.shoved then
                if pawn:GetEnergy() > 34 then
                    jet_input(lane,true)
                    return false
                end
                jet_input(lane,false)
                local facing = {Pitch=0,Yaw=lane.yaw,Roll=0}
                assert(pawn:K2_TeleportTo(lane.origin,facing),'flight_recovery_start_blocked')
                lane.controller:SetControlRotation(facing)
                movement:StopMovementImmediately()
                movement:SetWantsToSki(true)
                lane.skiing = true
                pawn:LaunchCharacter({X=-lane.heading.Y*950,Y=lane.heading.X*950,Z=160},true,true)
                lane.shoved = true
                return false
            end
            local v = movement.Velocity
            if -v.X*lane.heading.Y+v.Y*lane.heading.X < 600 then return false end
            assert(pawn:GetEnergy() <= 48,'flight_recovery_energy_not_low')
            local at = pawn:K2_GetActorLocation()
            lane.origin = {X=at.X,Y=at.Y,Z=at.Z}
            lane.recovery_begin = now
            sample(lane,0)
            return true
        end
        local function frame()
            env.scope()
            for _, entry in ipairs(flags) do
                assert(not valid(entry.flag:GetOwner()),'flight_flag_was_picked_up')
                if entry.flag.r_bPickupActive then entry.flag:SetPickupActive(false) end
            end
            local now = clock:GetTimeSeconds(gm)
            if not begin then
                for index, lane in ipairs(lanes) do
                    local at,v = lane.pawn:K2_GetActorLocation(),lane.movement.Velocity
                    assert(now-placed < 6, 'hill_start_ground_timeout|slot='..index)
                    assert((at.X-lane.target.X)^2+(at.Y-lane.target.Y)^2 <= 35^2, 'hill_start_shifted|slot='..index)
                    if not lane.movement:IsMovingOnGround() or v.X^2+v.Y^2+v.Z^2 > 30^2 then return true end
                    assert(lane.pawn:GetEnergy() >= 98,'hill_start_energy|slot='..index)
                end
                for _, lane in ipairs(lanes) do
                    local at = lane.pawn:K2_GetActorLocation()
                    lane.origin = {X=at.X,Y=at.Y}
                    sample(lane,0)
                end
                begin = now
            end
            local pending = 0
            for index, lane in ipairs(lanes) do
                if not lane.done then
                    local pawn = lane.pawn
                    assert(valid(pawn) and valid(lane.controller.Pawn)
                        and lane.controller.Pawn:GetAddress() == pawn:GetAddress()
                        and pawn:GetHealth() > 0, 'flight_pawn_changed')
                    if recovery and not lane.recovery_begin and not prepare_recovery(lane,now) then
                        pending = pending+1
                        goto next_lane
                    end
                    local elapsed = now-(lane.recovery_begin or begin)
                    local ended, lateral = sample(lane,elapsed)
                    if ended then
                        finish(lane)
                        publish('team-bot-'..index..'-trace',table.concat(lane.trace,'\n'))
                    else
                        pending = pending+1
                        local plan = lane.plan
                        local skiing = plan.ski == 1 and (env.strict_flight or elapsed > (plan.ski_delay or .40))
                        if skiing ~= lane.skiing then
                            lane.movement:SetWantsToSki(skiing)
                            lane.skiing = skiing
                        end
                        local delay = env.strict_flight and 0 or .35
                        local cycle = math.max(0,elapsed-delay)%plan.period
                        jet_input(lane,plan.pulse > cycle and elapsed >= delay)
                        local heading = lane.heading
                        if lane.hill then
                            local limit = plan.steer_cap or (recovery and .65 or .32)
                            local correction = math.max(-limit,math.min(limit,math.atan(-lateral,12)))
                            local angle = math.rad(lane.yaw)+correction
                            heading = {X=math.cos(angle),Y=math.sin(angle),Z=0}
                        end
                        pawn:AddMovementInput(heading,1,true)
                    end
                end
                ::next_lane::
            end
            if pending > 0 then return true end
            for _, entry in ipairs(flags) do
                entry.flag:SetPickupActive(entry.active)
                assert(entry.flag.r_bPickupActive == entry.active,'flight_flag_restore_failed')
            end
            publish('flight-complete',env.wave..','..#lanes)
            env.wave_finished = true
            return false
        end
        local function tick()
            local ok, again = pcall(frame)
            if not ok then env.report('BOT_TRAIN_ERROR|'..tostring(again):sub(1,400))
            elseif again then ExecuteInGameThreadAfterFrames(1,tick) end
        end
        publish('team-ready',env.wave..','..#lanes)
        env.report('BOT_FLIGHT_READY|'..env.wave..'|'..#lanes)
        ExecuteInGameThreadAfterFrames(1,tick)
    end
end
