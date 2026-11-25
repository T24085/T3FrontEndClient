-- Skip spawn rows over voids before creating a native pawn. The normal
-- spawn collision check still decides whether the pawn fits at this position.
return function(valid, signature)
    local path = '/Script/Engine.KismetSystemLibrary:LineTraceSingleForObjects'
    signature(path,{
        {'WorldContextObject','ObjectProperty',0},{'Start','StructProperty',8},{'End','StructProperty',32},
        {'ObjectTypes','ArrayProperty',56},{'bTraceComplex','BoolProperty',72},{'ActorsToIgnore','ArrayProperty',80},
        {'DrawDebugType','ByteProperty',96},{'OutHit','StructProperty',104},{'bIgnoreSelf','BoolProperty',336},
        {'TraceColor','StructProperty',340},{'TraceHitColor','StructProperty',356},{'DrawTime','FloatProperty',372},
        {'ReturnValue','BoolProperty',376},
    })
    local system = StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
    assert(valid(system),'training_spawn_floor_trace_required')
    local pending, walkable
    local clear = {R=0,G=0,B=0,A=0}
    RegisterHook(path,function() end,function(context,returned,caller,_,_,_,_,_,_,out)
        if not pending or context:get():GetAddress() ~= system:GetAddress()
            or caller:get():GetAddress() ~= pending or returned:get() ~= true then return end
        local hit = out:get()
        walkable = hit.bBlockingHit and not hit.bStartPenetrating and hit.ImpactNormal.Z >= .7
    end)
    return function(start,position)
        pending,walkable = start:GetAddress(),false
        local bottom = {X=position.X,Y=position.Y,Z=position.Z-1800}
        local ok,found = pcall(system.LineTraceSingleForObjects,system,start,position,bottom,
            {0},false,{start},0,{},true,clear,clear,0)
        pending = nil
        assert(ok,found)
        return found == true and walkable == true
    end
end
