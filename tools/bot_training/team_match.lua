return function(env)
    local valid = env.valid
    return function(gm, gs, entries)
        assert(gm:HasAuthority() and #entries == env.blue + env.red, 'team_training_roster')
        local clock = StaticFindObject('/Script/Engine.Default__GameplayStatics')
        local world = gm:GetWorld():GetAddress()
        local roles = env.roles or {}
        local defense_tactics = env.defense_tactics or {}
        local offense_tactics, offense_commands = env.offense_tactics or {}, {}
        local request_travel, steer_travel, clear_travel, finish_travel, assist_open_travel
        if env.role_movement_script then
            request_travel, steer_travel, clear_travel, finish_travel, assist_open_travel = assert(loadfile(env.role_movement_script))()(env)
        end
        if #roles > 0 then
            env.signature('/Script/AIModule.AIController:MoveToLocation',{
                {'Dest','StructProperty',0},{'AcceptanceRadius','FloatProperty',24},{'bStopOnOverlap','BoolProperty',28},
                {'bUsePathfinding','BoolProperty',29},{'bProjectDestinationToNavigation','BoolProperty',30},
                {'bCanStrafe','BoolProperty',31},{'FilterClass','ClassProperty',32},{'bAllowPartialPath','BoolProperty',40},
                {'ReturnValue','ByteProperty',41}})
        end
        local function distance(a, b)
            return math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2+(a.Z-b.Z)^2)
        end
        local field = env.field_tactics_script and assert(loadfile(env.field_tactics_script))()(env,distance)
        local intel, visible, jobs
        local counts, traces, previous = {0, 0}, {}, {}
        local flag_states, base_states, at_base, dropped = {}, {}, nil, nil
        local state_enum = StaticFindObject('/Script/Topaz.ETopFlagState')
        if valid(state_enum) then
            state_enum:ForEachName(function(name,id)
                local label = name:ToString():match('([^:]+)$')
                if label == 'AtBase' or label == 'AtStand' then at_base = id end
                if label == 'Dropped' then dropped = id end
            end)
            if dropped then
                local ok = pcall(env.signature, '/Script/Topaz.TopPickup_Flag:GetFlagState',
                    {{'Querier','ObjectProperty',0},{'ReturnValue','EnumProperty',8}})
                if not ok then dropped = nil end
            end
        end
        local stands = {}
        for _, stand in ipairs(FindAllOf('TopFlagStand') or {}) do
            if valid(stand) and stand:GetWorld():GetAddress() == world then
                stands[stand.TeamNum] = stand:K2_GetActorLocation()
            end
        end
        local function flag_distance(pos, team)
            local stand = stands[team]
            return stand and distance(pos, stand) or -1
        end
        local score_log, previous_score = {'seconds,blue,red'}, nil
        local events, pursuit = {'seconds,event,team,bot'}, {}
        local function event(elapsed, name, team, bot)
            events[#events+1] = ('%.3f,%s,%d,%d'):format(elapsed,name,team,bot or 0)
        end
        local function read_scores()
            local score = {}
            gs.r_CurrentTeamScores:ForEach(function(_, element)
                local row = element:get()
                score[row.TeamNum] = row.Score
            end)
            return score
        end
        local function read_equipment()
            local rows = {}
            for _, actor in ipairs(FindAllOf('TopGenerator') or {}) do
                if valid(actor) and actor:GetWorld():GetAddress() == world and (actor.r_TeamId == 1 or actor.r_TeamId == 2) then
                    rows[actor:GetAddress()] = {kind='generators',team=actor.r_TeamId,
                        health=actor:IsOnline() and 1 or 0,pos=actor:K2_GetActorLocation()}
                end
            end
            for _, actor in ipairs(FindAllOf('BP_Topaz_BaseTurret_C') or {}) do
                if valid(actor) and actor:GetWorld():GetAddress() == world and actor.bInitialized then
                    local team = actor:GetTeamId()
                    if team == 1 or team == 2 then
                        rows[actor:GetAddress()] = {kind='turrets',team=team,
                            health=actor:GetHealth(),pos=actor:K2_GetActorLocation()}
                    end
                end
            end
            return rows
        end
        local equipment = env.base_equipment and read_equipment() or {}
        local initial_equipment, downed = equipment, {}
        local equipment_events = {'seconds,kind,team,x_cm,y_cm,z_cm'}
        local function sample_equipment(elapsed)
            if not env.base_equipment then return end
            equipment = read_equipment()
            for address, row in pairs(initial_equipment) do
                if not downed[address] and row.health > 0 and (not equipment[address] or equipment[address].health <= 0) then
                    downed[address] = row
                    event(elapsed, row.kind == 'generators' and 'generator_down' or 'turret_down', row.team)
                    equipment_events[#equipment_events+1] = ('%.3f,%s,%d,%.2f,%.2f,%.2f'):format(
                        elapsed,row.kind,row.team,row.pos.X,row.pos.Y,row.pos.Z)
                end
            end
        end
        local begin = clock:GetTimeSeconds(gm)
        local duel, duel_receipt
        if env.duel_script then
            duel,duel_receipt = assert(loadfile(env.duel_script))()(env,entries,stands,world,begin)
        end
        local end_combat
        if env.combat_script then end_combat = assert(loadfile(env.combat_script))()(env,gm,entries,clock,begin) end
        local guide = env.guide_script and assert(loadfile(env.guide_script))()
        local guide_tick, guide_results, guide_pending
        if guide then guide_tick,guide_results,guide_pending = guide(env,gm,gs,entries,stands,clock,begin) end
        local function publish(name, data)
            if (env.wave or 1) > 1 then name = 'wave-'..env.wave..'-'..name end
            local path = env.path..'/'..name
            local file = assert(io.open(path..'.tmp', 'w'))
            assert(file:write(data, '\n'))
            assert(file:close())
            assert(os.rename(path..'.tmp', path..'.csv'))
        end
        for index, entry in ipairs(entries) do
            assert(valid(entry.controller) and valid(entry.pawn) and entry.pawn.PlayerState.bIsABot
                and entry.pawn:GetTeamId() == entry.team, 'team_training_member')
            counts[entry.team] = counts[entry.team]+1
            traces[index] = {'seconds,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,vz_cm_s,energy,ski,jet,carrying,phase,health,home_flag_cm,enemy_flag_cm,grounded,open_travel'}
        end
        assert(counts[1] == env.blue and counts[2] == env.red, 'team_training_counts')
        env.report(('BOT_TEAM_READY|%d|%d'):format(counts[1], counts[2]))
        if (env.wave or 1) > 1 then publish('team-ready', env.wave..','..#entries) end
        local function attack_target(team, home, enemy, tactic, carriers, combatants)
            local capper_range, guard, guard_range = math.huge, nil, 3200
            for _, ally in ipairs(combatants[team]) do
                if ally.role == 'Capper' then capper_range = math.min(capper_range, distance(ally.pos, enemy)) end
            end
            local use_intel = intel and (not env.adaptive_team or env.adaptive_team == team)
            for _, opponent in pairs(use_intel and intel[team] or combatants[3-team]) do
                local range = distance(opponent.pos, enemy)
                if range < guard_range then guard, guard_range = opponent.pos, range end
            end
            local dx, dy = home.X-enemy.X, home.Y-enemy.Y
            local length = math.sqrt(dx*dx+dy*dy)
            if length < 100 then return nil end
            local push = capper_range <= tactic.launch or carriers[3-team] ~= nil
            if push and tactic.raid then
                local objective, nearest = nil, math.huge
                for _, item in pairs(equipment) do
                    if item.team == 3-team and item.health > 0 then
                        local range = distance(item.pos, enemy)
                        if range < nearest then objective, nearest = item.pos, range end
                    end
                end
                if objective then return objective, 'push' end
            end
            if push and guard then return guard, 'push' end
            local depth = math.min(push and tactic.strike or tactic.stage, .4*length)
            local lateral = push and 0 or tactic.flank*(team == 1 and 1 or -1)
            return {X=enemy.X+(dx*depth-dy*lateral)/length,
                    Y=enemy.Y+(dy*depth+dx*lateral)/length,
                    Z=enemy.Z+(home.Z-enemy.Z)*depth/length}, push and 'push' or 'stage'
        end
        local function direct_role(index, entry, pawn, pos, carriers, flag_locations, combatants, now)
            local role = roles[index]
            local tactic = defense_tactics[index] or {}
            local offense = offense_tactics[index]
            local home, enemy = stands[entry.team], stands[3-entry.team]
            if not role or not home or not enemy then return end
            local use_intel = field and (not env.adaptive_team or env.adaptive_team == entry.team)
            if role == 'Capper' and (not env.strict_movement or (env.adaptive_team and not use_intel)
                or (guide_pending and guide_pending(index))) then return end
            local target, radius, command = nil, 850, nil
            local chased_carrier
            local nearest = use_intel and (visible[index] or math.huge) or math.huge
            local threat, threat_distance
            for _, opponent in pairs(use_intel and intel[entry.team] or combatants[3-entry.team]) do
                if not use_intel then nearest = math.min(nearest, distance(opponent.pos, pos)) end
                local to_home = distance(opponent.pos, home)
                if not threat_distance or to_home < threat_distance then
                    threat, threat_distance = opponent, to_home
                end
            end
            local job = use_intel and jobs[index]
            local engagement = use_intel and nearest < 4800 and {evade=role == 'Capper'} or nil
            if job and job.kind == 'chase' then
                local seen = job.sighting
                local lead = math.max(0,(env.pursuit_lead or tactic.lead or .65)-(now-seen.seen))
                local p,v = seen.pos,seen.v
                target = {X=p.X+lead*v.X,Y=p.Y+lead*v.Y,Z=p.Z+lead*v.Z*.3}
                chased_carrier, radius = seen.id, 650
            elseif job and job.kind == 'cutoff' then
                target, radius = job.target, 1250
                if pursuit[index] ~= 'cutoff' then event(now-begin,'cutoff_started',entry.team,index) end
                chased_carrier = 'cutoff'
            elseif role == 'Capper' then
                local enemy_carrier = carriers[3-entry.team]
                if enemy_carrier and enemy_carrier:GetAddress() == pawn:GetAddress() then
                    target = home
                elseif nearest > 1600 then
                    target = enemy_carrier and home or flag_locations[3-entry.team] or enemy
                end
            elseif role == 'Heavy on flag' then
                if use_intel and distance(pos,home) > 1000 then target,radius = home,700
                elseif distance(pos, home) > 1400 and nearest > (tactic.handoff or 1600) then target = home end
            elseif role == 'Light defense' then
                local carrier = not use_intel and carriers[entry.team]
                if carrier then
                    local p, v = carrier:K2_GetActorLocation(), carrier.CharacterMovement.Velocity
                    local lead = tactic.lead or .5
                    if distance(pos, p) > (tactic.carrier_handoff or 2000) then
                        target = {X=p.X+lead*v.X,Y=p.Y+lead*v.Y,Z=p.Z}
                        chased_carrier = carrier:GetAddress()
                    end
                elseif threat and threat_distance < (tactic.trigger or 6500) then
                    if distance(pos, threat.pos) > (tactic.handoff or 2400) then
                        local p, v = threat.pos, threat.v or threat.pawn.CharacterMovement.Velocity
                        local lead = tactic.incoming_lead or 0
                        target = {X=p.X+lead*v.X,Y=p.Y+lead*v.Y,Z=p.Z}
                    end
                elseif distance(pos, home) > 3500 then
                    target, radius = home, 2200
                end
            elseif role == 'Medium defense' then
                local line = distance(home, enemy)
                if line > 100 and nearest > (tactic.handoff or 2100) then
                    if threat and threat_distance < (tactic.intercept or 0) then
                        target = threat.pos
                    else
                        local fraction = math.min(.3, (tactic.depth or 2200) / line)
                        target = {X=home.X+(enemy.X-home.X)*fraction,Y=home.Y+(enemy.Y-home.Y)*fraction,Z=home.Z}
                    end
                end
            elseif offense and offense.launch then
                if nearest > offense.handoff then
                    target, command = attack_target(entry.team,home,enemy,offense,carriers,combatants)
                end
            elseif nearest > 2400 and distance(pos, enemy) > 2800 then
                target, radius = enemy, 2000
            end
            if target and distance(pos, target) > radius then
                if chased_carrier and pursuit[index] ~= chased_carrier then
                    if chased_carrier ~= 'cutoff' then event(now-begin, 'chase_started', entry.team, index) end
                end
                pursuit[index] = chased_carrier
                if not request_travel or not request_travel(index,entry,pawn,pos,target,radius,now,offense or tactic,engagement) then
                    entry.controller:MoveToLocation(target,radius,false,true,true,false,nil,true)
                end
                if command then
                    local totals = offense_commands[index] or {stage=0,push=0}
                    totals[command] = totals[command]+1
                    offense_commands[index] = totals
                end
            else
                pursuit[index] = nil
                if clear_travel then clear_travel(index) end
            end
        end
        local next_sample, next_directive = 0, 0
        local function sample()
            env.scope()
            local elapsed = clock:GetTimeSeconds(gm)-begin
            if elapsed < next_sample then return true end
            next_sample = elapsed+.25
            local owners, carriers, flag_locations = {}, {}, {}
            local querier
            if dropped then
                for _, entry in ipairs(entries) do
                    local pawn = entry.controller.Pawn
                    if valid(pawn) and pawn:GetHealth() > 0 then querier = pawn; break end
                end
            end
            for _, flag in ipairs(FindAllOf('TopPickup_Flag') or {}) do
                if valid(flag) and flag:GetWorld():GetAddress() == world then
                    local team = flag.r_TeamId
                    local owner = flag:GetOwner()
                    if dropped and querier and (team == 1 or team == 2) then
                        local observed, state = pcall(function() return flag:GetFlagState(querier) end)
                        if not observed then
                            dropped = nil
                            env.report('BOT_FLAG_STATE_UNAVAILABLE|'..tostring(state):sub(1,180))
                        else
                            local base = at_base or base_states[team]
                            if not base and state ~= dropped and flag.r_bPickupActive and not valid(owner)
                                    and stands[team] and flag_distance(flag:K2_GetActorLocation(), team) <= 800 then
                                base_states[team], base = state, state
                            end
                            if flag_states[team] and flag_states[team] ~= dropped and state == dropped then
                                event(elapsed, 'flag_dropped', team)
                            elseif flag_states[team] == dropped and base and state == base then
                                event(elapsed, 'flag_returned', team)
                            end
                            flag_states[team] = state
                        end
                    end
                    if valid(owner) then
                        owners[owner:GetAddress()] = true
                        if #roles > 0 and valid(owner.CharacterMovement) then carriers[flag.r_TeamId] = owner end
                    elseif env.strict_movement and (team == 1 or team == 2) then
                        flag_locations[team] = flag:K2_GetActorLocation()
                    end
                end
            end
            local state = gm:GetMatchState():ToString()
            local score = read_scores()
            local duel_ready, duel_outcome = true, nil
            if duel then duel_ready,duel_outcome = duel(begin+elapsed,score) end
            local combatants
            if #roles > 0 and elapsed >= next_directive and state == 'InProgress' and duel_ready and not duel_outcome then
                sample_equipment(elapsed)
                combatants = {{}, {}}
                for index, entry in ipairs(entries) do
                    local pawn = entry.controller.Pawn
                    if valid(pawn) and pawn:GetHealth() > 0 then
                        local group = combatants[entry.team]
                        group[#group+1] = {pos=pawn:K2_GetActorLocation(),pawn=pawn,role=roles[index],
                                           index=index,controller=entry.controller}
                    end
                end
                if env.live_player then
                    for _, controller in ipairs(FindAllOf('ValPlayerController') or {}) do
                        if valid(controller) and controller:GetWorld():GetAddress() == world then
                            local pawn = controller.Pawn
                            if valid(pawn) and pawn:GetHealth() > 0 and valid(pawn.PlayerState)
                                    and not pawn.PlayerState.bIsABot then
                                local team = combatants[pawn:GetTeamId()]
                                if team then
                                    team[#team+1] = {pos=pawn:K2_GetActorLocation(),pawn=pawn,role='Capper'}
                                end
                            end
                        end
                    end
                end
                if field then intel, visible, jobs = field(combatants,carriers,stands,begin+elapsed) end
                next_directive = elapsed + (field and .5 or 1)
            end
            for team=1,2 do
                if counts[team] == 0 and score[team] == nil then score[team] = 0 end
            end
            if score[1] ~= nil and score[2] ~= nil then
                if not previous_score or score[1] ~= previous_score[1] or score[2] ~= previous_score[2] then
                    score_log[#score_log+1] = ('%.3f,%d,%d'):format(elapsed, score[1], score[2])
                end
            end
            for index, entry in ipairs(entries) do
                local pawn = entry.controller.Pawn
                local trace, prior = traces[index], previous[index]
                if valid(pawn) and pawn:GetHealth() > 0 then
                    local movement = pawn.CharacterMovement
                    local pos, vel = pawn:K2_GetActorLocation(), movement.Velocity
                    if combatants then direct_role(index, entry, pawn, pos, carriers, flag_locations, combatants, begin+elapsed) end
                    local home_range,away_range = flag_distance(pos,entry.team),flag_distance(pos,3-entry.team)
                    local open_travel = env.adaptive_movement and (not env.adaptive_team or env.adaptive_team==entry.team)
                        and home_range>=3000 and away_range>=3000 and not (visible and (visible[index] or math.huge)<4000)
                    if assist_open_travel then
                        assist_open_travel(index,entry,pawn,open_travel and state=='InProgress' and duel_ready
                                           and not (guide_pending and guide_pending(index)))
                    end
                    if env.live_player then goto next_bot end
                    local carrying = owners[pawn:GetAddress()] and 1 or 0
                    local phase = state
                    if carrying == 1 and (not prior or prior.carrying == 0) then
                        phase = 'flag_pickup'
                    elseif carrying == 0 and prior and prior.carrying == 1 then
                        phase = previous_score and score[entry.team] and previous_score[entry.team]
                            and score[entry.team] > previous_score[entry.team] and 'cap' or 'flag_lost'
                    end
                    if phase ~= state then event(elapsed, phase, entry.team, index) end
                    trace[#trace+1] = ('%.3f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.2f,%d,%d,%d,%s,%.1f,%.1f,%.1f,%d,%d'):format(
                        elapsed,pos.X,pos.Y,pos.Z,vel.X,vel.Y,vel.Z,pawn:GetEnergy(),
                        movement:IsSkiing() and 1 or 0,movement.bIsJetpackActive and 1 or 0,carrying,phase,
                        pawn:GetHealth(),home_range,away_range,movement:IsMovingOnGround() and 1 or 0, open_travel and 1 or 0)
                    previous[index] = {x=pos.X, y=pos.Y, z=pos.Z, carrying=carrying, pawn=pawn:GetAddress()}
                elseif prior and state == 'InProgress' then
                    local x,y,z, phase = prior.x,prior.y,prior.z,'death_last_seen'
                    if valid(pawn) and pawn:GetAddress() == prior.pawn then
                        local pos = pawn:K2_GetActorLocation()
                        x,y,z,phase = pos.X,pos.Y,pos.Z,'death'
                    end
                    if prior.carrying == 1 then
                        event(elapsed, 'carrier_down', entry.team, index)
                        trace[#trace+1] = ('%.3f,%.1f,%.1f,%.1f,0,0,0,0,0,0,0,flag_lost,0,-1,-1,0,0'):format(elapsed,x,y,z)
                    end
                    trace[#trace+1] = ('%.3f,%.1f,%.1f,%.1f,0,0,0,0,0,0,0,%s,0,-1,-1,0,0'):format(elapsed,x,y,z,phase)
                    previous[index] = nil
                    pursuit[index] = nil
                end
                ::next_bot::
            end
            previous_score = score
            if env.capture_limit and ((score[1] or 0) >= env.capture_limit or (score[2] or 0) >= env.capture_limit) then
                state = 'CaptureLimit'
            end
            if duel and not duel_outcome then return true end
            if not duel and elapsed < env.seconds and state == 'InProgress' then return true end
            if finish_travel then finish_travel() end
            if end_combat then
                local observations, complete, aiming, aim_boosts = end_combat()
                publish('team-combat', observations)
                publish('team-combat-status', complete and 'complete' or 'partial')
                publish('team-aim', aiming)
                if env.aim_boosts and next(env.aim_boosts) then
                    publish('team-aim-plan', ('%d,%d,%d'):format(env.wave or 1, aim_boosts[1], aim_boosts[2]))
                end
            end
            local guided = guide_results and guide_results()
            if env.live_player then return false end
            if duel_receipt then publish('team-duel',duel_receipt()) end
            if guided then publish('team-guided', guided) end
            if env.base_equipment then
                sample_equipment(elapsed)
                local rows = {'team,generators,turrets,changed'}
                for team=1,2 do
                    local counts = {generators=0,turrets=0,changed=0}
                    for _, row in pairs(downed) do
                        if row.team == team then counts[row.kind] = counts[row.kind]+1 end
                    end
                    for address, row in pairs(initial_equipment) do
                        if row.team == team and (not equipment[address] or equipment[address].health ~= row.health) then counts.changed = 1 end
                    end
                    for address, row in pairs(equipment) do
                        if row.team == team and not initial_equipment[address] then counts.changed = 1 end
                    end
                    rows[#rows+1] = ('%d,%d,%d,%d'):format(team,counts.generators,counts.turrets,counts.changed)
                end
                publish('team-base-equipment',table.concat(rows,'\n'))
                publish('team-equipment-events',table.concat(equipment_events,'\n'))
            end
            if next(offense_tactics) then
                local commands = {'bot,stage,push'}
                for index in pairs(offense_tactics) do
                    local totals = offense_commands[index] or {stage=0,push=0}
                    commands[#commands+1] = ('%d,%d,%d'):format(index,totals.stage,totals.push)
                end
                publish('team-offense-commands', table.concat(commands,'\n'))
            end
            publish('team-score', table.concat(score_log,'\n'))
            publish('team-events', table.concat(events,'\n'))
            local known_returns = dropped and (at_base or (base_states[1] and base_states[2]))
            publish('team-events-status', known_returns and 'returns_observed' or 'return_state_unavailable')
            for index, trace in ipairs(traces) do
                publish('team-bot-'..index..'-trace', table.concat(trace,'\n'))
            end
            publish('team-result', ('%.3f,%d,%d,%s'):format(elapsed,assert(score[1]),assert(score[2]),state))
            env.wave_finished = true
            return false
        end
        local function tick()
            local ok, again = pcall(function()
                if guide_tick then env.scope();guide_tick(visible) end
                if steer_travel then env.scope();steer_travel(clock:GetTimeSeconds(gm)) end
                return sample()
            end)
            if not ok then env.report('BOT_TRAIN_ERROR|'..tostring(again):sub(1,400))
            elseif again then ExecuteInGameThreadAfterFrames(1,tick) end
        end
        ExecuteInGameThreadAfterFrames(1,tick)
    end
end
