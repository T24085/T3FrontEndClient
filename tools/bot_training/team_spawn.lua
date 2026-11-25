-- Select candidates around the chosen native team starts. The engine still
-- rejects obstructed capsules and the wave waits for every pawn to land.
local offsets = {
    {0,0,100}, {0,0,225},
    {0,250,160}, {0,-250,160}, {-250,0,160}, {250,0,160},
    {250,250,180}, {250,-250,180}, {-250,250,180}, {-250,-250,180},
    {0,450,225}, {0,-450,225}, {-450,0,225}, {450,0,225},
    {450,450,300}, {450,-450,300}, {-450,450,300}, {-450,-450,300},
}

return function(start, ordinal, start_count, attempt)
    local at = start:K2_GetActorLocation()
    local yaw = math.rad(start:K2_GetActorRotation().Yaw)
    local forward, right, lift, fallback
    local pass = math.floor(attempt/start_count)
    if pass == 0 then
        local row = math.floor(ordinal/start_count)
        forward, right, lift = 600*row, 0, row > 0 and 1000 or 0
    else
        fallback = (pass-1)%#offsets+1
        forward, right, lift = table.unpack(offsets[fallback])
    end
    local dx, dy = math.cos(yaw), math.sin(yaw)
    return {X=at.X+dx*forward-dy*right,Y=at.Y+dy*forward+dx*right,Z=at.Z+lift}, fallback
end
