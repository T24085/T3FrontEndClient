-- Start each duel from a real pickup. Teleports only seed the isolated bot roster.
return function(env, entries, stands, world, begin)
    local valid = env.valid
    local capper = entries[env.duel_capper]
    local chaser = entries[3-env.duel_capper]
    local home, enemy = assert(stands[capper.team]), assert(stands[chaser.team])
    local dx,dy = home.X-enemy.X,home.Y-enemy.Y
    local length = math.sqrt(dx*dx+dy*dy)
    assert(length > 4500, 'field_duel_stands_too_close')
    local hx,hy = dx/length,dy/length
    local heading = math.deg(math.atan(hy,hx))
    local flag
    for _, actor in ipairs(FindAllOf('TopPickup_Flag') or {}) do
        if valid(actor) and actor:GetWorld():GetAddress() == world and actor.r_TeamId == chaser.team then flag = actor end
    end
    assert(valid(flag) and not valid(flag:GetOwner()), 'field_duel_foreign_flag')
    env.signature('/Script/Engine.Actor:K2_TeleportTo',
        {{'DestLocation','StructProperty',0},{'DestRotation','StructProperty',24},{'ReturnValue','BoolProperty',48}})
    env.signature('/Script/Engine.Controller:SetControlRotation',{{'NewRotation','StructProperty',0}})
    local function place(entry, choices, yaw)
        assert(entry.pawn:HasAuthority() and entry.pawn.PlayerState.bIsABot
            and entry.pawn:GetWorld():GetAddress() == world,'field_duel_pawn_scope')
        local controller, pawn = entry.controller, entry.pawn
        local tree = controller:GetStateTreeComponent()
        assert(valid(tree),'field_duel_missing_brain')
        controller:StopMovement()
        if tree:IsRunning() then tree:StopLogic('Local capper and chaser setup') end
        local facing = {Pitch=0,Yaw=yaw,Roll=0}
        for _, target in ipairs(choices) do
            pawn.CharacterMovement:StopMovementImmediately()
            if pawn:K2_TeleportTo(target,facing) then
                controller:SetControlRotation(facing)
                return
            end
        end
        error('field_duel_blocked_start')
    end
    local at = flag:K2_GetActorLocation()
    local half = capper.pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()
    place(capper, {{X=at.X,Y=at.Y,Z=at.Z+half+12},{X=at.X,Y=at.Y,Z=at.Z+half+110}}, heading)
    local lateral = (env.duel_lane or 1)*700
    place(chaser, {
        {X=at.X+1800*hx-lateral*hy,Y=at.Y+1800*hy+lateral*hx,Z=at.Z+320},
        {X=at.X+1450*hx+lateral*hy,Y=at.Y+1450*hy-lateral*hx,Z=at.Z+360},
        {X=at.X+1700*hx,Y=at.Y+1700*hy,Z=at.Z+440},
    }, heading+180)
    local started, end_time, outcome
    return function(now, score)
        local owner = flag:GetOwner()
        local carrying = valid(owner) and owner:GetAddress() == capper.pawn:GetAddress()
        if not started then
            if not carrying then
                if now-begin >= 10 then outcome,end_time = 'setup_failed',now end
                return false, outcome
            end
            started = now
            for _, entry in ipairs(entries) do entry.controller:StartStateTree() end
            env.report('BOT_FIELD_DUEL_PICKUP|'..env.duel_capper)
        end
        if (score[capper.team] or 0) > 0 then
            outcome = 'captured'
        elseif capper.pawn:GetHealth() <= 0 or not valid(capper.controller.Pawn)
                or capper.controller.Pawn:GetAddress() ~= capper.pawn:GetAddress() then
            outcome = 'intercepted'
        elseif not carrying then
            outcome = 'flag_lost'
        elseif now-started >= env.seconds then
            outcome = 'timeout'
        end
        if outcome then end_time = now end
        return true, outcome
    end, function()
        return ('capper,setup_seconds,duel_seconds,outcome\n%d,%.3f,%.3f,%s'):format(
            env.duel_capper,(started or end_time)-begin,started and end_time-started or 0,outcome)
    end
end
