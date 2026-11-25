local lift_profiles = {
    {4500,35}, {6500,120}, {8000,0}, {10000,0}, {8000,240}, {10000,240}
}

local function waypoints(flag, hx, hy, flank, runup, layout)
    if flank == 0 then return {} end
    local side = flank > 0 and 1 or -1
    local function relative(forward, lateral)
        return {X=flag.X+hx*forward-hy*lateral,Y=flag.Y+hy*forward+hx*lateral,Z=flag.Z}
    end
    if layout == 'wide_flank' then
        return {relative(3500,side*runup),relative(-1700,side*(runup*.65)),
                relative(-2400,side*3800)}
    elseif layout == 'back_cut' then
        return {relative(1800,side*(runup*.65)),relative(-runup,side*(runup*.55)),
                relative(-7000,side*4200),relative(-4600,side*2300)}
    end
    local points = {relative(-2500, side*5500)}
    if runup and runup > 9000 then
        points[2] = relative(-(runup+2500), side*3500)
        points[3] = relative(-runup, 0)
    elseif runup and runup > 0 then
        points[2] = relative(-runup, 0)
    elseif math.abs(flank) == 2 then
        points[2] = relative(-5500, 0)
    end
    return points
end

local function pass_axis(flag, points, hx, hy, layout)
    if not layout then return hx,hy end
    local last = points[#points]
    local x,y = flag.X-last.X,flag.Y-last.Y
    local range = math.sqrt(x*x+y*y)
    return x/range,y/range
end

local function flythrough(flag, at, velocity, hx, hy, guidance)
    local x,y=at.X-flag.X,at.Y-flag.Y
    local along=x*hx+y*hy
    local cross=-x*hy+y*hx
    local forward=velocity.X*hx+velocity.Y*hy
    local cross_speed=-velocity.X*hy+velocity.Y*hx
    local correction=math.atan(-cross-.35*cross_speed,math.max(650,-along))
    local heading=math.atan(hy,hx)+math.max(-.55,math.min(.55,correction))
    local lift=lift_profiles[guidance]
    local lead=math.min(1.25,math.max(.2,-along/math.max(900,forward)))
    local target_z=flag.Z+lift[2]
    local climbing=x*x+y*y<lift[1]^2 and at.Z+velocity.Z*lead<target_z
        and (at.Z<target_z or velocity.Z<0)
    return heading,climbing
end

local function limit_turn(heading, velocity)
    if velocity.X^2+velocity.Y^2<=900^2 then return heading end
    local travel=math.atan(velocity.Y,velocity.X)
    local change=(heading-travel+math.pi)%(2*math.pi)-math.pi
    return travel+math.max(-1.2,math.min(1.2,change))
end

local function stand_distance(at, stand)
    local dx,dy=at.X-stand.X,at.Y-stand.Y
    return math.sqrt(dx*dx+dy*dy)
end

local function sample_approach(attempt, distance, speed)
    if distance > 3000 then
        attempt.approach_entry, attempt.approach_peak = nil, nil
    elseif attempt.last_stand_distance and attempt.last_stand_distance > 3000 and distance >= 2000 then
        attempt.approach_entry, attempt.approach_peak = speed, speed
    elseif attempt.approach_entry then
        attempt.approach_peak = math.max(attempt.approach_peak, speed)
    end
    attempt.last_stand_distance = distance
end

return {waypoints=waypoints, pass_axis=pass_axis, flythrough=flythrough, limit_turn=limit_turn,
        stand_distance=stand_distance, sample_approach=sample_approach}
