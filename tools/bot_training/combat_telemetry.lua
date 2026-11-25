-- Observe tracked projectiles in the owned practice world. Credit only
-- verified native damage. Calibration can redirect some native AI misses.
return function(env, gm, entries, clock, begin)
    local valid, report = env.valid, env.report
    local world = gm:GetWorld():GetAddress()
    local launch = '/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'
    local impact = '/Script/Valhalla.ValProjectile:OnHit'
    local aim = '/Script/Valhalla.ValAIBlueprintHelperLibrary:ShouldAimHitTarget'
    local header = 'seconds,event,shot,projectile,shooter,shooter_team,target,target_team,range_m,airborne,damage,source,aim_angle_deg,shooter_airborne'
    local rows, shots, pending, hooks, impact_stack = {header}, {}, {}, {}, {}
    local deferred, damage_epoch = {}, {}
    local sampling = false
    local active, complete, count = true, true, 0
    local function bot(pawn)
        if not valid(pawn) or pawn:GetWorld():GetAddress() ~= world then return end
        local address = pawn:GetAddress()
        for slot, entry in ipairs(entries) do
            local current = entry.controller.Pawn
            if valid(current) and current:GetAddress() == address then return slot, entry.team end
        end
    end
    local function observe(callback, ...)
        if not active then return end
        local ok, why = pcall(callback, ...)
        if not ok then
            active, complete = false, false
            report('BOT_COMBAT_OBSERVER_UNAVAILABLE|'..tostring(why):sub(1,220))
        end
    end
    local function emit(line)
        if #rows >= 10001 then active, complete = false, false; return end
        rows[#rows+1] = line
    end
    local aim_vectors = pcall(function()
        env.signature('/Script/Valhalla.ValAIController:GetAITargetedActor',{{'ReturnValue','ObjectProperty',0}})
        env.signature('/Script/Engine.Actor:GetVelocity',{{'ReturnValue','StructProperty',0}})
    end)
    local function launch_target(controller, projectile, spawn, team)
        if not aim_vectors then return end
        local pawn = controller:GetAITargetedActor()
        local target, enemy = bot(pawn)
        if not target or enemy==team then return end
        local p,v = pawn:K2_GetActorLocation(),projectile:GetVelocity()
        local x,y,z = p.X-spawn.X,p.Y-spawn.Y,p.Z-spawn.Z
        local range = math.sqrt(x*x+y*y+z*z)
        local speed = math.sqrt(v.X*v.X+v.Y*v.Y+v.Z*v.Z)
        if range<=0 or speed<=0 or range>=math.huge or speed>=math.huge then return end
        local cosine = (x*v.X+y*v.Y+z*v.Z)/(range*speed)
        if cosine~=cosine then return end
        local angle = math.deg(math.acos(math.max(-1,math.min(1,cosine))))
        return (',%d,%d,%.2f,%d,,,%.2f'):format(
            target,enemy,range/100,pawn.CharacterMovement:IsMovingOnGround() and 0 or 1,angle)
    end
    local function shot_fired(_, _, parameter)
        local projectile = parameter:get()
        if not valid(projectile) or not projectile:HasAuthority() or projectile:GetWorld():GetAddress() ~= world then return end
        local instigator = projectile.Instigator
        local shooter, team = bot(instigator)
        if not shooter then return end
        local address, name = projectile:GetAddress(), projectile:GetFullName()
        if shots[address] and shots[address].name == name then return end
        count = count+1
        local class = projectile:GetClass():GetFName():ToString():gsub('[^%w_]', '_')
        local at = projectile:K2_GetActorLocation()
        local controller = entries[shooter].controller
        local owner = instigator.PlayerState
        local airborne = instigator.CharacterMovement:IsMovingOnGround() and 0 or 1
        local shot = {id=count,name=name,class=class,shooter=shooter,team=team,x=at.X,y=at.Y,z=at.Z,hits={},contacts={},
                      shooter_airborne=airborne,
                      pawn_address=instigator:GetAddress(),controller_address=controller:GetAddress(),
                      state_address=valid(owner) and owner:GetAddress() or nil}
        shots[address] = shot
        local ok, target = pcall(launch_target,controller,projectile,at,team)
        emit(('%.3f,launch,%d,%s,%d,%d'):format(clock:GetTimeSeconds(gm)-begin,count,class,shooter,team)
            ..(ok and target or ',,,,,,,')..','..airborne)
    end
    local function tracked_actor(projectile)
        if not valid(projectile) then return end
        local address = projectile:GetAddress()
        local shot = shots[address]
        if shot and shot.name == projectile:GetFullName() then return projectile, shot, address end
    end
    local function tracked(context)
        return tracked_actor(context:get())
    end
    local function shield(pawn)
        local ok, value = pcall(function() return pawn.Attributes.Shield.CurrentValue end)
        if ok and type(value)=='number' and value>=0 and value<math.huge then return value end
    end
    local function target_state(shot, pawn, target, team, health)
        local pos = pawn:K2_GetActorLocation()
        local range = math.sqrt((pos.X-shot.x)^2+(pos.Y-shot.y)^2+(pos.Z-shot.z)^2)/100
        return {shot=shot,pawn=pawn,target=target,team=team,health=health,shield=shield(pawn),range=range,
                airborne=not pawn.CharacterMovement:IsMovingOnGround()}
    end
    local function snapshot(projectile, shot, pawn, target, team)
        if not target or team == shot.team or shot.hits[target] or not valid(pawn) or projectile.HitTargets:Contains(pawn) then return end
        if pawn.bCanBeDamaged==false then return end
        local health = pawn:GetHealth()
        if health <= 0 then return end
        return target_state(shot,pawn,target,team,health)
    end
    local function snapshot_targets(projectile, shot)
        local targets = {}
        for index, entry in ipairs(entries) do
            local hit = snapshot(projectile,shot,entry.controller.Pawn,index,entry.team)
            if hit then targets[#targets+1] = hit end
        end
        return targets
    end
    local function observed_damage(hit)
        local damage = math.max(0,hit.health-math.max(0,hit.pawn:GetHealth()))
        local remaining_shield = hit.shield and shield(hit.pawn)
        if remaining_shield then damage = damage+math.max(0,hit.shield-remaining_shield) end
        return damage
    end
    local function record_damage(shot,hit,damage,source)
        shot.hits[hit.target] = true
        local address = hit.pawn:GetAddress()
        damage_epoch[address] = (damage_epoch[address] or 0)+1
        emit(('%.3f,damage,%d,%s,%d,%d,%d,%d,%.2f,%d,%.2f,%s,,%d'):format(clock:GetTimeSeconds(gm)-begin,
            shot.id,shot.class,shot.shooter,shot.team,hit.target,hit.team,hit.range,hit.airborne and 1 or 0,
            damage,source,shot.shooter_airborne))
    end
    local function credit(projectile, shot, hit, source)
        if not hit or shot.hits[hit.target] or not valid(hit.pawn) then return end
        local damage = observed_damage(hit)
        if damage > 0 and (source=='effect_application' or projectile.HitTargets:Contains(hit.pawn)) then
            record_damage(shot,hit,damage,source)
        end
    end
    local function sample_deferred()
        local attribution = {}
        for key, candidate in pairs(deferred) do
            local shot,hit,projectile = candidate.shot,candidate.hit,candidate.projectile
            candidate.frames = candidate.frames-1
            if valid(projectile) and valid(hit.pawn) and not shot.hits[hit.target] then
                local address = hit.pawn:GetAddress()
                local age = damage_epoch[address] or 0
                if projectile.HitTargets:Contains(hit.pawn) then
                    deferred[key] = nil
                    -- Assign delayed loss only when a single original projectile accepts this
                    -- target in the sampled frame. A synchronous credited hit takes precedence.
                    local frame = attribution[address] or {accepted=0}
                    frame.accepted = frame.accepted+1
                    local damage = observed_damage(hit)
                    if damage > 0 and age==candidate.epoch then
                        frame.shot, frame.hit, frame.damage = shot,hit,damage
                    end
                    attribution[address] = frame
                elseif candidate.frames > 0 then
                    hit.health, hit.shield = hit.pawn:GetHealth(),shield(hit.pawn)
                    candidate.epoch = age
                else
                    deferred[key] = nil
                end
            else
                deferred[key] = nil
            end
        end
        for _, frame in pairs(attribution) do
            if frame.accepted==1 and frame.damage then
                record_damage(frame.shot,frame.hit,frame.damage,'native_impact')
            end
        end
    end
    local function tick_deferred()
        sampling = false
        observe(sample_deferred)
        if active and next(deferred) then
            sampling = true
            ExecuteInGameThreadAfterFrames(1,tick_deferred)
        end
    end
    local function queue_deferred(projectile,shot,targets)
        for _, hit in ipairs(targets) do
            local key = shot.id..'/'..hit.target
            if not shot.hits[hit.target] and valid(hit.pawn)
                    and not projectile.HitTargets:Contains(hit.pawn) and not deferred[key] then
                deferred[key] = {projectile=projectile,shot=shot,hit=hit,frames=16,
                                 epoch=damage_epoch[hit.pawn:GetAddress()] or 0}
            end
        end
        if not sampling and next(deferred) then
            sampling = true
            ExecuteInGameThreadAfterFrames(1,tick_deferred)
        end
    end
    local function contact(shot, pawn, source)
        local target, team = bot(pawn)
        if not target or team==shot.team or shot.contacts[target] then return end
        shot.contacts[target] = true
        local pos = pawn:K2_GetActorLocation()
        local range = math.sqrt((pos.X-shot.x)^2+(pos.Y-shot.y)^2+(pos.Z-shot.z)^2)/100
        emit(('%.3f,contact,%d,%s,%d,%d,%d,%d,%.2f,%d,,%s,,%d'):format(clock:GetTimeSeconds(gm)-begin,
            shot.id,shot.class,shot.shooter,shot.team,target,team,range,
            pawn.CharacterMovement:IsMovingOnGround() and 0 or 1,source,shot.shooter_airborne))
    end
    local function before_impact(context, _, other, _, _, hit_arg)
        local projectile, shot, address = tracked(context)
        if not projectile then return end
        local pawn = other:get()
        local hit = hit_arg and hit_arg:get()
        if hit and hit.bStartPenetrating~=true then
            if hit.bBlockingHit==true then contact(shot,pawn,'contact') end
            pending[address] = snapshot_targets(projectile,shot)
        else
            pending[address] = {snapshot(projectile,shot,pawn,bot(pawn))}
        end
    end
    local function after_impact(context)
        local projectile, shot, address = tracked(context)
        if not projectile then return end
        local targets = pending[address]
        pending[address] = nil
        if not targets then return end
        for _, hit in ipairs(targets) do credit(projectile,shot,hit,'contact') end
        queue_deferred(projectile,shot,targets)
    end
    local function install(path, before, after)
        local pre, post = RegisterHook(path, before, after)
        hooks[#hooks+1] = {path=path,pre=pre,post=post}
    end
    local function with_projectile(path, before, after)
        install(path,function(context,...)
            impact_stack[#impact_stack+1] = false
            observe(function()
                local _, shot = tracked(context)
                impact_stack[#impact_stack] = shot or false
            end)
            observe(before,context,...)
        end,function(context,...)
            observe(after,context,...)
            impact_stack[#impact_stack] = nil
        end)
    end
    local function observe_explosion(method, source, stopped)
        local path = '/Script/Valhalla.ValProjectile:'..method
        local fn = StaticFindObject(path)
        assert(valid(fn) and fn:GetFullName() == 'Function '..path, 'projectile_event_missing='..method)
        local snapshots = {}
        if stopped then env.signature(path,{{'HitResult','StructProperty',0}}) end
        with_projectile(path,function(context, hit_arg)
            observe(function()
                local projectile, shot, address = tracked(context)
                if not projectile then return end
                if stopped then
                    local hit = hit_arg:get()
                    if type(hit)=='userdata' and hit.bBlockingHit==true and hit.bStartPenetrating==false then
                        local weak = hit.Component
                        if weak and weak:type()=='FWeakObjectPtr' then
                            local component = weak:Get()
                            if valid(component) then contact(shot,component:GetOwner(),source) end
                        end
                    end
                end
                snapshots[address] = snapshot_targets(projectile,shot)
            end)
        end,function(context)
            observe(function()
                local projectile, shot, address = tracked(context)
                if not projectile then return end
                local targets = snapshots[address]
                snapshots[address] = nil
                for _, hit in ipairs(targets or {}) do credit(projectile,shot,hit,source) end
                if targets then queue_deferred(projectile,shot,targets) end
            end)
        end)
    end
    local ready, why = pcall(function()
        env.signature(launch,{{'Projectile','ObjectProperty',0},{'Transform','StructProperty',16},{'ReturnValue','ObjectProperty',112}})
        env.signature(impact,{{'HitComp','ObjectProperty',0},{'OtherActor','ObjectProperty',8},
            {'OtherComp','ObjectProperty',16},{'NormalImpulse','StructProperty',24},{'Hit','StructProperty',48}})
        install(launch,function() end,function(...) observe(shot_fired,...) end)
        with_projectile(impact,before_impact,after_impact)
        observe_explosion('OnProjectileStopped','projectile_stop',true)
        observe_explosion('ServerProcessPredictedHits','predicted_hit')
    end)
    if not ready then
        active, complete = false, false
        report('BOT_COMBAT_OBSERVER_UNAVAILABLE|'..tostring(why):sub(1,220))
    end
    local effect_active = true
    if ready and env.combat_effects_script then
        local function unavailable(reason)
            effect_active = false
            report('BOT_COMBAT_EFFECT_UNAVAILABLE|'..tostring(reason):sub(1,180))
        end
        local function before_effect(asc, spec, read_effect)
            if not active or not effect_active or not valid(asc) then return end
            local ok, frame = pcall(function()
                for target, entry in ipairs(entries) do
                    local pawn = entry.controller.Pawn
                    local owned_asc = valid(pawn) and pawn.AbilitySystemComponent or nil
                    if valid(owned_asc) and owned_asc:GetAddress()==asc:GetAddress() then
                        local context = read_effect(spec)
                        if not context then return end
                        local projectile, shot = tracked_actor(context.causer)
                        if not shot then projectile, shot = tracked_actor(context.source) end
                        shot = shot or impact_stack[#impact_stack]
                        if not shot or shot.team==entry.team or shot.hits[target] then return end
                        if not valid(context.instigator) then return end
                        local id = context.instigator:GetAddress()
                        if id~=shot.pawn_address and id~=shot.controller_address and id~=shot.state_address then return end
                        if not projectile and (not valid(context.causer) or context.causer:GetAddress()~=shot.pawn_address) then return end
                        return target_state(shot,pawn,target,entry.team,pawn:GetHealth())
                    end
                end
            end)
            if ok then return frame end
            unavailable(frame)
        end
        local function after_effect(frame)
            if active and effect_active then observe(credit,nil,frame.shot,frame,'effect_application') end
        end
        local function before_direct(source,pawn)
            if not active or not effect_active or not valid(source) then return end
            local _, shot = tracked_actor(source)
            if not shot then
                local enclosing = impact_stack[#impact_stack]
                if enclosing and source:GetAddress()==enclosing.pawn_address then shot = enclosing end
            end
            local target, team = bot(pawn)
            if not shot or not target or team==shot.team or shot.hits[target] then return end
            return target_state(shot,pawn,target,team,pawn:GetHealth())
        end
        local enabled, reason = pcall(function()
            assert(loadfile(env.combat_effects_script))()(env,install,before_effect,after_effect,before_direct,unavailable)
        end)
        if not enabled then
            unavailable(reason)
        end
    end
    local aim_active, aiming, aim_carry = true, {}, {}
    local plan = env.aim_boosts or {}
    local aim_boosts = {plan[1] or 0, plan[2] or 0}
    local aims_ready, reason = pcall(function()
        env.signature(aim,{{'Controller','ObjectProperty',0},{'FireMode','StructProperty',8},
            {'ReturnValue','BoolProperty',16}})
        install(aim,function()end,function(_,result,controller_arg)
            if not active or not aim_active then return end
            local ok, err = pcall(function()
                local controller = controller_arg:get()
                if not valid(controller) then return end
                local shooter, team = bot(controller.Pawn)
                if not shooter then return end
                local intended = result:get()
                assert(type(intended)=='boolean','aim_native_boolean_required')
                local counts = aiming[shooter] or {team=team, decisions=0, aimed=0, adjusted=0}
                counts.decisions = counts.decisions+1
                if intended then counts.aimed = counts.aimed+1 end
                local boost = aim_boosts[team]
                if not intended and (boost==10 or boost==20) then
                    local carry = (aim_carry[team] or 0)+boost
                    if carry >= 100 then
                        result:set(true)
                        assert(result:get()==true,'aim_adjustment_readback_required')
                        counts.adjusted = counts.adjusted+1
                        carry = carry-100
                    end
                    aim_carry[team] = carry
                end
                aiming[shooter] = counts
            end)
            if not ok then
                aim_active = false
                report('BOT_AIM_OBSERVER_UNAVAILABLE|'..tostring(err):sub(1,180))
            end
        end)
    end)
    if not aims_ready then report('BOT_AIM_OBSERVER_UNAVAILABLE|'..tostring(reason):sub(1,180)) end
    return function()
        active = false
        for _, hook in ipairs(hooks) do
            local stop, error_text = pcall(UnregisterHook,hook.path,hook.pre,hook.post)
            if not stop then
                complete = false
                report('BOT_COMBAT_OBSERVER_CLEANUP_FAILED|'..tostring(error_text):sub(1,220))
            end
        end
        local aim_rows = {'bot,team,decisions,aimed,adjusted'}
        if aim_active and aims_ready then
            for slot=1,#entries do
                local sample = aiming[slot]
                if sample then
                    aim_rows[#aim_rows+1] = ('%d,%d,%d,%d,%d'):format(slot,sample.team,sample.decisions,sample.aimed,sample.adjusted)
                end
            end
        end
        return table.concat(rows,'\n'), complete and effect_active, table.concat(aim_rows,'\n'), aim_boosts
    end
end
