return function(env)
    local valid, report, signature = env.valid, env.report, env.signature
    local route_factory = assert(loadfile(env.route_script))()
    local overlap = '/Script/Topaz.TopPickup_Flag:OnBeginOverlap'
    return function(gm, gs, entries)
        local world = gm:GetWorld()
        local clock = StaticFindObject("/Script/Engine.Default__GameplayStatics")
        local flags = {}
        for _, candidate in ipairs(FindAllOf('TopPickup_Flag') or {}) do
            if valid(candidate) and candidate:GetWorld():GetAddress() == world:GetAddress() then
                local team = candidate.r_TeamId
                if team == 1 or team == 2 then
                    assert(not flags[team], 'screen_duplicate_flag')
                    flags[team] = candidate
                end
            end
        end
        signature('/Script/Engine.PrimitiveComponent:GetCollisionEnabled',{{'ReturnValue','ByteProperty',0}})
        signature('/Script/Engine.PrimitiveComponent:SetCollisionEnabled',{{'NewType','ByteProperty',0}})
        signature('/Script/Engine.PrimitiveComponent:GetGenerateOverlapEvents',{{'ReturnValue','BoolProperty',0}})
        signature('/Script/Engine.PrimitiveComponent:SetGenerateOverlapEvents',{{'bInGenerateOverlapEvents','BoolProperty',0}})
        signature('/Script/Engine.PrimitiveComponent:IgnoreActorWhenMoving',{{'Actor','ObjectProperty',0},{'bShouldIgnore','BoolProperty',8}})
        signature('/Script/Valhalla.ValPickup:SetPickupActive',{{'bActive','BoolProperty',0}})
        signature(overlap,{{'OverlappedComponent','ObjectProperty',0},{'OtherActor','ObjectProperty',8},
            {'OtherComp','ObjectProperty',16},{'OtherBodyIndex','IntProperty',24},{'bFromSweep','BoolProperty',28},{'SweepResult','StructProperty',32}})
        local function disarm(flag, volume, collision)
            flag:SetPickupActive(false)
            if volume:GetCollisionEnabled() ~= collision then volume:SetCollisionEnabled(collision) end
            if not volume:GetGenerateOverlapEvents() then volume:SetGenerateOverlapEvents(true) end
            assert(not flag.r_bPickupActive and not valid(flag:GetOwner())
                and volume:GetCollisionEnabled() == collision and volume:GetGenerateOverlapEvents(),
                'screen_flag_disarm_failed')
        end
        local lanes, targets = {}, {}
        for index, entry in ipairs(entries) do
            assert((entry.team == 1 or entry.team == 2) and valid(entry.pawn), 'screen_wrong_bot')
            local other = 3-entry.team
            if not targets[other] then
                local flag = flags[other]
                assert(valid(flag) and not valid(flag:GetOwner()), 'screen_home_flag_required')
                local volume = flag.FlagInteractCollisionComp
                assert(valid(volume), 'screen_flag_volume_missing')
                local collision = volume:GetCollisionEnabled()
                assert(collision ~= 0 and volume:GetGenerateOverlapEvents(), 'screen_flag_volume_inactive')
                targets[other] = {flag=flag,volume=volume,collision=collision}
                disarm(flag,volume,collision)
            end
            lanes[entry.pawn:GetAddress()] = {index=index, target=targets[other]}
        end
        for i, entry in ipairs(entries) do
            for j = i + 1, #entries do
                local a,b = entry.pawn,entries[j].pawn
                a.CapsuleComponent:IgnoreActorWhenMoving(b,true)
                b.CapsuleComponent:IgnoreActorWhenMoving(a,true)
            end
        end
        RegisterHook(overlap,function(ctx, comp, actor)
            local ok, why = pcall(function()
                env.scope()
                local observed, component, pawn = ctx:get(),comp:get(),actor:get()
                if not valid(observed) or not valid(component) or not valid(pawn) then return end
                local lane = lanes[pawn:GetAddress()]
                if lane and lane.armed and not lane.hit and observed:GetAddress() == lane.target.flag:GetAddress()
                    and component:GetAddress() == lane.target.volume:GetAddress() then
                    local movement = pawn.CharacterMovement
                    local v = movement.Velocity
                    lane.hit = {1,.036*v.X,.036*v.Y,.036*v.Z,movement:IsSkiing() and 1 or 0}
                    local p = pawn:K2_GetActorLocation()
                    lane.hit_position = {x=p.X, y=p.Y, z=p.Z, time=clock:GetTimeSeconds(gm)}
                    report('BOT_SCREEN_CONTACT|'..lane.index)
                end
            end)
            if not ok then report('BOT_TRAIN_ERROR|'..tostring(why):sub(1,350)) end
        end)
        report('BOT_SCREEN_VOLUME_READY|lanes='..#entries)
        for index, entry in ipairs(entries) do
            local lane = lanes[entry.pawn:GetAddress()]
            local flag,volume,collision = lane.target.flag,lane.target.volume,lane.target.collision
            local lane_env = setmetatable({lane=index,team=entry.team,long_runups=true,speed_sweep=true}, {__index=env})
            lane_env.reset_participants = {entry.pawn}
            lane_env.reset_contact = function()
                lane.hit, lane.hit_position, lane.armed = nil, nil, false
                disarm(flag,volume,collision)
            end
            lane_env.contact = function(armed)
                -- Native warmup can reapply activation before the bots start moving.
                if flag.r_bPickupActive or volume:GetCollisionEnabled()~=collision or not volume:GetGenerateOverlapEvents() then
                    disarm(flag,volume,collision)
                end
                lane.armed = armed
                local hit, position = lane.hit, lane.hit_position
                if hit then
                    lane.hit, lane.hit_position, lane.armed = nil, nil, false
                end
                return hit, position
            end
            route_factory(lane_env)(gm,gs,entry.pawn,entry.controller)
        end
    end
end
