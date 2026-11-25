return function(env, stand, defenders)
    local valid = env.valid
    local home = stand:K2_GetActorLocation()
    local function distance(a, b)
        return math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2+(a.Z-b.Z)^2)
    end
    local function move(controller, destination, radius)
        controller:MoveToLocation(destination,radius,false,true,true,false,nil,true)
    end
    local function alive(pawn)
        return valid(pawn) and pawn:GetHealth() > 0
    end
    local function position(controller, dx, dy)
        local pawn = controller.Pawn
        controller:StopMovement()
        pawn.CharacterMovement:StopMovementImmediately()
        local z = home.Z+pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()+15
        local target = {X=home.X+dx,Y=home.Y+dy,Z=z}
        assert(pawn:K2_TeleportTo(target,{Pitch=0,Yaw=0,Roll=0}),'training_defender_reset_failed')
    end
    env.signature('/Script/AIModule.AIController:MoveToLocation',{
        {'Dest','StructProperty',0},{'AcceptanceRadius','FloatProperty',24},{'bStopOnOverlap','BoolProperty',28},
        {'bUsePathfinding','BoolProperty',29},{'bProjectDestinationToNavigation','BoolProperty',30},
        {'bCanStrafe','BoolProperty',31},{'FilterClass','ClassProperty',32},{'bAllowPartialPath','BoolProperty',40},
        {'ReturnValue','ByteProperty',41}})
    local hof, ld = defenders[1], defenders[2]
    local last, health, damage, near_flag, near_carrier, red_score, hof_alive, ld_alive
    return {
        ready=function()
            return alive(hof.Pawn) and alive(ld.Pawn)
        end,
        reset=function(capper, now, score)
            position(hof,500,0)
            position(ld,-900,500)
            last, health, damage, near_flag, near_carrier, red_score = now,capper:GetHealth(),0,0,0,score
            hof_alive, ld_alive = 0,0
        end,
        tick=function(capper, carrying, now)
            if now-last < .25 then return end
            local dt = now-last
            last = now
            local current = capper:GetHealth()
            damage = damage+math.max(0,health-current)
            health = current
            if alive(hof.Pawn) then
                hof_alive = hof_alive+dt
                if distance(hof.Pawn:K2_GetActorLocation(),home) < 1800 then
                    near_flag = near_flag+dt
                else
                    move(hof,home,650)
                end
            end
            if alive(ld.Pawn) then
                ld_alive = ld_alive+dt
                local at = capper:K2_GetActorLocation()
                local ld_at = ld.Pawn:K2_GetActorLocation()
                if carrying and distance(ld_at,at) < 2200 then near_carrier = near_carrier+dt end
                if carrying or distance(at,home) < 5000 then
                    local v = capper.CharacterMovement.Velocity
                    move(ld,{X=at.X+v.X*.7,Y=at.Y+v.Y*.7,Z=at.Z},700)
                elseif distance(ld_at,home) > 3500 then
                    move(ld,home,1700)
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
