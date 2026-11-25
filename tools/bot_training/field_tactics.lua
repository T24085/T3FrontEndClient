-- Share sightings within a team and give the home stand, chase and cutoff distinct assignments.
return function(env, distance)
    env.signature('/Script/Engine.Controller:LineOfSightTo',{
        {'Other','ObjectProperty',0},{'ViewPoint','StructProperty',8},
        {'bAlternateChecks','BoolProperty',32},{'ReturnValue','BoolProperty',33}})
    local memory = {{}, {}}
    local zero = {X=0,Y=0,Z=0}
    local function snapshot(groups, carriers, stands, now)
        local intel, visible, jobs = {{}, {}}, {}, {}
        for team=1,2 do
            local team_memory = memory[team]
            for _, ally in ipairs(groups[team]) do
                local nearby
                for _, enemy in ipairs(ally.index and groups[3-team] or {}) do
                    local range = distance(ally.pos,enemy.pos)
                    if range <= 9000 and ally.controller:LineOfSightTo(enemy.pawn,zero,false) then
                        local id = enemy.pawn:GetAddress()
                        local v = enemy.pawn.CharacterMovement.Velocity
                        team_memory[id] = {id=id,pos=enemy.pos,v={X=v.X,Y=v.Y,Z=v.Z},seen=now}
                        nearby = math.min(nearby or math.huge,range)
                    end
                end
                if ally.index then visible[ally.index] = nearby end
            end
            for id, sighting in pairs(team_memory) do
                if now-sighting.seen <= 3.5 then
                    intel[team][id] = sighting
                else
                    team_memory[id] = nil
                end
            end
            local owner = carriers[team]
            local carrier = owner and intel[team][owner:GetAddress()]
            if carrier then
                local defenders = {}
                for _, ally in ipairs(groups[team]) do
                    if ally.role == 'Light defense' or ally.role == 'Medium defense' then
                        defenders[#defenders+1] = ally
                    end
                end
                table.sort(defenders,function(a,b)
                    local da,db = distance(a.pos,carrier.pos),distance(b.pos,carrier.pos)
                    return da == db and a.index < b.index or da < db
                end)
                if defenders[1] then jobs[defenders[1].index] = {kind='chase',sighting=carrier} end
                if defenders[2] and stands[3-team] then
                    local home = stands[3-team]
                    local v = carrier.v
                    local speed = math.sqrt(v.X*v.X+v.Y*v.Y)
                    local advance = math.min(.24,3800/math.max(500,distance(carrier.pos,home)))
                    local cutoff = {X=carrier.pos.X+(home.X-carrier.pos.X)*advance,
                                    Y=carrier.pos.Y+(home.Y-carrier.pos.Y)*advance,
                                    Z=carrier.pos.Z+(home.Z-carrier.pos.Z)*advance}
                    if now-carrier.seen < .5 and speed >= 1000 then
                        cutoff.X, cutoff.Y = (cutoff.X+carrier.pos.X+v.X)/2,(cutoff.Y+carrier.pos.Y+v.Y)/2
                    end
                    jobs[defenders[2].index] = {kind='cutoff',target=cutoff}
                end
            end
        end
        return intel, visible, jobs
    end
    return snapshot
end
