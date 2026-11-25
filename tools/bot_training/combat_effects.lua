-- Observe the native application while its effect spec and context are borrowed.
return function(env, install, before, after, before_direct, unavailable)
    local valid, signature = env.valid, env.signature
    local prefix = '/Script/GameplayAbilities.AbilitySystemBlueprintLibrary:'
    local context_path = prefix..'GetEffectContext'
    local self_path = '/Script/GameplayAbilities.AbilitySystemComponent:BP_ApplyGameplayEffectSpecToSelf'
    local target_path = '/Script/GameplayAbilities.AbilitySystemComponent:BP_ApplyGameplayEffectSpecToTarget'
    local external_path = '/Script/Valhalla.ValAbilityFunctionLibrary:ApplyExternalEffectSpec'
    local direct_path = '/Script/Valhalla.ValBlueprintLibrary:ApplyDirectDamage'
    local api = StaticFindObject('/Script/GameplayAbilities.Default__AbilitySystemBlueprintLibrary')
    local damage_api = StaticFindObject('/Script/Valhalla.Default__ValAbilityFunctionLibrary')
    assert(valid(api) and valid(damage_api),'combat_effect_libraries_required')
    signature(context_path,{{'SpecHandle','StructProperty',0},{'ReturnValue','StructProperty',16}})
    signature(prefix..'EffectContextGetEffectCauser',{{'EffectContext','StructProperty',0},{'ReturnValue','ObjectProperty',24}})
    signature(prefix..'EffectContextGetOriginalInstigatorActor',{{'EffectContext','StructProperty',0},{'ReturnValue','ObjectProperty',24}})
    signature(prefix..'EffectContextGetSourceObject',{{'EffectContext','StructProperty',0},{'ReturnValue','ObjectProperty',24}})
    signature(prefix..'GetAllActorsFromTargetData',{{'TargetData','StructProperty',0},{'ReturnValue','ArrayProperty',40}})
    signature('/Script/Valhalla.ValAbilityFunctionLibrary:GetSetByCallerMagnitudeByTag',
        {{'SpecHandle','StructProperty',0},{'DataTag','StructProperty',16},{'ReturnValue','FloatProperty',24}})
    signature(self_path,{{'SpecHandle','StructProperty',0},{'ReturnValue','StructProperty',16}})
    signature(target_path,{{'SpecHandle','StructProperty',0},{'Target','ObjectProperty',16},{'ReturnValue','StructProperty',24}})
    signature(external_path,{{'EffectSpec','StructProperty',0},{'TargetData','StructProperty',16},{'ReturnValue','ArrayProperty',56}})
    signature(direct_path,{{'SourceActor','ObjectProperty',0},{'TargetActor','ObjectProperty',8},{'DamageSpec','StructProperty',16}})
    local tag = {TagName=FName('Data.Damage')}
    local request
    local reading = true
    install(context_path,function() end,function(context,result)
        if not request then return end
        local ok, err = pcall(function()
            local library,native = context:get(),result:get()
            assert(valid(library) and library:GetAddress()==api:GetAddress() and type(native)=='userdata',
                'combat_effect_context_proxy_required')
            request.causer = api:EffectContextGetEffectCauser(native)
            request.instigator = api:EffectContextGetOriginalInstigatorActor(native)
            request.source = api:EffectContextGetSourceObject(native)
            request.read = true
        end)
        if not ok then request.err = err end
    end)
    local function read_effect(parameter)
        local spec = parameter:get()
        assert(type(spec)=='userdata' and not request,'combat_effect_spec_proxy_required')
        local damage = damage_api:GetSetByCallerMagnitudeByTag(spec,tag)
        if type(damage)~='number' or not (damage<0 and damage>-math.huge) then return end
        local info = {}
        request = info
        local ok, err = pcall(function() api:GetEffectContext(spec) end)
        request = nil
        assert(ok,err)
        assert(info.read and not info.err,info.err or 'combat_effect_context_not_observed')
        return info
    end
    local function apply(path, prepare)
        local frames = {}
        install(path,function(...)
            if not reading then frames[#frames+1] = false; return end
            local ok, observed = pcall(prepare,...)
            if not ok then
                reading = false
                unavailable(observed)
            end
            frames[#frames+1] = ok and observed or false
        end,function()
            local frame = frames[#frames]
            frames[#frames] = nil
            for _, observed in ipairs(frame or {}) do after(observed) end
        end)
    end
    apply(self_path,function(context,spec) return {before(context:get(),spec,read_effect)} end)
    apply(target_path,function(_,spec,target) return {before(target:get(),spec,read_effect)} end)
    apply(external_path,function(_,spec,target)
        local borrowed = target:get()
        assert(type(borrowed)=='userdata','combat_effect_target_data_proxy_required')
        local actors = api:GetAllActorsFromTargetData(borrowed) or {}
        assert(type(actors)=='table' and #actors<=64,'combat_effect_target_data_bounds')
        local observations, addresses = {}, {}
        for _, entry in ipairs(actors) do
            local actor = entry:get()
            if valid(actor) and not addresses[actor:GetAddress()] then
                addresses[actor:GetAddress()] = true
                local observed = before(actor.AbilitySystemComponent,spec,read_effect)
                if observed then observations[#observations+1] = observed end
            end
        end
        return observations
    end)
    apply(direct_path,function(_,source,target) return {before_direct(source:get(),target:get())} end)
end
