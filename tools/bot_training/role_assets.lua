return function(valid, report, requested)
    local folder = '/Game/Topaz/Game/AI/BotData/PlayerBotData/CTF/'
    local profiles = {
        {'capper', 'LightCapper', 'Light'},
        {'heavy_on_flag', 'HeavyDefender', 'Heavy'},
        {'light_defense', {'LightSentinel', 'LightDefender', 'LightBrawler'}, 'Light'},
        {'heavy_offense', {'HeavyOffense', 'HeavyBrawler'}, 'Heavy'},
        {'medium_defense', {'MediumDefender', 'MediumDefense'}, 'Medium'},
    }
    local chosen = {}
    for i, profile in ipairs(profiles) do
        if i > 3 and not (requested and requested[i]) then break end
        local role, names, armor = table.unpack(profile)
        local asset, name, class
        if i == 3 and not (requested and requested[4]) then names = 'LightBrawler' end
        if type(names) == 'string' then names = {names} end
        for _, suffix in ipairs(names) do
            local candidate_name = 'Topaz_PlayerBot_CTF_'..suffix
            local path = folder..candidate_name..'.'..candidate_name
            local loaded, candidate = pcall(LoadAsset, path)
            if loaded and valid(candidate) and candidate:GetFullName() == 'ValBotData '..path then
                local pawn_class = candidate.BotPawnClass:GetObjectID():GetAssetPathName():ToString()
                if pawn_class:match('%.BP_TopazCharacter_'..armor..'_C$') then
                    asset, name, class = candidate, candidate_name, pawn_class
                    break
                end
            end
        end
        if i <= 3 then assert(asset, 'training_role_asset_missing='..role) end
        if asset then
            for _, field in ipairs({'BotPawnClass','BotController','LoadoutAsset','CustomABP','StateTree'}) do
                local dependency = asset[field]:GetObjectID():GetAssetPathName():ToString()
                if dependency ~= '' and dependency ~= 'None' then
                    assert(valid(LoadAsset(dependency)), 'training_role_dependency_missing='..dependency)
                end
            end
            report('BOT_ROLE_READY|'..role..'|'..name..'|'..class)
            if requested and requested[4] then
                report('BOT_ROLE_LOADOUT|'..role..'|'..asset.LoadoutAsset:GetObjectID():GetAssetPathName():ToString())
            end
            chosen[i] = asset
        end
    end
    return chosen
end
