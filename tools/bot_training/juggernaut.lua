return function(data, valid, report, signature)
    local name = '/Game/Topaz/Loadouts/Bots/BotLoadout_Juggernaut.BotLoadout_Juggernaut'
    local loadout = LoadAsset(name)
    assert(valid(loadout), 'training_juggernaut_asset_missing')
    local current = data.LoadoutAsset:GetObjectID():GetAssetPathName():ToString()
    report('BOT_HEAVY_ORIGINAL_LOADOUT|'..current)
    if current ~= name then
        local property
        data:GetClass():ForEachProperty(function(field)
            if field:GetFullName() == 'SoftObjectProperty /Script/Valhalla.ValBotData:LoadoutAsset' then
                property = field
            end
        end)
        assert(property, 'training_juggernaut_loadout_property_missing')
        property:ImportText(name, property:ContainerPtrToValuePtr(data,0), 0, data)
        assert(data.LoadoutAsset:GetObjectID():GetAssetPathName():ToString() == name,
            'training_juggernaut_asset_readback_failed')
    end
    signature('/Script/Valhalla.ValCharacter:GetBotLoadout',{{'ReturnValue','ObjectProperty',0}})
    return function(pawn)
        local actual = pawn:GetBotLoadout()
        assert(valid(actual) and actual:GetAddress() == loadout:GetAddress(), 'training_juggernaut_pawn_readback_failed')
        report('BOT_HEAVY_JUGGERNAUT|'..actual:GetFullName())
    end
end
