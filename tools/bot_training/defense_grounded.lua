return function(env, stand, defenders, hx, hy)
    local valid = env.valid
    local home = stand:K2_GetActorLocation()
    local trace = StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
    assert(valid(trace), 'training_defender_trace_unavailable')
    local trace_path = '/Script/Engine.KismetSystemLibrary:LineTraceSingleForObjects'
    env.signature(trace_path,{
        {'WorldContextObject','ObjectProperty',0},{'Start','StructProperty',8},{'End','StructProperty',32},
        {'ObjectTypes','ArrayProperty',56},{'bTraceComplex','BoolProperty',72},{'ActorsToIgnore','ArrayProperty',80},
        {'DrawDebugType','ByteProperty',96},{'OutHit','StructProperty',104},{'bIgnoreSelf','BoolProperty',336},
        {'TraceColor','StructProperty',340},{'TraceHitColor','StructProperty',356},{'DrawTime','FloatProperty',372},
        {'ReturnValue','BoolProperty',376}})
    env.signature('/Script/AIModule.AIController:MoveToLocation',{
        {'Dest','StructProperty',0},{'AcceptanceRadius','FloatProperty',24},{'bStopOnOverlap','BoolProperty',28},
        {'bUsePathfinding','BoolProperty',29},{'bProjectDestinationToNavigation','BoolProperty',30},
        {'bCanStrafe','BoolProperty',31},{'FilterClass','ClassProperty',32},{'bAllowPartialPath','BoolProperty',40},
        {'ReturnValue','ByteProperty',41}})
    env.signature('/Script/Engine.Controller:LineOfSightTo',{
        {'Other','ObjectProperty',0},{'ViewPoint','StructProperty',8},
        {'bAlternateChecks','BoolProperty',32},{'ReturnValue','BoolProperty',33}})
    if env.body_block then
        env.signature('/Script/Engine.PrimitiveComponent:GetCollisionObjectType',{{'ReturnValue','ByteProperty',0}})
        env.signature('/Script/Engine.PrimitiveComponent:GetCollisionResponseToChannel',{
            {'Channel','ByteProperty',0},{'ReturnValue','ByteProperty',1}})
        env.signature('/Script/Engine.PrimitiveComponent:SetCollisionResponseToChannel',{
            {'Channel','ByteProperty',0},{'NewResponse','ByteProperty',1}})
        env.signature('/Script/Engine.Pawn:AddMovementInput',{
            {'WorldDirection','StructProperty',0},{'ScaleValue','FloatProperty',24},{'bForce','BoolProperty',28}})
    end

    local roles = {
        {controller=defenders[1], name='heavy_on_flag', lateral=-220},
        {controller=defenders[2], name='light_defense', lateral=220},
    }
    -- Pursuit trigger, Light combat handoff range, Heavy combat handoff range, lead time.
    local profiles = {
        {5000,2500,2500,.45},
        {8500,2500,2500,.45},
        {6500,1200,2500,.45},
        {6500,4000,2500,.45},
        {6500,2500,4000,.45},
        {8500,1600,4000,.85},
        {8500,3500,4000,.15},
        {6500,1600,1200,.85},
    }
    local active = profiles[1]
    local combat_used = false
    local zero = {X=0,Y=0,Z=0}
    local clear = {R=0,G=0,B=0,A=0}
    local offsets = {{0,1},{100,1},{-100,1},{0,.55},{100,.55},{-100,.55},
        {200,1},{-200,1},{0,1.5},{350,1},{-350,1},{500,1}}
    local function distance(a, b)
        return math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2+(a.Z-b.Z)^2)
    end
    local function alive(pawn)
        return valid(pawn) and pawn:GetHealth() > 0
    end
    local function set_combat(role, enabled)
        if role.combat == enabled then return end
        local tree = role.controller:GetStateTreeComponent()
        if not valid(tree) then return end
        if enabled then
            combat_used = true
            role.controller:StopMovement()
            if not tree:IsRunning() then role.controller:StartStateTree() end
        elseif tree:IsRunning() then
            tree:StopLogic('Local defense positioning')
            role.controller:StopMovement()
        end
        role.combat = enabled
    end
    local function floor_at(pawn, capper, top, bottom)
        local impact_z
        local pre, post = RegisterHook(trace_path,function() end,function(context, _, ...)
            local params = {...}
            if context:get():GetAddress() ~= trace:GetAddress()
                or params[1]:get():GetAddress() ~= pawn:GetAddress() then return end
            local hit = params[8]:get()
            local impact, normal = hit.ImpactPoint, hit.ImpactNormal
            if hit.bBlockingHit and not hit.bStartPenetrating and normal.Z >= .65
                and impact.Z >= bottom.Z and impact.Z <= top.Z then
                impact_z = impact.Z
            end
        end)
        local ok, found = pcall(function()
            return trace:LineTraceSingleForObjects(pawn,top,bottom,{0},true,{stand,capper,pawn},
                0,{},true,clear,clear,0)
        end)
        UnregisterHook(trace_path,pre,post)
        assert(ok,found)
        if found then return impact_z end
    end
    local function place(role, capper)
        local pawn = role.controller.Pawn
        local half = pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()
        role.combat = nil
        set_combat(role,false)
        for _, offset in ipairs(offsets) do
            local forward, side = offset[1], role.lateral*offset[2]
            local x = home.X + hx*forward - hy*side
            local y = home.Y + hy*forward + hx*side
            local top = {X=x,Y=y,Z=home.Z+350}
            local bottom = {X=x,Y=y,Z=home.Z-850}
            local floor = floor_at(pawn,capper,top,bottom)
            if floor then
                local target = {X=x,Y=y,Z=floor+half+8}
                pawn.CharacterMovement:StopMovementImmediately()
                if pawn:K2_TeleportTo(target,{Pitch=0,Yaw=math.deg(math.atan(hy,hx)),Roll=0}) then
                    role.anchor = target
                    role.pawn = pawn:GetAddress()
                    env.report(('BOT_DEFENSE_ANCHOR|%s|%.1f|%.1f|%.1f'):format(role.name,x,y,floor))
                    return
                end
            end
        end
        -- Native player starts are the fallback when the stand has no usable
        -- trace hit. Grounded readiness still applies to the placed pawn.
        local start, nearest
        for _, actor in ipairs(FindAllOf('TopPlayerStart') or {}) do
            if actor.TeamNumber == 2 and actor:GetWorld():GetAddress() == stand:GetWorld():GetAddress() then
                local point = actor:K2_GetActorLocation()
                local range = distance(point,home)
                if range < 1800 and (not nearest or range < nearest)
                    and (not roles[1].anchor or role == roles[1] or distance(point,roles[1].anchor) > 140) then
                    start, nearest = point, range
                end
            end
        end
        assert(start, 'training_defender_floor_missing='..role.name)
        pawn.CharacterMovement:StopMovementImmediately()
        local target = {X=start.X,Y=start.Y,Z=start.Z+30}
        assert(pawn:K2_TeleportTo(target,{Pitch=0,Yaw=math.deg(math.atan(hy,hx)),Roll=0}),
            'training_defender_spawn_placement_failed='..role.name)
        role.anchor, role.pawn = target, pawn:GetAddress()
        env.report(('BOT_DEFENSE_ANCHOR|%s|native_spawn|%.1f|%.1f|%.1f'):format(role.name,start.X,start.Y,start.Z))
    end
    local function move(role, target, radius)
        role.controller:MoveToLocation(target,radius,false,true,true,false,nil,true)
    end
    local function enable_block(heavy, capper)
        local heavy_capsule, light_capsule = heavy.CapsuleComponent, capper.CapsuleComponent
        for _, pair in ipairs({{heavy_capsule,light_capsule},{light_capsule,heavy_capsule}}) do
            local channel = pair[2]:GetCollisionObjectType()
            if pair[1]:GetCollisionResponseToChannel(channel) ~= 2 then
                pair[1]:SetCollisionResponseToChannel(channel,2)
            end
            assert(pair[1]:GetCollisionResponseToChannel(channel) == 2,'training_body_block_response_failed')
        end
        env.report('BOT_HEAVY_BODY_BLOCK_COLLISION|mutual=block')
    end
    local function block_lane(role, capper, carrying)
        local at = capper:K2_GetActorLocation()
        local dx, dy = at.X-home.X,at.Y-home.Y
        local range = math.sqrt(dx*dx+dy*dy)
        if carrying or range < 60 or range > 2300 or math.abs(at.Z-home.Z)>550 then return end
        local pawn = role.controller.Pawn
        local loc = pawn:K2_GetActorLocation()
        if not pawn.CharacterMovement:IsMovingOnGround() or distance(loc,home)>850 then return end
        local aim_x, aim_y = home.X+dx/range*170,home.Y+dy/range*170
        return aim_x-loc.X,aim_y-loc.Y
    end
    local prepared
    local last, health, damage, near_flag, near_carrier, red_score, hof_alive, ld_alive
    return {
        configure=function(profile)
            active = assert(profiles[profile], 'training_invalid_defense_profile')
            env.report('BOT_DEFENSE_PROFILE|'..profile..'|'..table.concat(active,','))
        end,
        quiesce=function()
            for _, role in ipairs(roles) do
                set_combat(role,false)
                role.controller:StopMovement()
            end
            return not combat_used
        end,
        ready=function(capper, now)
            for _, role in ipairs(roles) do
                if not alive(role.controller.Pawn) then return false end
            end
            if not prepared then
                roles[1].anchor, roles[2].anchor = nil, nil
                for _, role in ipairs(roles) do place(role,capper) end
                if env.body_block then enable_block(roles[1].controller.Pawn,capper) end
                prepared = now
                return false
            end
            local both_grounded = true
            for _, role in ipairs(roles) do
                local pawn = role.controller.Pawn
                local movement = pawn.CharacterMovement
                both_grounded = both_grounded and movement:IsMovingOnGround()
                    and distance(pawn:K2_GetActorLocation(),role.anchor) < 200
                if env.verify_reuse and both_grounded then
                    local speed = movement.Velocity
                    both_grounded = speed.X^2+speed.Y^2+speed.Z^2 <= 900
                end
            end
            assert(both_grounded or now-prepared < 4, env.verify_reuse
                and 'training_reuse_unverified|defender_settle' or 'training_defender_settle_failed')
            return both_grounded
        end,
        reset=function(capper, now, score)
            prepared = nil
            last, health, damage, near_flag, near_carrier, red_score = now,capper:GetHealth(),0,0,0,score
            hof_alive, ld_alive = 0,0
        end,
        tick=function(capper, carrying, now)
            local heavy = roles[1]
            local x, y
            if env.body_block and alive(heavy.controller.Pawn) then
                x, y = block_lane(heavy,capper,carrying)
                if x then
                    set_combat(heavy,false)
                    local range = math.sqrt(x*x+y*y)
                    if range > 30 then
                        heavy.controller.Pawn:AddMovementInput({X=x/range,Y=y/range,Z=0},math.min(range/120,1),true)
                    end
                    if not heavy.blocking then env.report('BOT_HEAVY_BODY_BLOCK_LANE') end
                end
                heavy.blocking = x ~= nil
            end
            if now-last < .25 then return end
            local dt = now-last
            last = now
            local current = capper:GetHealth()
            damage = damage+math.max(0,health-current)
            health = current
            local at = capper:K2_GetActorLocation()
            for i, role in ipairs(roles) do
                local pawn = role.controller.Pawn
                if alive(pawn) then
                    if role.pawn ~= pawn:GetAddress() then
                        role.pawn, role.combat = pawn:GetAddress(), nil
                    end
                    local loc = pawn:K2_GetActorLocation()
                    local to_flag, to_capper = distance(loc,home), distance(loc,at)
                    local pursuing = i == 2 and (carrying or distance(at,home) < active[1])
                    local combat_range = i == 1 and active[3] or active[2]
                    local blocking = i == 1 and x ~= nil
                    local can_fight = not blocking and (pursuing or to_flag < 1200) and to_capper < combat_range
                        and role.controller:LineOfSightTo(capper,zero,false)
                    set_combat(role,can_fight)
                    if i == 1 then
                        hof_alive = hof_alive+dt
                        if to_flag < 1800 then near_flag = near_flag+dt end
                    else
                        ld_alive = ld_alive+dt
                        if carrying and to_capper < 2200 then near_carrier = near_carrier+dt end
                    end
                    if not can_fight and not blocking then
                        if pursuing then
                            local velocity = capper.CharacterMovement.Velocity
                            move(role,{X=at.X+velocity.X*active[4],Y=at.Y+velocity.Y*active[4],Z=at.Z},400)
                        elseif distance(loc,role.anchor) > 275 then
                            move(role,role.anchor,120)
                        end
                    end
                end
            end
        end,
        finish=function(capper, died, score)
            local current = died and 0 or capper:GetHealth()
            return table.concat({died and 1 or 0,damage+math.max(0,health-current),
                near_flag,near_carrier,score-red_score,hof_alive,ld_alive},',')
        end
    }
end
