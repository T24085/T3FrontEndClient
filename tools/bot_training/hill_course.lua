-- A hill course is surveyed on world-static collision before a bot can use it.
local step = 1000
local function choose(origin, floor, end_available, count, min_drop, start_floor)
    count, min_drop = count or 8, min_drop or 800
    local start = (start_floor or floor)(origin.X,origin.Y,origin.Z)
    if not start or math.abs(start-origin.Z) > 150 then return end
    local best
    for i=0,23 do
        local angle = i*math.pi/12
        local x,y = math.cos(angle),math.sin(angle)
        local height, supported = start, 0
        for segment=1,count do
            local next_height = floor(origin.X+x*step*segment, origin.Y+y*step*segment, height)
            local drop = next_height and height-next_height
            if not drop or drop > 650 or drop < -250 then break end
            if drop >= 50 then supported = supported+1 end
            height = next_height
            if segment == count and supported >= math.ceil(count*.6) and start-height >= min_drop then
                local last = {X=origin.X+x*step*count,Y=origin.Y+y*step*count,Z=height}
                local score = math.abs((start-height)-1650)
                if (not best or score < best.score) and end_available(last) then
                    best = {X=x,Y=y,yaw=i*15,last=last,drop=start-height,score=score}
                end
            end
        end
    end
    return best
end

local function survey(env, entries)
    local engine = StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
    assert(env.valid(engine),'hill_terrain_trace_unavailable')
    local trace_path = '/Script/Engine.KismetSystemLibrary:LineTraceSingleForObjects'
    env.signature(trace_path,{
        {'WorldContextObject','ObjectProperty',0},{'Start','StructProperty',8},{'End','StructProperty',32},
        {'ObjectTypes','ArrayProperty',56},{'bTraceComplex','BoolProperty',72},{'ActorsToIgnore','ArrayProperty',80},
        {'DrawDebugType','ByteProperty',96},{'OutHit','StructProperty',104},{'bIgnoreSelf','BoolProperty',336},
        {'TraceColor','StructProperty',340},{'TraceHitColor','StructProperty',356},{'DrawTime','FloatProperty',372},
        {'ReturnValue','BoolProperty',376}})
    local ignored, considered, height = {}, nil, nil
    for _, entry in ipairs(entries) do ignored[#ignored+1] = entry.pawn end
    local clear = {R=0,G=0,B=0,A=0}
    local pre, post = RegisterHook(trace_path,function() end,function(context,_,...)
        if not considered or context:get():GetAddress() ~= engine:GetAddress() then return end
        local params = {...}
        if params[1]:get():GetAddress() ~= considered:GetAddress() then return end
        local hit = params[8]:get()
        if hit.bBlockingHit and not hit.bStartPenetrating and hit.ImpactNormal.Z >= .65 then
            height = hit.ImpactPoint.Z
        end
    end)
    local function floor(x,y,z,at_feet)
        height = nil
        -- Probe the walkable height band for this step. A roof above the slope
        -- can otherwise hide the surface the native pawn is already standing on.
        local top = {X=x,Y=y,Z=z+(at_feet and 140 or 250)}
        local bottom = {X=x,Y=y,Z=z-(at_feet and 180 or 665)}
        local found = engine:LineTraceSingleForObjects(considered,top,bottom,{0},true,ignored,0,{},true,clear,clear,0)
        if found and height and height <= top.Z and height >= bottom.Z then return height end
    end
    local function floor_at_feet(x,y,z) return floor(x,y,z,true) end
    local ok, result = pcall(function()
        local courses = {}
        for index, entry in ipairs(entries) do
            considered = entry.pawn
            local origin = considered:K2_GetActorLocation()
            local half = considered.CapsuleComponent:GetScaledCapsuleHalfHeight()
            local function available(last)
                if env.hill_kind ~= 'uphill' then return true end
                for _, course in ipairs(courses) do
                    if (last.X-course.last.X)^2+(last.Y-course.last.Y)^2 < 210^2 then return false end
                end
                return true
            end
            local feet = {X=origin.X,Y=origin.Y,Z=origin.Z-half}
            local course = choose(feet,floor,available,nil,nil,floor_at_feet)
            if not course and env.hill_kind == 'recovery' then
                course = choose(feet,floor,available,4,300,floor_at_feet)
            end
            if not course then
                local initial = floor_at_feet(feet.X,feet.Y,feet.Z)
                env.report(('BOT_HILL_SURVEY|slot=%d|feet=%.1f|surface=%s'):format(index,feet.Z,tostring(initial)))
            end
            assert(course, 'hill_course_unavailable|slot='..index)
            courses[index] = course
        end
        return courses
    end)
    considered = nil
    UnregisterHook(trace_path,pre,post)
    assert(ok,result)
    return result
end

return {choose=choose,survey=survey}
