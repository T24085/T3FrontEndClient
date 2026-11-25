return function(env, world, capper, defenders)
    local valid = env.valid
    local participants = env.reset_participants or {capper}
    if not env.reset_participants and defenders then
        for _, controller in ipairs(defenders) do participants[#participants+1] = controller.Pawn end
    end
    local baseline
    local function ability_snapshot(pawn)
        local asc = pawn.AbilitySystemComponent
        assert(valid(asc))
        local handles = {}
        asc.ActiveGameplayEffects.GameplayEffects_Internal:ForEach(function(_, element)
            local effect = element:get()
            local spec = effect.Spec
            local definition = spec.Def
            assert(valid(definition), 'effect_definition_unavailable')
            handles[#handles+1] = table.concat({definition:GetFullName(),
                spec.StackCount, spec.Duration, spec.Period, effect.StartWorldTime,
                effect.bIsInhibited and 1 or 0}, ':')
        end)
        table.sort(handles)
        local abilities = {}
        asc.ActivatableAbilities.Items:ForEach(function(_, element)
            local spec = element:get()
            assert(type(spec.ActiveCount) == 'number' and type(spec.InputPressed) == 'boolean')
            abilities[#abilities+1] = table.concat({
                spec.Handle.Handle, spec.ActiveCount, spec.InputPressed and 1 or 0
            }, ':')
        end)
        assert(#abilities > 0)
        table.sort(abilities)
        return table.concat(handles, ',') .. '/' .. table.concat(abilities, ',')
    end
    return function(warm)
        if warm and not baseline then return false, 'fresh_baseline_inaccessible' end
        local snapshot = {}
        for index, pawn in ipairs(participants) do
            local controller = defenders and defenders[index-1]
            if not valid(pawn) or (controller and (not valid(controller.Pawn)
                    or controller.Pawn:GetAddress() ~= pawn:GetAddress())) then
                return false, 'pawn_changed'
            end
            if pawn:GetHealth() < pawn:GetHealthMax() or pawn:GetEnergy() < 99
                or pawn.CharacterMovement.bIsJetpackActive or pawn.CharacterMovement:IsSkiing() then
                return false, 'pawn_resources_or_input'
            end
            local ok, state = pcall(ability_snapshot, pawn)
            if not ok then
                if not warm then env.report('BOT_TRAIN_REUSE_UNAVAILABLE|ability_snapshot|'..tostring(state)) end
                return false, 'ability_snapshot'
            end
            if warm and baseline[index] ~= state then return false, 'active_effects_or_abilities' end
            snapshot[index] = state
        end
        if not valid(StaticFindObject('/Script/Valhalla.ValProjectile')) then
            return false, 'projectile_class_inaccessible'
        end
        for _, projectile in ipairs(FindAllOf('ValProjectile') or {}) do
            if valid(projectile) then
                local projectile_world = projectile:GetWorld()
                if valid(projectile_world) and projectile_world:GetAddress() == world:GetAddress() then
                    return false, 'live_projectile'
                end
            end
        end
        if not warm then baseline = snapshot end
        return true
    end
end
