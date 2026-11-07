-- Private visual comparison. The gate accepts numbered trials and "finish".
return function(env)
    local valid, scope, signature, report = env.valid, env.scope, env.signature, env.report
    local boltClass = 'BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/GA_Topaz_HeavyBoltLauncher.GA_Topaz_HeavyBoltLauncher_C'
    local slots = {mortar=2, pistol=3}
    local pc, pawn, asc, trial
    local requested, started, lastId = false, false, 0
    local service = {}

    local function same(a,b)
        return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()
    end

    local function equip(slot)
        pawn:SwapToEquipSlot({TagName=FName('EquipSlot.WeaponSlot.'..slot)})
    end

    local function selectedAbility()
        local selected = pawn:GetActiveEquippedAbility().Handle
        local selectedName
        asc.ActivatableAbilities.Items:ForEach(function(_,p)
            local spec = p:get()
            if spec.Handle.Handle==selected and valid(spec.Ability) then
                selectedName = spec.Ability:GetClass():GetFullName()
            end
        end)
        return selectedName or 'unavailable'
    end

    function service.select(plc,id)
        scope()
        if requested then return end
        assert(id==531,'bolt_fixture_heavy_loadout_required')
        local slot = {TagName=FName('EquipSlot.WeaponSlot.1')}
        local items = {}
        plc:GetLoadoutEquipSlotItems(id,slot,items)
        local chosen
        for _,wrapper in ipairs(items) do
            local item = wrapper:get()
            if item.ItemId==380 then chosen=item end
        end
        assert(chosen,'bolt_fixture_original_alternate_primary_missing')
        signature('/Script/Valhalla.PlayerLoadoutComponent:RequestLoadoutItem',{{'LoadoutId','IntProperty',0},{'EquipSlot','StructProperty',4},{'InventoryItem','StructProperty',16}})
        plc:RequestLoadoutItem(id,slot,chosen)
        requested = true
        report('BOLT_FIXTURE_LOADOUT_REQUEST|loadout=531|item=380|source=original_inventory')
    end

    local function readCommand()
        local file = io.open(env.gate,'rb')
        if not file then return '' end
        local command = file:read(80) or ''
        file:close()
        return command
    end

    local function sampleProjectiles()
        for _,projectile in ipairs(FindAllOf('BP_Projectile_Topaz_HeavyBoltLauncher_C') or {}) do
            if valid(projectile) and same(projectile:GetWorld(),pawn:GetWorld()) and same(projectile.Instigator,pawn) then
                local trail = projectile.NS_Projectile_Trail
                if valid(trail) and valid(trail.Asset) then
                    if not projectile.bHidden then trial.visibleProjectile = true end
                    report('BOLT_VISUAL_SAMPLE|id='..trial.id..'|tick='..trial.tick..
                        '|stopped='..tostring(projectile.bStopped)..'|predicted='..tostring(projectile.bIsClientProjectile)..
                        '|hidden='..tostring(projectile.bHidden)..'|asset='..trail.Asset:GetFullName()..
                        '|initialSpeed='..projectile.ProjectileMovement.InitialSpeed)
                end
            end
        end
    end

    local function sampleCameraEffects()
        local camera = pc.PlayerCameraManager
        if not valid(camera) then return end
        local origin = camera:GetCameraLocation()
        local components = FindAllOf('NiagaraComponent') or {}
        assert(#components<=8192,'bolt_fixture_niagara_count_bound')
        local reported = 0
        for _,component in ipairs(components) do
            if valid(component) and same(component:GetWorld(),pawn:GetWorld()) and
                valid(component.Asset) and component:IsActive() then
                local asset = component.Asset:GetFullName()
                local location = component:K2_GetComponentLocation()
                local dx,dy,dz = location.X-origin.X,location.Y-origin.Y,location.Z-origin.Z
                local distance = math.sqrt(dx*dx+dy*dy+dz*dz)
                if distance<450 or asset:find('/BoltLauncher/Heavy/',1,true) then
                    local owner = component:GetOwner()
                    report('BOLT_VISUAL_FX|id='..trial.id..'|tick='..trial.tick..
                        '|cameraCm='..string.format('%.1f',distance)..'|asset='..asset..
                        '|owner='..(valid(owner) and owner:GetFullName() or 'none'))
                    reported = reported+1
                    if reported>=24 then break end
                end
            end
        end
    end

    local function beginTrial(command)
        local id,mode,destination = command:match('^(%d+):(r[27]):(%a+)$')
        id = tonumber(id)
        if not id or id~=lastId+1 or (destination~='held' and not slots[destination]) then return end
        trial = {id=id,mode=mode,destination=destination,tick=0,visibleProjectile=false}
        lastId = id
        env.setMode(mode)
        equip(1)
        pc:SetControlRotation({Pitch=0,Yaw=0,Roll=0})
        report('BOLT_VISUAL_SCENE|id='..id..'|mode='..mode..'|destination='..destination)
    end

    local function advanceTrial()
        trial.tick = trial.tick+1
        local tick = trial.tick
        if tick==64 then
            sampleCameraEffects()
        elseif tick==80 then
            assert(selectedAbility()==boltClass,'bolt_fixture_original_grant_not_heavy_bolt')
            asc:PressInputID(5)
            report('BOLT_FIXTURE_FIRE|id='..trial.id..'|tick='..tick)
        elseif tick==83 then
            asc:ReleaseInputID(5)
        elseif tick==88 and slots[trial.destination] then
            equip(slots[trial.destination])
            report('BOLT_FIXTURE_STOW|id='..trial.id..'|tick='..tick..'|destination='..trial.destination)
        elseif tick==96 then
            local selected = selectedAbility()
            assert((trial.destination=='held')==(selected==boltClass) and selected~='unavailable',
                'bolt_fixture_wrong_weapon_after_switch')
            report('BOLT_VISUAL_EQUIPPED|id='..trial.id..'|ability='..selected)
        end
        if tick>=80 and tick<=208 and tick%8==0 then sampleProjectiles() end
        if tick==104 or tick==120 or tick==144 or tick==176 then sampleCameraEffects() end
        if tick==260 then
            report('BOLT_VISUAL_DONE|id='..trial.id..'|visibleProjectile='..tostring(trial.visibleProjectile))
            trial = nil
        end
    end

    local schedule
    schedule = function()
        ExecuteInGameThreadWithDelay(trial and 25 or 100,function()
            local ok,why = pcall(function()
                scope()
                assert(same(pc.Pawn,pawn) and same(pawn.Controller,pc) and same(pawn.AbilitySystemComponent,asc),
                    'bolt_fixture_owner_changed')
                if trial then
                    advanceTrial()
                else
                    local command = readCommand()
                    if command=='finish' then
                        report('BOLT_FIXTURE_COMPLETE|trials='..lastId..'|visualConfirmationSeparate=true')
                        return
                    end
                    beginTrial(command)
                end
                schedule()
            end)
            if not ok then report('BOLT_FIXTURE_ERROR|'..tostring(why)) end
        end)
    end

    function service.tick(controller,gs)
        if started or gs.r_GameplayPhaseInfo.Phase.TagName:ToString()~='GamePhase.GameplayStartPhase' then return end
        if not valid(controller.Pawn) or not controller.Pawn.bInitialized then return end
        started = true
        pc,pawn = controller,controller.Pawn
        asc = pawn.AbilitySystemComponent
        assert(pc:IsLocalPlayerController() and not pc:HasAuthority(),'bolt_fixture_local_owner_required')
        signature('/Script/GameplayAbilities.AbilitySystemComponent:PressInputID',{{'InputID','IntProperty',0}})
        signature('/Script/GameplayAbilities.AbilitySystemComponent:ReleaseInputID',{{'InputID','IntProperty',0}})
        signature('/Script/Engine.Controller:SetControlRotation',{{'NewRotation','StructProperty',0}})
        signature('/Script/Engine.SceneComponent:K2_GetComponentLocation',{{'ReturnValue','StructProperty',0}})
        signature('/Script/Engine.PlayerCameraManager:GetCameraLocation',{{'ReturnValue','StructProperty',0}})
        signature('/Script/Engine.ActorComponent:IsActive',{{'ReturnValue','BoolProperty',0}})
        report('BOLT_VISUAL_READY|gate='..env.gate)
        schedule()
    end

    return service
end
