-- Steer long trips with skis and jets, then hand close movement and combat back to the native bot.
return function(env)
    local valid = env.valid
    local geometry = assert(loadfile(env.route_geometry))()
    local events = StaticFindObject('/Script/GameplayAbilities.Default__AbilitySystemBlueprintLibrary')
    local jet_slot = {TagName=FName('EquipSlot.Jetpack')}
    local stop_tag = {TagName=FName('State.Jetpacking.StopAI')}
    env.signature('/Script/AIModule.BrainComponent:StopLogic',{{'Reason','StrProperty',0}})
    env.signature('/Script/Engine.Pawn:AddMovementInput',{
        {'WorldDirection','StructProperty',0},{'ScaleValue','FloatProperty',24},{'bForce','BoolProperty',28}})
    env.signature('/Script/Valhalla.ValCharacterMovementComponent:SetWantsToSki',{{'bEnabled','BoolProperty',0}})
    env.signature('/Script/GameplayAbilities.AbilitySystemComponent:TryActivateAbility',{
        {'AbilityToActivate','StructProperty',0},{'bAllowRemoteActivation','BoolProperty',4},{'ReturnValue','BoolProperty',5}})
    env.signature('/Script/GameplayAbilities.AbilitySystemBlueprintLibrary:SendGameplayEventToActor',{
        {'Actor','ObjectProperty',0},{'EventTag','StructProperty',8},{'Payload','StructProperty',16}})

    local roles, assists = {}, {}
    local function native_combat(role, allowed)
        if allowed and not role.tree:IsRunning() then
            role.controller:StartStateTree()
        elseif not allowed and role.tree:IsRunning() then
            role.tree:StopLogic('Local role travel')
        end
    end
    local function stop_jet(role)
        if role.jetting then
            events:SendGameplayEventToActor(role.pawn,stop_tag,{})
            role.jetting = false
        end
    end
    local function clear_assist(index)
        local assist = assists[index]
        assists[index] = nil
        if not assist or not valid(assist.pawn) or not valid(assist.controller.Pawn)
                or assist.controller.Pawn:GetAddress() ~= assist.pawn_id then return end
        stop_jet(assist)
        if assist.ski then assist.pawn.CharacterMovement:SetWantsToSki(false) end
    end
    local function assist_open_travel(index,entry,pawn,enabled)
        if not enabled or (roles[index] and roles[index].direct) then
            clear_assist(index)
            return
        end
        local current = assists[index]
        if not current or current.pawn_id ~= pawn:GetAddress() then
            clear_assist(index)
            assists[index] = {pawn=pawn,pawn_id=pawn:GetAddress(),controller=entry.controller,
                              jet=pawn:GetEquippedAbility(jet_slot,false),next_jet=0}
        end
    end
    local function clear(index)
        local role = roles[index]
        roles[index] = nil
        if not role or not role.direct or not valid(role.pawn) then return end
        stop_jet(role)
        role.pawn.CharacterMovement:SetWantsToSki(false)
        if valid(role.controller.Pawn) and role.controller.Pawn:GetAddress() == role.pawn:GetAddress()
                and valid(role.tree) and not role.tree:IsRunning() then
            role.controller:StartStateTree()
        end
    end
    local function request(index, entry, pawn, at, target, radius, now, flight, engagement)
        local role = roles[index]
        if not role or role.pawn_id ~= pawn:GetAddress() then
            clear(index)
            role = {pawn=pawn, pawn_id=pawn:GetAddress(), controller=entry.controller,
                    x=at.X, y=at.Y, checked=now}
            local selected = not env.adaptive_team or env.adaptive_team == entry.team
            role.strict, role.adaptive = selected and env.strict_movement, selected and env.adaptive_movement
            roles[index] = role
        end
        local strict, adaptive = role.strict, role.adaptive
        role.target, role.radius = target, radius
        role.engagement = engagement
        role.jet_period = flight and flight.jet_period or 2.4
        role.jet_pulse = flight and flight.jet_pulse or .65
        local take_over = strict and geometry.stand_distance(at,target) > math.max(1800, radius+450)
        if adaptive and engagement then
            take_over = take_over or geometry.stand_distance(at,target) > radius
        end
        if not strict and now-role.checked >= 4 then
            local moved = (at.X-role.x)^2 + (at.Y-role.y)^2
            role.x, role.y, role.checked = at.X,at.Y,now
            take_over = moved < 700^2 and geometry.stand_distance(at,target) > 2600
        end
        if not role.direct and take_over then
            local tree, jet = entry.controller:GetStateTreeComponent(), pawn:GetEquippedAbility(jet_slot,false)
            if valid(tree) and jet.Handle >= 0 then
                clear_assist(index)
                entry.controller:StopMovement()
                role.tree, role.jet, role.direct = tree,jet,now
                native_combat(role, adaptive and engagement ~= nil)
                local label = strict and 'BOT_ROLE_SKI_JET' or 'BOT_ROLE_TRAVEL_FALLBACK'
                env.report(('%s|%d'):format(label,index))
            end
        end
        if adaptive and role.direct then native_combat(role, engagement ~= nil) end
        return role.direct ~= nil
    end
    local function steer(now)
        for index, role in pairs(roles) do
            if role.direct then
                local pawn = role.controller.Pawn
                if not valid(pawn) or pawn:GetAddress() ~= role.pawn_id or pawn:GetHealth() <= 0 then
                    clear(index)
                else
                    local at, movement = pawn:K2_GetActorLocation(), pawn.CharacterMovement
                    local target = role.target
                    local x,y = target.X-at.X,target.Y-at.Y
                    local range = math.sqrt(x*x+y*y)
                    if range < role.radius then
                        clear(index)
                    else
                        local strict, adaptive = role.strict, role.adaptive
                        local v = movement.Velocity
                        local desired = math.atan(y,x)
                        local engagement = role.engagement
                        if adaptive and engagement and engagement.evade and range > 1400 then
                            local direction = (math.floor((now-role.direct)/1.15)+index)%2 == 0 and 1 or -1
                            desired = desired + direction*.27
                        end
                        local heading = geometry.limit_turn(desired,v)
                        local phase = (now-role.direct)%role.jet_period
                        local slow = v.X*v.X+v.Y*v.Y < 1300^2
                        local rise = range > 1800 and phase < role.jet_pulse and (slow or target.Z > at.Z+300)
                        if strict then
                            local grounded = movement:IsMovingOnGround()
                            local long_trip = range > math.max(role.radius+450, 2000)
                            rise = long_trip and phase < math.max(.85,role.jet_pulse)
                                and (role.jetting or grounded or v.Z < 250 or target.Z > at.Z+300)
                        end
                        local energy = pawn:GetEnergy()
                        if adaptive then
                            local grounded = movement:IsMovingOnGround()
                            local climbing = target.Z > at.Z+280
                            local learned = env.flight_transfer or {}
                            local profile = (energy < 48 and learned.recovery) or (climbing and learned.uphill) or learned.straight
                            local period = profile and profile.period or role.jet_period
                            local pulse = profile and profile.pulse or role.jet_pulse
                            phase = (now-role.direct)%period
                            pulse = math.min(1.10, math.max(.40,pulse))
                            local air_turn = engagement and v.Z < -150 and range > 2000
                            local reserve = energy >= (role.jetting and 10 or (env.jet_reserve or 26))
                            rise = reserve and phase < pulse and (role.jetting or climbing or air_turn or (grounded and slow))
                        end
                        local ski = strict or range > 2300
                        if ski ~= role.ski or (adaptive and ski and not movement.bWantsToSki) then
                            movement:SetWantsToSki(ski)
                            role.ski = ski
                        end
                        if rise and not role.jetting and energy >= 16 then
                            role.jetting = pawn.AbilitySystemComponent:TryActivateAbility(role.jet,false)
                        elseif not rise then
                            stop_jet(role)
                        end
                        pawn:AddMovementInput({X=math.cos(heading),Y=math.sin(heading),Z=0},1,true)
                    end
                end
            end
        end
        for index, assist in pairs(assists) do
            local pawn = assist.controller.Pawn
            if not valid(pawn) or pawn:GetAddress() ~= assist.pawn_id or pawn:GetHealth() <= 0 then
                clear_assist(index)
            else
                local movement = pawn.CharacterMovement
                local velocity = movement.Velocity
                local speed = velocity.X*velocity.X+velocity.Y*velocity.Y
                if speed >= 85^2 and not movement.bWantsToSki then
                    movement:SetWantsToSki(true)
                    assist.ski = true
                elseif speed < 85^2 and assist.ski and movement:IsMovingOnGround() then
                    movement:SetWantsToSki(false)
                    assist.ski = false
                end
                local sluggish = speed >= 85^2 and speed < 825^2 and movement:IsMovingOnGround()
                assist.slow_since = sluggish and (assist.slow_since or now) or nil
                if assist.jetting and now >= assist.jet_end then
                    stop_jet(assist)
                elseif not assist.jetting and assist.slow_since and now-assist.slow_since >= .65
                        and now >= assist.next_jet and assist.jet.Handle >= 0 and not movement.bIsJetpackActive
                        and pawn:GetEnergy() >= (env.jet_reserve or 26) then
                    assist.jetting = pawn.AbilitySystemComponent:TryActivateAbility(assist.jet,false)
                    assist.jet_end, assist.next_jet = now+.5,now+2.3
                end
            end
        end
    end
    local function finish()
        for index in pairs(roles) do clear(index) end
        for index in pairs(assists) do clear_assist(index) end
    end
    return request, steer, clear, finish, assist_open_travel
end
