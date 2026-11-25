-- Isolated training only. Recreate native bots; never repair a damaged map by
-- guessing at its state. Any unverified reset asks Python for a fresh host.
return function(env)
    local valid, signature = env.valid, env.signature
    local baseline, retired, began, old = nil, nil, nil, {}
    local checked_persistent, drop_cleanup_attempted
    local engine_valid
    local drop_class = 'BP_TopPickup_PlayerAllDrop_C'
    local function require_reset(ok, why)
        assert(ok, 'training_reuse_unverified|'..why)
    end
    local function owned(actor, world)
        return valid(actor) and (not engine_valid or engine_valid(actor))
            and actor:HasAuthority() and valid(actor:GetWorld())
            and actor:GetWorld():GetAddress() == world:GetAddress()
    end
    local function remember_retired(actor)
        local address = actor:GetAddress()
        local names = old[address] or {}
        names[actor:GetFullName()] = true
        old[address] = names
    end
    local function equipment(world)
        local rows = {}
        for _, name in ipairs({'TopGenerator','TopRadar','TopTurret','TopShield'}) do
            for _, actor in ipairs(FindAllOf(name) or {}) do
                if owned(actor, world) then
                    rows[#rows+1] = table.concat({actor:GetFullName(), actor:GetAddress(),
                        actor:GetHealth(), actor:GetHealthMax()}, ':')
                end
            end
        end
        table.sort(rows)
        return table.concat(rows, '|')
    end
    local function flags_home(world)
        local seen = {}
        for _, stand in ipairs(FindAllOf('TopFlagStand') or {}) do
            if owned(stand, world) then
                if not stand:IsFlagAtHome() then return false end
                seen[stand.TeamNum] = true
            end
        end
        return seen[1] and seen[2]
    end
    local function persistent_gameplay(world)
        local rows, drops = {}, {}
        for _, actor in ipairs(FindAllOf('Actor') or {}) do
            if owned(actor,world) then
                local native_class = actor:GetClass()
                local class = native_class:GetFullName():lower()
                -- Keep physical gameplay actors in the reset receipt.
                if not class:find('gameplaycue',1,true) and not class:find('pickup_flag',1,true)
                    and (class:find('turret',1,true) or class:find('forcefield',1,true)
                        or class:find('shield',1,true) or class:find('mine',1,true)
                        or class:find('deployable',1,true) or class:find('pickup',1,true)) then
                    local identity = actor:GetFullName()..':'..actor:GetAddress()
                    rows[#rows+1] = identity
                    if class:find('bp_toppickup_playeralldrop',1,true)
                            and native_class:GetFName():ToString() == drop_class then
                        drops[identity] = actor
                    end
                end
            end
        end
        for _, point in ipairs(FindAllOf('TopObservationPoint') or {}) do
            if owned(point,world) then
                rows[#rows+1] = point:GetFullName()..':'..point:GetTeamId()
            end
        end
        table.sort(rows)
        return table.concat(rows,'|'), rows, drops
    end
    local function retire_bot_drops(world, rows, drops)
        if env.live_player then return false, 'live_player_session' end
        local originals, unchanged, additions = {}, {}, {}
        for item in baseline.persistent:gmatch('[^|]+') do originals[item] = true end
        for _, item in ipairs(rows) do
            if drops[item] and not originals[item] then
                additions[#additions+1] = drops[item]
            else
                unchanged[#unchanged+1] = item
            end
        end
        if #additions == 0 then return false, 'no_exact_new_bot_drops' end
        if table.concat(unchanged,'|') ~= baseline.persistent then
            return false, 'other_world_changes|exact_drops='..#additions
        end
        local local_player = StaticFindObject('/Script/Engine.LocalPlayer')
        for _, controller in ipairs(FindAllOf('ValPlayerController') or {}) do
            if owned(controller,world) then
                -- A dedicated host can retain an empty controller. A player
                -- connection also covers a spectator or an unspawned player.
                local player = controller.Player
                local has_player = engine_valid(player)
                local pawn = engine_valid(controller.Pawn)
                local headless_local = has_player and not pawn and engine_valid(local_player)
                    and controller:IsLocalPlayerController() == true and player:IsA(local_player)
                if pawn or (has_player and not headless_local) then
                    local kind = has_player and player:GetClass():GetFName():ToString() or 'none'
                    return false, 'player_present|player_type='..kind..'|pawn='..tostring(pawn)
                end
            end
        end
        -- Only exact death-drop actors added during this bot-only wave may
        -- retire. The next tick still has to prove the full world snapshot.
        for _, drop in ipairs(additions) do drop:K2_DestroyActor() end
        env.report('BOT_TEAM_WAVE_DROPS_RETIRED|count='..#additions)
        return true
    end
    local function missing_items(expected, actual)
        local present, missing = {}, {}
        for item in actual:gmatch('[^|]+') do present[item] = true end
        for item in expected:gmatch('[^|]+') do
            if not present[item] then missing[#missing+1] = item end
        end
        return table.concat(missing, ';'):sub(1,340)
    end
    local service = {}
    function service.hold(entry)
        local pawn = entry.pawn
        local name = pawn:GetFullName()
        if entry.training_held_actor == name then return end
        entry.training_held_actor = name
        entry.training_settle_since, entry.training_settle_reported = nil, nil
        entry.state_tree_requested = true
        pawn.bCanBeDamaged = false
        entry.controller:StopMovement()
        entry.controller:GetStateTreeComponent():StopLogic('Local training wave preparation')
        if pawn.CharacterMovement.bIsJetpackActive then
            StaticFindObject('/Script/GameplayAbilities.Default__AbilitySystemBlueprintLibrary'):
                SendGameplayEventToActor(pawn,{TagName=FName('State.Jetpacking.StopAI')},{})
        end
        pawn.CharacterMovement:SetWantsToSki(false)
        -- Polling readiness must leave gravity and native landing velocity intact.
        pawn.CharacterMovement:StopMovementImmediately()
        entry.training_held = true
    end
    function service.ready(entries)
        local blocked
        for index, entry in ipairs(entries) do
            local pawn = entry.pawn
            local movement = pawn.CharacterMovement
            local healthy = pawn:GetHealth() == pawn:GetHealthMax() and pawn:GetEnergy() >= 99
            local grounded, jetting = movement:IsMovingOnGround(), movement.bIsJetpackActive
            if not healthy or jetting or not grounded then
                blocked = blocked or index
                if not entry.training_settle_since then
                    entry.training_settle_since = os.time()
                elseif os.time()-entry.training_settle_since >= 5
                    and not entry.training_settle_reported then
                    entry.training_settle_reported = true
                    local pos, velocity = pawn:K2_GetActorLocation(), movement.Velocity
                    local spawn = entry.training_spawn
                    env.report(('BOT_TEAM_SPAWN_SETTLE|slot=%d|team=%d|grounded=%s|jetting=%s|health=%.1f|energy=%.1f'
                        ..'|spawn=%.1f,%.1f,%.1f|position=%.1f,%.1f,%.1f|velocity=%.1f,%.1f,%.1f'):
                        format(index,entry.team,tostring(grounded),tostring(jetting),pawn:GetHealth(),pawn:GetEnergy(),
                            spawn.X,spawn.Y,spawn.Z,pos.X,pos.Y,pos.Z,velocity.X,velocity.Y,velocity.Z))
                end
            end
        end
        return blocked == nil, blocked
    end
    function service.start(gm, gs, entries, wave)
        env.scope()
        local world = gm:GetWorld()
        if not baseline then
            baseline = {world=world:GetAddress(), timer=gm.MatchTimer, spawns={},
                equipment=equipment(world), persistent=persistent_gameplay(world),
                phase_remaining=gs:GetPhaseRemainingTimer()-gs:GetServerWorldTimeSeconds(),
                phase=gs.r_GameplayPhaseInfo.Phase.TagName:ToString()}
        end
        require_reset(world:GetAddress() == baseline.world and gm:GetMatchState():ToString() == 'InProgress', 'world_or_match_phase')
        require_reset(flags_home(world), 'flags_not_home')
        local reused_addresses = 0
        for index, entry in ipairs(entries) do
            local pawn = entry.pawn
            require_reset(owned(pawn,world), 'fresh_pawn_scope|slot='..index)
            -- Unreal may reuse a retired actor's address for a new pawn.
            local retired_names = old[pawn:GetAddress()]
            if retired_names then
                require_reset(not retired_names[pawn:GetFullName()], 'retired_pawn_identity|slot='..index)
                reused_addresses = reused_addresses + 1
            end
            require_reset(pawn:GetHealth() == pawn:GetHealthMax() and pawn:GetEnergy() >= 99,
                'fresh_pawn_resources|slot='..index..'|health='..pawn:GetHealth()..'/'..pawn:GetHealthMax()
                    ..'|energy='..pawn:GetEnergy())
            if not baseline.spawns[index] then
                local p, r = pawn:K2_GetActorLocation(), entry.training_facing
                baseline.spawns[index] = {at={X=p.X,Y=p.Y,Z=p.Z}, rotation={Pitch=r.Pitch,Yaw=r.Yaw,Roll=r.Roll}}
            end
        end
        -- Park collision for this game-thread operation so a fresh pawn in
        -- another slot cannot block the original, surveyed start position.
        if wave > 1 then
            signature('/Script/Engine.Actor:SetActorEnableCollision', {{'bNewActorEnableCollision','BoolProperty',0}})
            signature('/Script/Engine.Actor:K2_SetActorLocation',{{'NewLocation','StructProperty',0},{'bSweep','BoolProperty',24},
                {'SweepHitResult','StructProperty',32},{'bTeleport','BoolProperty',264},{'ReturnValue','BoolProperty',265}})
            for _, entry in ipairs(entries) do entry.pawn:SetActorEnableCollision(false) end
        end
        for index, entry in ipairs(entries) do
            local pawn = entry.pawn
            local at, rotation = baseline.spawns[index].at, baseline.spawns[index].rotation
            if wave > 1 then
                -- These positions were grounded and recorded in the fresh
                -- wave. TeleportTo's encroachment adjustment can reject them
                -- on sloped floors; restore the exact surveyed position.
                pawn:K2_SetActorLocation(at,false,{},true)
                local p = pawn:K2_GetActorLocation()
                require_reset((p.X-at.X)^2+(p.Y-at.Y)^2+(p.Z-at.Z)^2 <= 1, 'spawn_position_restore')
            end
            pawn.CharacterMovement:StopMovementImmediately()
            local v = pawn.CharacterMovement.Velocity
            require_reset(v.X*v.X+v.Y*v.Y+v.Z*v.Z <= 1, 'spawn_velocity')
            entry.controller:SetControlRotation(rotation)
        end
        if wave > 1 then
            for _, entry in ipairs(entries) do
                entry.pawn:SetActorEnableCollision(true)
                require_reset(entry.pawn:GetActorEnableCollision(), 'spawn_collision_restore')
            end
        end
        if wave > 1 then
            require_reset(equipment(world) == baseline.equipment, 'map_equipment_changed')
            require_reset(persistent_gameplay(world) == baseline.persistent, 'persistent_gameplay_changed')
            require_reset(gs.r_GameplayPhaseInfo.Phase.TagName:ToString() == baseline.phase, 'gameplay_phase_changed')
            local seen = {}
            gs.r_CurrentTeamScores:ForEach(function(_, element)
                local row = element:get()
                row.Score = 0
                require_reset(row.Score == 0, 'score_reset')
                seen[row.TeamNum] = true
            end)
            require_reset(seen[1] and seen[2], 'team_scores_missing')
            gm.MatchTimer = baseline.timer
            require_reset(math.abs(gm:GetMatchTimer()-baseline.timer) < .01, 'match_timer_reset')
            local deadline = gs:GetServerWorldTimeSeconds()+baseline.phase_remaining
            gs.r_GameplayPhaseInfo.PhaseTimeRemaining = deadline
            require_reset(math.abs(gs:GetPhaseRemainingTimer()-deadline) < .01, 'phase_timer_reset')
        end
        if env.path then
            local rows = {'bot,x_cm,y_cm,z_cm,health,max_health,energy,vx_cm_s,vy_cm_s,vz_cm_s'}
            for index, entry in ipairs(entries) do
                local pawn = entry.pawn
                local p, v = pawn:K2_GetActorLocation(), pawn.CharacterMovement.Velocity
                rows[#rows+1] = ('%d,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f'):format(
                    index,p.X,p.Y,p.Z,pawn:GetHealth(),pawn:GetHealthMax(),pawn:GetEnergy(),v.X,v.Y,v.Z)
            end
            local name = env.path..'/team-reset-'..wave
            local file = assert(io.open(name..'.tmp','w'))
            assert(file:write(table.concat(rows,'\n'),'\n'));assert(file:close())
            assert(os.rename(name..'.tmp',name..'.csv'))
        end
        gm.bPausedTimer = false
        for _, entry in ipairs(entries) do
            entry.pawn.bCanBeDamaged = true
            require_reset(entry.pawn.bCanBeDamaged == true, 'spawn_protection_not_released')
            entry.controller:StartStateTree()
            require_reset(entry.controller:GetStateTreeComponent():IsRunning(), 'fresh_brain_start')
        end
        retired, began = nil, nil
        env.report('BOT_TEAM_WAVE_RESET|'..wave..'|bots='..#entries..'|fresh_pawns=true|reused_addresses='..reused_addresses)
    end
    function service.reset(gm, gs, entries)
        env.scope()
        if not engine_valid then
            signature('/Script/Engine.KismetSystemLibrary:IsValid',{{'Object','ObjectProperty',0},{'ReturnValue','BoolProperty',8}})
            local system = StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
            local is_valid = StaticFindObject('/Script/Engine.KismetSystemLibrary:IsValid')
            engine_valid = function(actor) return valid(actor) and is_valid(system,actor)==true end
        end
        local world = gm:GetWorld()
        require_reset(baseline and world:GetAddress() == baseline.world
            and gm:GetMatchState():ToString() == 'InProgress', 'world_or_match_phase')
        if not retired then
            signature('/Script/Topaz.TopPickup_Flag:Drop', {{'bScored','BoolProperty',0},
                {'bInheritVelocity','BoolProperty',1},{'bForceReturnToStart','BoolProperty',2}})
            signature('/Script/Engine.Controller:UnPossess', {})
            signature('/Script/Engine.Actor:SetLifeSpan', {{'InLifespan','FloatProperty',0}})
            signature('/Script/Engine.Actor:K2_DestroyActor', {})
            gm.bPausedTimer = true
            retired, began, checked_persistent = {}, os.time(), nil
            drop_cleanup_attempted = false
            for _, entry in ipairs(entries) do
                local controller = entry.controller
                require_reset(owned(controller,world), 'owned_controller_missing')
                controller:StopMovement()
                local tree = controller:GetStateTreeComponent()
                if valid(tree) and tree:IsRunning() then tree:StopLogic('Local training wave reset') end
            end
            for _, flag in ipairs(FindAllOf('TopPickup_Flag') or {}) do
                if owned(flag,world) then flag:Drop(false,false,true) end
            end
            for _, entry in ipairs(entries) do
                local controller, pawn = entry.controller, entry.controller.Pawn
                retired[#retired+1] = {controller, controller.PlayerState, pawn, entry.bot}
                if owned(pawn,world) then
                    remember_retired(pawn)
                    controller:UnPossess()
                    pawn:K2_DestroyActor()
                end
                if owned(entry.bot,world) and (not valid(pawn) or entry.bot:GetAddress() ~= pawn:GetAddress()) then
                    remember_retired(entry.bot)
                    entry.bot:K2_DestroyActor()
                end
                controller:SetLifeSpan(.1)
            end
            for _, projectile in ipairs(FindAllOf('ValProjectile') or {}) do
                if owned(projectile,world) then projectile:K2_DestroyActor() end
            end
        end
        require_reset(os.time()-began < 15, 'retired_bot_or_flag_timeout')
        for _, group in ipairs(retired) do
            local controller, ps = group[1], group[2]
            if not engine_valid(controller) and engine_valid(ps) then
                require_reset(ps.bIsABot and ps.r_bPlayerBot and not engine_valid(ps.PawnPrivate)
                    and not engine_valid(ps:GetOwner()), 'detached_player_state_scope')
                ps:K2_DestroyActor()
            end
            for _, actor in pairs(group) do if engine_valid(actor) then return false end end
        end
        if not flags_home(world) then return false end
        for _, projectile in ipairs(FindAllOf('ValProjectile') or {}) do
            if owned(projectile,world) then return false end
        end
        require_reset(equipment(world) == baseline.equipment, 'map_equipment_changed')
        -- Effects such as temporary pickups can expire after the pawn and
        -- projectile are gone. Let the native world settle and only reuse an
        -- exact match to the original gameplay snapshot.
        local now = os.time()
        if now == checked_persistent then return false end
        checked_persistent = now
        local current, rows, drops = persistent_gameplay(world)
        if current ~= baseline.persistent then
            local reason = 'drop_retirement_not_confirmed'
            if not drop_cleanup_attempted then
                drop_cleanup_attempted, reason = retire_bot_drops(world,rows,drops)
                if drop_cleanup_attempted then return false end
            end
            if now-began >= 12 then
                env.report('BOT_TEAM_WAVE_WORLD_CHANGED|added='..missing_items(current,baseline.persistent)
                    ..'|removed='..missing_items(baseline.persistent,current))
                env.report('BOT_TEAM_WAVE_DROP_CLEANUP_UNVERIFIED|reason='..reason)
                require_reset(false, 'persistent_gameplay_changed')
            end
            return false
        end
        return true
    end
    return service
end
