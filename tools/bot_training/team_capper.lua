return function(env, gm, gs, entries, stands, clock, begin)
    local assignments = env.guided or {}
    if next(assignments) == nil then return function() end, function() return nil end end
    local valid, report = env.valid, env.report
    local geometry = assert(loadfile(env.route_geometry))()
    local events = StaticFindObject('/Script/GameplayAbilities.Default__AbilitySystemBlueprintLibrary')
    local world = gm:GetWorld():GetAddress()
    local jet_slot = {TagName=FName('EquipSlot.Jetpack')}
    local stop_tag = {TagName=FName('State.Jetpacking.StopAI')}
    local flags = {}
    for _, flag in ipairs(FindAllOf('TopPickup_Flag') or {}) do
        if valid(flag) and flag:GetWorld():GetAddress() == world then flags[flag.r_TeamId] = flag end
    end
    env.signature('/Script/AIModule.BrainComponent:StopLogic',{{'Reason','StrProperty',0}})
    env.signature('/Script/Engine.Pawn:AddMovementInput',{
        {'WorldDirection','StructProperty',0},{'ScaleValue','FloatProperty',24},{'bForce','BoolProperty',28}})
    env.signature('/Script/Valhalla.ValCharacterMovementComponent:SetWantsToSki',{{'bEnabled','BoolProperty',0}})
    env.signature('/Script/GameplayAbilities.AbilitySystemComponent:TryActivateAbility',{
        {'AbilityToActivate','StructProperty',0},{'bAllowRemoteActivation','BoolProperty',4},{'ReturnValue','BoolProperty',5}})
    env.signature('/Script/GameplayAbilities.AbilitySystemBlueprintLibrary:SendGameplayEventToActor',{
        {'Actor','ObjectProperty',0},{'EventTag','StructProperty',8},{'Payload','StructProperty',16}})

    local trackers, by_slot = {}, {}
    local function score(team)
        local result = 0
        gs.r_CurrentTeamScores:ForEach(function(_, element)
            local row=element:get()
            if row.TeamNum==team then result=row.Score end
        end)
        return result
    end

    local function finish(item, outcome)
        if item.finished then return end
        item.finished = outcome
        if env.live_player then item.restart_at = clock:GetTimeSeconds(gm) + 8 end
        local pawn, controller = item.pawn, item.entry.controller
        if item.started and valid(pawn) and valid(controller.Pawn)
            and pawn:GetAddress()==controller.Pawn:GetAddress() then
            if item.jetting then events:SendGameplayEventToActor(pawn,stop_tag,{}) end
            if item.skiing then pawn.CharacterMovement:SetWantsToSki(false) end
            if not item.tree:IsRunning() then controller:StartStateTree() end
        end
    end

    local function move(item, now, visible)
        if item.finished then return end
        local entry, plan = item.entry, item.plan
        local pawn = entry.controller.Pawn
        if not valid(pawn) or pawn:GetHealth() <= 0 or (item.pawn and pawn:GetAddress()~=item.pawn:GetAddress()) then
            if item.started then
                item.failure = item.pickup and 'carrier_down' or 'outbound_death'
                finish(item,item.pickup and 'grab' or 'miss')
            end
            return
        end
        local flag = flags[3-entry.team]
        if not valid(flag) or not stands[entry.team] or not stands[3-entry.team] then return end
        local owner = flag:GetOwner()
        local carrying = valid(owner) and owner:GetAddress()==pawn:GetAddress()
        local engagement = env.adaptive_movement and visible and visible[item.index_id]
        local may_fight = engagement and engagement < 4800
        local movement = pawn.CharacterMovement
        local at, v = pawn:K2_GetActorLocation(), movement.Velocity
        if env.approach_reward and item.started and not item.pickup then
            local distance = geometry.stand_distance(at, stands[3-entry.team])
            if not carrying then
                geometry.sample_approach(item,distance,.036*math.sqrt(v.X*v.X+v.Y*v.Y))
            elseif distance <= 800 then
                item.pickup_entry, item.pickup_approach_peak = item.approach_entry, item.approach_peak
            end
        end
        if not item.started then
            if valid(owner) then return end
            local tree, jet = entry.controller:GetStateTreeComponent(), pawn:GetEquippedAbility(jet_slot,false)
            if not valid(tree) or jet.Handle<0 then
                if not env.live_player and now-begin>5 then finish(item,'censored') end
                return
            end
            local pos, home = flag:K2_GetActorLocation(), stands[entry.team]
            if env.live_player and geometry.stand_distance(pos, stands[3-entry.team]) > 800 then return end
            local x,y=home.X-pos.X,home.Y-pos.Y
            local range=math.sqrt(x*x+y*y)
            if range<100 then finish(item,'censored'); return end
            item.flag, item.home, item.hx, item.hy = {X=pos.X,Y=pos.Y,Z=pos.Z},home,x/range,y/range
            item.points = geometry.waypoints(item.flag,item.hx,item.hy,plan.flank,plan.runup,plan.layout)
            item.pass_x,item.pass_y = geometry.pass_axis(item.flag,item.points,item.hx,item.hy,plan.layout)
            item.tree, item.jet, item.pawn, item.started, item.index = tree,jet,pawn,now,1
            entry.controller:StopMovement()
            if not may_fight then tree:StopLogic('Local capper route training') end
            report(('BOT_GUIDED_ROUTE|bot=%d|%s'):format(item.index_id,plan.name))
        elseif carrying and not item.pickup then
            item.pickup = .036*math.sqrt(v.X*v.X+v.Y*v.Y)
            item.homeward = .036*(v.X*item.hx+v.Y*item.hy)
            item.pickup_ski = movement:IsSkiing()
            item.before = score(entry.team)
            item.picked_at = now
        elseif item.pickup and not carrying then
            local captured = score(entry.team)>item.before
            if not captured then item.failure = 'flag_lost' end
            finish(item,captured and 'capture' or 'grab')
            return
        elseif valid(owner) and not carrying then
            item.failure = 'other_carrier'
            finish(item,'censored')
            return
        end
        local elapsed = now-item.started
        local limit = plan.layout and math.min(env.seconds,145) or 76
        if carrying and item.picked_at and not item.escape_seconds and geometry.stand_distance(at,item.flag) >= 3000 then
            item.escape_seconds = now-item.picked_at
        end
        if elapsed>=limit then
            item.failure = item.pickup and 'return_timeout' or 'approach_timeout'
            finish(item,item.pickup and 'grab' or 'miss')
            return
        end
        local point = not carrying and item.points[item.index]
        local radius = item.index==#item.points and (plan.layout and 850 or 1150) or 1800
        if point and (at.X-point.X)^2+(at.Y-point.Y)^2<radius*radius then
            item.index=item.index+1
            point=item.points[item.index]
        end
        local target=carrying and item.home or point or item.flag
        local x,y=target.X-at.X,target.Y-at.Y
        local heading=math.atan(y,x)+math.rad(plan.turn)
        local flight = env.flight_transfer or {}
        local energy = pawn:GetEnergy()
        local profile = carrying and env.adaptive_movement and (
            (energy<48 and flight.recovery) or (target.Z>at.Z+300 and flight.uphill) or flight.straight)
        local pulse,period = profile and profile.pulse or plan.pulse,profile and profile.period or plan.period
        local rising=elapsed%period<pulse
        if not carrying and not point then
            local horizontal = geometry.stand_distance(at,item.flag)
            local distance = math.sqrt(horizontal^2+(at.Z-item.flag.Z)^2)
            if not item.closest_pass or distance<item.closest_pass then
                item.closest_pass,item.closest_speed=distance,.036*math.sqrt(v.X*v.X+v.Y*v.Y)
            end
            local along=(at.X-item.flag.X)*item.pass_x+(at.Y-item.flag.Y)*item.pass_y
            if along>750 then item.failure = 'missed_flag'; finish(item,'miss'); return end
            heading,rising=geometry.flythrough(item.flag,at,v,item.pass_x,item.pass_y,plan.guidance)
        end
        if env.adaptive_movement then
            if may_fight and not item.tree:IsRunning() then entry.controller:StartStateTree()
            elseif not may_fight and item.tree:IsRunning() then item.tree:StopLogic('Local capper route training') end
            if carrying and may_fight and x*x+y*y > 1400^2 then
                local direction = (math.floor(elapsed/1.15)+item.index_id)%2 == 0 and 1 or -1
                heading = heading+direction*.27
            end
        end
        heading=geometry.limit_turn(heading,v)
        local reserve = env.adaptive_movement and (env.jet_reserve or 26) or 10
        if rising and pulse>0 and not item.jetting and energy>=reserve then
            item.jetting=pawn.AbilitySystemComponent:TryActivateAbility(item.jet,false)
        elseif not rising and item.jetting then
            events:SendGameplayEventToActor(pawn,stop_tag,{})
            item.jetting=false
        end
        if (env.strict_movement or plan.ski==1) and (not item.skiing or (env.adaptive_movement and not movement.bWantsToSki)) then
            movement:SetWantsToSki(true)
            item.skiing=true
        end
        pawn:AddMovementInput({X=math.cos(heading),Y=math.sin(heading),Z=0},1,true)
    end

    for index, plan in pairs(assignments) do
        local item = {entry=entries[index],plan=plan,index_id=index}
        trackers[#trackers+1], by_slot[index] = item, item
    end
    return function(visible)
        local now=clock:GetTimeSeconds(gm)
        if gm:GetMatchState():ToString()~='InProgress' then return end
        for index, item in ipairs(trackers) do
            if item.restart_at and now >= item.restart_at then
                item = {entry=item.entry, plan=item.plan, index_id=item.index_id}
                trackers[index] = item
                by_slot[item.index_id] = item
            end
            local ok, why=pcall(move,item,now,visible)
            if not ok then
                pcall(finish,item,'censored')
                item.restart_at = nil
                report('BOT_GUIDE_FALLBACK|'..tostring(why):sub(1,230))
            end
        end
    end, function()
        local rows={'bot,outcome,pickup_kmh,homeward_kmh,skiing,approach_entry_kmh,approach_peak_kmh,pass_gap_m,pass_speed_kmh,escape_seconds,failure'}
        for _, item in ipairs(trackers) do
            if not item.finished then item.failure = 'match_ended' end
            finish(item,item.pickup and 'grab' or 'censored')
            local row=('%d,%s,%.3f,%.3f,%d'):format(item.index_id,item.finished,item.pickup or 0,
                item.homeward or 0,item.pickup_ski and 1 or 0)
            row=row..(item.pickup_entry and (',%.3f,%.3f'):format(item.pickup_entry,item.pickup_approach_peak) or ',,')
            row=row..(item.closest_pass and (',%.3f,%.3f'):format(item.closest_pass/100,item.closest_speed) or ',,')
            row=row..(item.escape_seconds and (',%.3f'):format(item.escape_seconds) or ',')..','..(item.failure or '')
            rows[#rows+1]=row
        end
        return table.concat(rows,'\n')
    end, function(slot)
        local item = by_slot[slot]
        return item ~= nil and not item.finished
    end
end
