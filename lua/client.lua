-- Private launcher runtime. All calls run on the game thread in this exact child.
local EXPECTED=@@EXPECTED@@
local OUTPUT=@@OUTPUT@@
local DESTINATION=@@DESTINATION@@
-- SPECTATOR_CLIENT_CONTRACT_V1
local SPECTATOR_ROLE=@@SPECTATOR_ROLE@@
local SPECTATOR_LEASE=@@MATCH_LEASE@@
local SPECTATOR_WATCH=@@WATCH_ID@@
local spectatorRuntime=nil
local nativeSpectatorPresentation
local MODE="BlueprintGeneratedClass /Game/Topaz/Game/BP_TopazGameMode_CTF_Persistent_BotBackfill.BP_TopazGameMode_CTF_Persistent_BotBackfill_C"
local joined=false
local nextHandle=nil
local stopped=false
local records={}
local recordCount=0
local written=0
local function valid(o) return o~=nil and o:IsValid() end
local function report(text)
    text=tostring(text):gsub("[\r\n]"," "):sub(1,2048)
    written=written+#text+1;assert(written<=1048576,"launcher_runtime_output_bound")
    local f=assert(io.open(OUTPUT,"ab"));assert(f:write(text,"\n"));assert(f:flush());assert(f:close())
end
local function loaded(path,identity)
    local o=StaticFindObject(path);assert(valid(o) and o:GetFullName()==identity,"loaded_identity_required="..path);return o
end
local function signature(path,fields)
    local fn=loaded(path,"Function "..path);local n=0
    fn:ForEachProperty(function(p)
        n=n+1;local field=assert(fields[n],"extra_function_parameter")
        assert(p:GetFullName()==field[2].." "..path..":"..field[1] and p:GetOffset_Internal()==field[3],"function_parameter_changed="..path)
    end);assert(n==#fields,"parameter_count_changed="..path)
end
local function scope()
    assert(IsInGameThread()==true,"game_thread_required")
    local sys=loaded("/Script/Engine.Default__KismetSystemLibrary","KismetSystemLibrary /Script/Engine.Default__KismetSystemLibrary")
    local c=sys:GetCommandLine();c=type(c)=="string" and c or c:ToString()
    assert(c:match("^%s*(.-)%s*$")==EXPECTED,"exact_owned_command_required")
    return sys
end
local mapDefinitions=assert(loadfile(@@MAP_DEFINITIONS@@))()
-- The sand release changes only this tile's authored mesh identity.
do
    local center='/Game/Community/RollercoasterSand2026/SM_RollercoasterCenter'
    local session=assert(OUTPUT:match('^(.*/)'))
    local asset=io.open(session..'game/Topaz/Content'..center:sub(6)..'.uasset','rb')
    if asset then
        asset:close()
        for _,row in ipairs(mapDefinitions.Rollercoaster2026.geometry) do
            if row.actor=='StaticMeshActor_47' then
                row.asset=center..'.SM_RollercoasterCenter'
                break
            end
        end
    end
end
local configure_geometry=assert(loadfile(@@GEOMETRY@@))()({valid=valid,report=report,signature=signature,settings=assert(loadfile(@@LEVEL_SETTINGS@@))(),descriptors=mapDefinitions})
local configure_weather=assert(loadfile(@@SNOWBLIND_WEATHER@@))()({valid=valid,report=report,scope=scope,descriptors=mapDefinitions})
local configure_base_lighting=(function()
 local current
 local tags
 local function blink_interval(actor)
  local interval=actor:ActorHasTag(FName('CwBlink')) and .5 or nil
  local configured
  local names=actor.Tags
  if names then
   for i=1,names:GetArrayNum() do
    local tag=names[i]
    local name=type(tag)=='string' and tag or tag:ToString()
    local ms=tonumber(name:lower():match('^cwblink_(%d+)$'))
    if ms and ms>0 and ms<=60000 then
     if configured then return interval end
     configured=ms/1000
    end
   end
  end
  return configured or interval
 end
 local function same_world(actor,world)
  if not valid(actor) then return false end
  local own=actor:GetWorld()
  return valid(own) and own:GetAddress()==world:GetAddress()
 end
 local function scan(gs,world)
  local teams={{normal={},alarm={},blinking={}},{normal={},alarm={},blinking={}}}
  local prefix=gs:GetFullName():match(' (/Game/.+:)PersistentLevel%.')
  if not prefix then return teams,false end
  for _,row in pairs(mapDefinitions) do
   if row.world==prefix and row.emergency_lighting==false then return teams,false end
  end
  tags=tags or {{FName('CwPwr_T1_Normal'),1,'normal'},{FName('CwPwr_T1_Alarm'),1,'alarm'},
                {FName('CwPwr_T2_Normal'),2,'normal'},{FName('CwPwr_T2_Alarm'),2,'alarm'}}
  local any=false
  for _,actor in ipairs(FindAllOf('Actor') or {}) do
   if same_world(actor,world) and actor:GetFullName():find(prefix..'PersistentLevel.',1,true) then
    local group
    for _,match in ipairs(tags) do
     if actor:ActorHasTag(match[1]) then
      if group then group=nil;break end
      group=match
     end
    end
    if group then
     local team=teams[group[2]]
     local half=group[3]=='alarm' and blink_interval(actor)
     if half then
      team.blinking[#team.blinking+1]={actor=actor,half=half}
     else
      local set=team[group[3]]
      set[#set+1]=actor
     end
     any=true
    end
   end
  end
  return teams,any
 end
 local function power(gs,world)
  local generators=gs.r_Generators
  if not generators then return end
  local count=generators:GetArrayNum()
  if count>64 then return end
  local totals,online={0,0},{false,false}
  local seen={}
  for i=1,count do
   -- An unresolved weak reference can arrive before its generator on late join.
   local weak=generators[i]
   local actor=weak and weak:Get()
   if not same_world(actor,world) then return end
   local team,active=actor.r_TeamId,actor:IsOnline()
   if (team~=1 and team~=2) or type(active)~='boolean' then return end
   local id=actor:GetAddress()
   if not seen[id] then
    totals[team]=totals[team]+1
    online[team]=online[team] or active
    seen[id]=true
   end
  end
  return {totals[1]==0 or online[1],totals[2]==0 or online[2]}
 end
 local function set_visible(actor,world,visible)
  if not same_world(actor,world) then return end
  actor:SetActorHiddenInGame(not visible)
  local light=actor.LightComponent
  if valid(light) then light:SetVisibility(visible,true) end
 end
 local function show(set,world,visible)
  for _,actor in ipairs(set) do set_visible(actor,world,visible) end
 end
 return function(gs)
  local world=gs:GetWorld()
  if not valid(world) then return end
  local context=gs:GetAddress()
  if not current or current.address~=world:GetAddress() or current.context~=context then
   local teams,any=scan(gs,world)
   current={address=world:GetAddress(),context=context,teams=teams,any=any}
  end
  if not current.any then return end
  local states=power(gs,world)
  if not states then return end
  for team,lights in ipairs(current.teams) do
   local powered=states[team]
   if lights.powered~=powered and (#lights.normal>0 or #lights.alarm>0 or #lights.blinking>0) then
    show(lights.normal,world,powered)
    show(lights.alarm,world,not powered)
    lights.powered=powered
    if #lights.blinking>0 then
     lights.blink_started=not powered and gs:GetServerWorldTimeSeconds() or nil
     for _,alarm in ipairs(lights.blinking) do
      alarm.visible=not powered
      set_visible(alarm.actor,world,alarm.visible)
     end
    end
    report('BASE_LIGHTING|team='..team..'|powered='..tostring(powered))
   end
   if not powered and lights.blink_started then
    local elapsed=math.max(0,gs:GetServerWorldTimeSeconds()-lights.blink_started)
    for _,alarm in ipairs(lights.blinking) do
     local visible=math.floor(elapsed/alarm.half)%2==0
     if alarm.visible~=visible then
      set_visible(alarm.actor,world,visible)
      alarm.visible=visible
     end
    end
   end
  end
 end
end)()
local configure_water=assert(loadfile(@@DAMNATION_WATER@@))()({valid=valid,report=report,descriptors=mapDefinitions})
local allowedMaps={}
for name,row in pairs(mapDefinitions)do
 assert(name==row.name,"map_descriptor_identity_disagreement");allowedMaps[#allowedMaps+1]=row
end
local function player_key(pc) return pc:GetFullName()..'|'..string.format('%x',pc:GetAddress()) end
local function player_record(pc,ps)
    local key=player_key(pc)
    if not records[key] then
        assert(recordCount<64,"launcher_player_history_capacity_restart_client")
        records[key]={psName=ps:GetFullName(),psAddress=ps:GetAddress()};recordCount=recordCount+1
    end
    local r=records[key]
    assert(r.psName==ps:GetFullName() and r.psAddress==ps:GetAddress(),"player_state_identity_changed_restart_client")
    return r
end
local function state()
    local all=FindAllOf("ValGameState") or {};if #all~=1 or not valid(all[1]) then return nil end
    local recognized=false;for _,entry in ipairs(allowedMaps) do if all[1]:GetFullName():find(entry.world,1,true) then recognized=true end end
    if not recognized then return nil end
    return all[1]
end
local markerService=nil
local inputService=nil
-- BEGIN_WEAPON_INPUT_RECOVERY_V1|sha256=f4f505a0b6a3e27b3f30c1e4d8a4b7940e4c5a4b1e84a92df12347765162efdd
local weaponInputFactory=(function()
-- Client-side completion of original weapon input and cancellation protocols.
-- Projectile creation, ammo, per-weapon last-shot times and cooldowns stay native.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 signature('/Script/GameplayAbilities.AbilitySystemComponent:ServerSetInputReleased',{{'AbilityHandle','StructProperty',0}})
 signature('/Script/GameplayAbilities.GameplayAbility:K2_CancelAbility',{})
 signature('/Script/Valhalla.ValCharacter:GetActiveEquippedAbility',{{'ReturnValue','StructProperty',0}})
 local masterPath='/Game/Abilities/Devices/Gun/GA_Gun_Master.GA_Gun_Master_C'
 local reloadPath='/Game/Abilities/Devices/Gun/GA_Gun_Master_Reload.GA_Gun_Master_Reload_C'
 local master=nil;local reloadMaster=nil;local state;local stopped=false;local visualObserver=env.observeVisuals
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function owned(s)
  return valid(s.pc)and s.pc:IsLocalPlayerController()and not s.pc:HasAuthority()
   and same(s.pc.Pawn,s.pawn)and s.pawn:GetFullName()==s.name and same(s.pawn.Controller,s.pc)
   and same(s.pawn.AbilitySystemComponent,s.asc)and same(s.asc:GetOwner(),s.pawn)
   and same(s.pawn:GetWorld(),s.world)
 end
 local function pulse()
  local s=state;if not s then return end
  if not owned(s)then state=nil;return end
  if not valid(master)then master=StaticFindObject(masterPath)end
  if not valid(master)then return end
  assert(master:GetFullName()=='BlueprintGeneratedClass '..masterPath,'weapon_input_master_identity_changed')
  local selected=s.pawn:GetActiveEquippedAbility().Handle
  if visualObserver then
   local ok,why=pcall(visualObserver,s.pc,s.pawn,s.asc,selected)
   if not ok then visualObserver=nil;report('HEAVY_BOLT_VISUAL_ERROR|'..tostring(why):sub(1,500))end
  end
  if not valid(reloadMaster)then reloadMaster=StaticFindObject(reloadPath)end
  if valid(reloadMaster)then assert(reloadMaster:GetFullName()=='BlueprintGeneratedClass '..reloadPath,'weapon_input_reload_identity_changed')end
  local pressed=false;local grants={};local reloads={};local count=0
  s.asc.ActivatableAbilities.Items:ForEach(function(_,param)
   count=count+1;assert(count<=256,'weapon_input_grant_bound')
   local spec=param:get()
   if spec.InputID==5 and valid(spec.Ability)and spec.Ability:IsA(master)then
    pressed=pressed or spec.InputPressed
    grants[#grants+1]=spec
   end
   if valid(reloadMaster)and valid(spec.Ability)and spec.Ability:IsA(reloadMaster)then reloads[#reloads+1]=spec end
  end)
  if #grants==0 then return end
  -- GAS can end the local predicted ability before key-up. Its ordinary
  -- release path can then omit the still-active server counterpart.
  if not pressed and s.pressed==true then
   for _,spec in ipairs(grants)do s.asc:ServerSetInputReleased(spec.Handle)end
   report('WEAPON_INPUT_RELEASE_SYNC|handles='..#grants)
  end
  s.pressed=pressed
  if selected==s.selected then return end
  local previous=s.selected;s.selected=selected
  if not previous or previous==0 then return end
  local oldInstances={}
  for _,spec in ipairs(grants)do
   if spec.Handle.Handle==previous and spec.Handle.Handle~=selected then
    local cancelled={}
    for _,arrayName in ipairs({'NonReplicatedInstances','ReplicatedInstances'})do
     spec[arrayName]:ForEach(function(_,param)
      local ability=param:get()
      if valid(ability)and ability:IsA(master)and same(ability.SourceCharacter,s.pawn)and not cancelled[ability:GetAddress()]then
       cancelled[ability:GetAddress()]=true
       oldInstances[ability:GetAddress()]=true
       if spec.ActiveCount>0 then
        assert(ability.bServerRespectsRemoteAbilityCancellation==true,'weapon_input_native_cancel_contract_required')
        ability.InputBuffered=false;ability.ListeningForInput=false
        ability:K2_CancelAbility()
        report('WEAPON_INPUT_SWAP_CANCEL|oldHandle='..previous..'|newHandle='..selected..'|weapon='..ability:GetClass():GetFullName())
       end
      end
     end)
    end
   end
  end
  for _,spec in ipairs(reloads)do
   if spec.ActiveCount>0 then
    local cancelled={}
    for _,arrayName in ipairs({'NonReplicatedInstances','ReplicatedInstances'})do
     spec[arrayName]:ForEach(function(_,param)
      local ability=param:get()
      if valid(ability)and ability:IsA(reloadMaster)and same(ability.OwningCharacter,s.pawn)
       and valid(ability.GA_Gun)and oldInstances[ability.GA_Gun:GetAddress()]and not cancelled[ability:GetAddress()]then
       cancelled[ability:GetAddress()]=true
       assert(ability.bServerRespectsRemoteAbilityCancellation==true,'weapon_input_native_reload_cancel_contract_required')
       ability:K2_CancelAbility()
       report('WEAPON_INPUT_OLD_RELOAD_CANCEL|oldHandle='..previous..'|newHandle='..selected..'|reloadHandle='..spec.Handle.Handle)
      end
     end)
    end
   end
  end
 end
 local schedule
 schedule=function()
  ExecuteInGameThreadWithDelay(25,function()
   if stopped then return end
   local ok,why=pcall(function()scope();pulse();schedule()end)
   if not ok then stopped=true;report('WEAPON_INPUT_ERROR|'..tostring(why):sub(1,500))end
  end)
 end
 schedule();report('WEAPON_INPUT_READY|nativeFire=true|nativeAmmo=true|perWeaponCooldowns=true')
 return function(pc,ps)
  local pawn=pc.Pawn
  if not valid(pawn)or not pawn.bInitialized or not same(pawn.PlayerState,ps)then return end
  if state and same(state.pawn,pawn)and state.name==pawn:GetFullName()then return end
  local asc=pawn.AbilitySystemComponent;if not valid(asc)then return end
  state={pc=pc,pawn=pawn,asc=asc,world=pawn:GetWorld(),name=pawn:GetFullName()}
 end
end


end)()
local heavyBoltVisualFactory=(function()
-- Keep the local Heavy Bolt's flight and reload effects out of the camera.
return function(env)
 local valid,scope,report=env.valid,env.scope,env.report
 local weapon='/Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/'
 local gun='BlueprintGeneratedClass '..weapon..'GA_Topaz_HeavyBoltLauncher.GA_Topaz_HeavyBoltLauncher_C'
 local visualPath=weapon..'AV_Topaz_HeavyBoltLauncher.AV_Topaz_HeavyBoltLauncher'
 local trail='/Game/VFX/Weapons/BoltLauncher/Heavy/Projectile/NS_BoltLauncher_Heavy_Projectile_'
 local one='NiagaraSystem '..trail..'1P.NS_BoltLauncher_Heavy_Projectile_1P'
 local three='NiagaraSystem '..trail..'3P.NS_BoltLauncher_Heavy_Projectile_3P'
 local reload='NiagaraSystem /Game/VFX/Weapons/BoltLauncher/Heavy/Reload/'
 local reloadSockets={
  [reload..'NS_BoltLauncher_Heavy_Bolt_Reload.NS_BoltLauncher_Heavy_Bolt_Reload']='EnergyBullet_Socket',
  [reload..'NS_BoltLauncher_Heavy_EnergyTether_Reload.NS_BoltLauncher_Heavy_EnergyTether_Reload']='MuzzleSocket',
 }
 local configured
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end

 return function(pc,pawn,asc)
  scope()
  if valid(configured) then return end
  if not valid(pc)or not pc:IsLocalPlayerController()or pc:HasAuthority()or not same(pc.Pawn,pawn)or not same(pawn.Controller,pc)or not same(pawn.AbilitySystemComponent,asc)or not same(asc:GetOwner(),pawn)then return end
  local hasBolt=false
  asc.ActivatableAbilities.Items:ForEach(function(_,p)
   local spec=p:get()
   if spec.InputID==5 and valid(spec.Ability)and spec.Ability:GetClass():GetFullName()==gun then hasBolt=true end
  end)
  if not hasBolt then return end

  local visual=StaticFindObject(visualPath)
  if not valid(visual)or visual:GetFullName()~='ValDeviceAudioVisual '..visualPath then return end
  local first,world=visual.ProjectileTrail1P,visual.ProjectileTrail3P
  if not valid(first)or not valid(world)or world:GetFullName()~=three then return end
  if not same(first,world)and first:GetFullName()~=one then return end

  local targets={}
  local seen={}
  visual.ReloadActions:ForEach(function(_,param)
   local action=param:get()
   local system=action.ParticleSystem
   if not valid(system) then return end
   local name=system:GetFullName()
   local socket=reloadSockets[name]
   if socket and action.SocketName:ToString()==socket then
    assert(not seen[name],'heavy_bolt_duplicate_camera_reload_action')
    seen[name]=true
    targets[#targets+1]=action
   end
  end)
  if #targets~=2 then return end

  -- The original projectile reads this slot when assigning its trail. A single
  -- asset selection also covers bolts that impact before the player stows the gun.
  -- The two first-person reload emitters can outlive the weapon attachment.
  -- Retire their particle systems while preserving the original reload itself.
  for _,action in ipairs(targets)do
   action.ParticleSystem=nil
   assert(not valid(action.ParticleSystem),'heavy_bolt_camera_reload_readback_failed')
  end
  visual.ProjectileTrail1P=world
  assert(same(visual.ProjectileTrail1P,world),'heavy_bolt_world_trail_readback_failed')
  configured=visual
  report('HEAVY_BOLT_CAMERA_EFFECTS_READY|trail=original_3P|reload_emitters=2|stage=before_projectile')
 end
end
end)()
local heavyBoltVisual=heavyBoltVisualFactory({valid=valid,scope=scope,signature=signature,report=report})
local weaponInput=weaponInputFactory({valid=valid,scope=scope,signature=signature,report=report,observeVisuals=heavyBoltVisual})
-- END_WEAPON_INPUT_RECOVERY_V1

-- BEGIN_DIRECT_PLAYTEST_PRESENTATION
local shockLanceVisual
local function configure_shock_lance()
    if valid(shockLanceVisual) then return end
    local path='/Game/Topaz/Abilities/Weapons/Shocklance/AV_Topaz_Shocklance.AV_Topaz_Shocklance'
    local visual=StaticFindObject(path)
    if not valid(visual) or visual:GetFullName()~='ValDeviceAudioVisual '..path then return end

    local prefix='NiagaraSystem /Game/VFX/Weapons/ShockLance/'
    local targets={}
    local function select_action(actions,expected)
        local count=0
        actions:ForEach(function(_,param)
            local action=param:get()
            local system=action.ParticleSystem
            if valid(system) and system:GetFullName()==prefix..expected and action.SocketName:ToString()=='MuzzleSocket' then
                count=count+1
                targets[#targets+1]=action
            end
        end)
        return count==1
    end
    if not select_action(visual.RemainingAmmoActions,'Ammo/NS_ShockLance_Standard_Ammo_1P.NS_ShockLance_Standard_Ammo_1P') then return end
    if not select_action(visual.ReloadActions,'Reload/NS_ShockLance_Standard_Reload_1P.NS_ShockLance_Standard_Reload_1P') then return end

    -- These attached effects contain local-space lightning ribbons. The
    -- muzzle flash, world-space tracers and impacts use separate slots.
    for _,action in ipairs(targets) do
        action.ParticleSystem=nil
        assert(not valid(action.ParticleSystem),'shock_lance_camera_effect_readback_failed')
    end
    shockLanceVisual=visual
    report('SHOCK_LANCE_CAMERA_EFFECTS_READY|charge=false|reload=false')
end

local scoreBarClass='WidgetBlueprintGeneratedClass /Game/UI/Components/Game/WBP_Game_ScoreBar_CTF.WBP_Game_ScoreBar_CTF_C'
local scoreBars={}
local scoreBarWorld,scoreBarController,scoreBarReported
local scoreBarScanDelay=0
local function same_object(a,b)
    return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()
end

local function prune_generator_icons(panel,world)
    if not valid(panel) then return end
    local count=panel:GetChildrenCount()
    if count<2 or count>32 then return end
    local seen,duplicates={},{}
    for index=0,count-1 do
        local icon=panel:GetChildAt(index)
        if valid(icon) and icon:GetClass():GetFullName()==
                'WidgetBlueprintGeneratedClass /Game/UI/Components/Game/WBP_Game_GeneratorIcon.WBP_Game_GeneratorIcon_C' then
            local generator=icon.CachedActor
            if valid(generator) and same_object(generator:GetWorld(),world) then
                local key=generator:GetAddress()
                if seen[key] then duplicates[#duplicates+1]=index end
                seen[key]=true
            end
        end
    end
    for index=#duplicates,1,-1 do panel:RemoveChildAt(duplicates[index]) end
end

local function refresh_ctf_score_bar(pc,ps,gs)
    local team=ps.r_TeamId
    if team~=1 and team~=2 then return end
    local world=pc:GetWorld()
    if not same_object(world,gs:GetWorld()) then return end
    if not same_object(scoreBarWorld,world) or not same_object(scoreBarController,pc) then
        scoreBarWorld,scoreBarController=world,pc
        scoreBarScanDelay=0
        scoreBarReported=false
    end
    if scoreBarScanDelay==0 then
        scoreBars={}
        for _,widget in ipairs(FindAllOf('WBP_Game_ScoreBar_CTF_C') or {}) do
            if valid(widget) and widget:GetClass():GetFullName()==scoreBarClass
                and same_object(widget:GetWorld(),world) and same_object(widget:GetOwningPlayer(),pc) then
                scoreBars[#scoreBars+1]=widget
            end
        end
        scoreBarScanDelay=3
    end
    scoreBarScanDelay=scoreBarScanDelay-1
    if #scoreBars==0 then return end

    local rows=gs.r_CurrentTeamScores
    local count=rows:GetArrayNum()
    local scores,malformed={},count>4
    if not malformed then
        rows:ForEach(function(_,param)
            local row=param:get()
            local id,score=row.TeamNum,row.Score
            if id~=1 and id~=2 then return end
            if scores[id]~=nil or type(score)~='number' or score<0 or score%1~=0 then malformed=true;return end
            scores[id]=score
        end)
    end
    if malformed then scores={} end
    local friendly,enemy=scores[team],scores[3-team]
    for _,widget in ipairs(scoreBars) do
        if valid(widget) and widget:IsVisible() then
            prune_generator_icons(widget.FriendlyGenerators,world)
            prune_generator_icons(widget.EnemyGenerators,world)
            local updated=false
            local function sync_counter(score,fill,counter)
                if score==nil or not valid(fill) or not valid(counter) or not valid(counter.ScoreText) then return end
                if counter.CachedScore~=score or tonumber(counter.ScoreText:GetText():ToString())~=score then
                    -- Use the original fill and counter update with the absolute
                    -- replicated score for this side, independent of the delta.
                    widget:UpdateScore(score,fill,counter)
                    updated=true
                end
            end
            sync_counter(friendly,widget.FriendlyScoreFill,widget.UI_Game_Scorebar_ScoreCount)
            sync_counter(enemy,widget.EnemyScoreFill,widget.UI_Game_Scorebar_ScoreCount_1)
            if updated and not scoreBarReported then
                scoreBarReported=true
                report('CTF_SCORE_BAR_REFRESHED|team='..team..'|friendly='..tostring(friendly)..'|enemy='..tostring(enemy))
            end
        end
    end
end
-- END_DIRECT_PLAYTEST_PRESENTATION

local function flag_marker_projection(valid)
 local layout=StaticFindObject('/Script/UMG.Default__WidgetLayoutLibrary')
 assert(valid(layout),'flag_marker_projection_library_required')

 return function(entry,pc,target,lift)
  local widget=entry.widget
  local slot,parent=widget.Slot,widget:GetParent()
  if not valid(slot) or not valid(parent) then return end

  local viewport=layout:GetViewportSize(pc)
  local dpi=layout:GetViewportScale(pc)
  local cx,cy=viewport.X/2,viewport.Y/2
  if cx<=0 or cy<=0 or dpi<=0 then return end
  local out={}
  -- Keep the viewport origin used by Slate, including a constrained view rect.
  local front=pc:ProjectWorldLocationToScreen(target,out,false)
  local x,y
  if front then
   local screen=out.ScreenLocation or out
   x,y=screen.X-cx,screen.Y-cy
  else
   local camera=pc.PlayerCameraManager
   if not valid(camera) then return end
   local origin,rotation=camera:GetCameraLocation(),camera:GetCameraRotation()
   local yaw,pitch=math.rad(rotation.Yaw),math.rad(rotation.Pitch)
   local dx,dy,dz=target.X-origin.X,target.Y-origin.Y,target.Z-origin.Z
   x=-math.sin(yaw)*dx+math.cos(yaw)*dy
   y=math.sin(pitch)*math.cos(yaw)*dx+math.sin(pitch)*math.sin(yaw)*dy-math.cos(pitch)*dz
   if math.abs(x)+math.abs(y)<0.0001 then y=1 end
  end
  local offscreen=not front or math.abs(x)>cx or math.abs(y)>cy
  if offscreen or lift then
   local desired=widget:GetDesiredSize()
   local edgeX,edgeY=cx-(desired.X/2+8)*dpi,cy-(desired.Y/2+8)*dpi
   if edgeX<=0 or edgeY<=0 then return end
   if offscreen then
    local scale=math.min(edgeX/math.max(math.abs(x),0.0001),edgeY/math.max(math.abs(y),0.0001))
    x,y=x*scale,y*scale
   else
    y=math.max(-edgeY,math.min(edgeY,y-lift*dpi))
   end
  end
  local anchor={X=(cx+x)/viewport.X,Y=(cy+y)/viewport.Y}
  if anchor.X~=anchor.X or anchor.Y~=anchor.Y or math.abs(anchor.X)==math.huge or math.abs(anchor.Y)==math.huge then return end
  if not same_object(entry.layoutSlot,slot) then
   slot:SetAutoSize(true)
   slot:SetAlignment({X=0.5,Y=0.5})
   entry.layoutSlot=slot
  end
  -- The retail Flags canvas fills the HUD. A point anchor lets Slate apply
  -- the actual canvas scale and leaves no pixel offset for DPI to distort.
  slot:SetAnchors({Minimum=anchor,Maximum=anchor})
  slot:SetPosition({X=0,Y=0})
  return true
 end
end

-- Use the original overlay widgets when the lobby opts in.
local function enabled_flag_markers(env)
 local valid,report=env.valid,env.report
 local project=flag_marker_projection(valid)
 env.signature('/Script/Topaz.TopPickup_Flag:GetFlagState',{{'Querier','ObjectProperty',0},{'ReturnValue','EnumProperty',8}})
 env.signature('/Script/Engine.SceneComponent:K2_GetComponentLocation',{{'ReturnValue','StructProperty',0}})
 env.signature('/Script/Engine.KismetSystemLibrary:GetComponentBounds',{{'Component','ObjectProperty',0},
  {'Origin','StructProperty',8},{'BoxExtent','StructProperty',32},{'SphereRadius','FloatProperty',56}})
 local system=StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
 local state=nil
 local stopped=false
 local widgetPath='/Game/UI/Components/Game/Overlays/UI_Game_Overlay_FlagObjective.UI_Game_Overlay_FlagObjective_C'
 local library=StaticFindObject('/Script/UMG.Default__WidgetBlueprintLibrary')
 local function same(a,b) return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() end
 local function clear()
  if state then for _,entry in pairs(state.entries) do if entry.owned and valid(entry.widget) then entry.widget:RemoveFromParent() end end end
  state=nil
 end
 local function current(s)
  return valid(s.pc) and valid(s.ps) and valid(s.gs) and same(s.pc.PlayerState,s.ps) and same(s.pc:GetWorld(),s.gs:GetWorld()) and s.gs:GetFullName()==s.gameState and not s.pc:HasAuthority() and s.pc:IsLocalPlayerController()
 end
 local function flag_holder(flag,info)
  if info.bReturned then return nil end
  local holder=info.Holder
  if not valid(holder) then return nil end
  -- The replicated holder can still name the thrower after detachment.
  local root=flag.RootComponent
  local attached=valid(root) and root:GetAttachParent() or nil
  if same(flag:GetOwner(),holder) or (valid(attached) and same(attached:GetOwner(),holder)) then return holder end
 end
 local function loose_flag_anchor(flag,root)
  -- The pickup root is a collision sphere. The flag's visible mesh has its
  -- own transform and extends above that pivot.
  local mesh=flag.Mesh
  if valid(mesh) then
   local origin,extent={},{}
   system:GetComponentBounds(mesh,origin,extent,{})
   origin,extent=origin.Origin or origin,extent.BoxExtent or extent
   if type(extent.Z)=='number' and extent.Z>0 then
    return {X=origin.X,Y=origin.Y,Z=origin.Z+extent.Z}
   end
  end
  return {X=root.X,Y=root.Y,Z=root.Z+150}
 end
 local function pulse()
  local s=state
  if not s then return end
  if not current(s) then clear();return end
  local pawn=s.pc.Pawn
  if not valid(pawn) or not pawn.bInitialized or pawn:GetHealth()<=0 then return end
  local team=s.ps.r_TeamId
  if team~=1 and team~=2 then return end
  local carrying=false
  for _,e in pairs(s.entries) do
   if valid(e.flag) and e.flag.r_TeamId~=team and same(flag_holder(e.flag,e.flag:GetHeldBy()),pawn) then carrying=true end
  end
  for _,e in pairs(s.entries) do
   local flag,w=e.flag,e.widget
   if valid(flag) and valid(w) and same(flag:GetWorld(),s.pc:GetWorld()) then
    local friendly=flag.r_TeamId==team
    local flagState=flag:GetFlagState(pawn)
    local holderInfo=flag:GetHeldBy()
    local returned=holderInfo.bReturned==true
    local holder=flag_holder(flag,holderInfo)
    local holderAddress=valid(holder) and holder:GetAddress() or nil
    if e.returned~=returned or e.holderAddress~=holderAddress then
     -- Refresh the retail Tick on detachment as well as return. Both native
     -- callbacks accept LastHolderInfo and use only the current value.
     w:OnFlagHeldChanged(flag,holderInfo,holderInfo)
     w.Content:SetRenderTranslation({X=0,Y=0})
     e.holderAddress=holderAddress
    end
    if e.returned~=returned then
     if returned and e.returned==nil then
      e.home=flag:K2_GetActorLocation()
      e.homeAnchor=loose_flag_anchor(flag,e.home)
     end
     -- The stationary base widgets consume the same native flag notification.
     for _,base in ipairs(FindAllOf('UI_Game_Overlay_FlagBase_C') or {}) do
      if valid(base) and same(base:GetWorld(),s.pc:GetWorld()) and same(base:GetOwningPlayer(),s.pc) then
       base:OnFlagHeldChanged(flag,holderInfo,holderInfo)
       if same(base.CachedFlag,flag) then e.nativeBase=base end
      end
     end
     e.returned=returned
    end
    local ownCarried=not friendly and same(holder,pawn)
    local homeTarget=friendly and carrying and flagState==1
    local text=friendly and (flagState==4 and 'RETURN' or flagState==3 and 'CHASE' or homeTarget and 'GO HERE' or 'DEFEND') or (flagState==2 and 'ESCORT' or 'GRAB')
    w.BackgroundSwitcher:SetActiveWidget(friendly and (homeTarget and w.BlueGoTo or w.BlueDefend) or w.RedGoTo)
    w.ActionLabelGroup:SetVisibility(4)
    w.ActionText:SetText(FText(text))
    local position
    if returned then
     -- Community matches can omit the stand actor and its widget on clients.
     -- Keep the flag's original home position across out-of-order updates.
     -- A client that joined with the flag away uses its replicated return.
     if not valid(e.nativeBase) then position=e.home or flag:K2_GetActorLocation() end
    elseif not ownCarried then
     position=flag:K2_GetActorLocation()
    end
    local visible=position~=nil
    local projected=false
    if visible then
     local a,b=pawn:K2_GetActorLocation(),position
     local distance=math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2+(a.Z-b.Z)^2)
     w.DistanceText:SetText(FText(string.format('%dm',math.floor(distance/100+0.5))))
     local anchor,lift
     if holder then
      -- Retail uses the carrier's Character.Mesh origin and a 190 cm lift.
      local mesh=holder.Mesh
      local origin=valid(mesh) and mesh:K2_GetComponentLocation() or holder:K2_GetActorLocation()
      anchor={X=origin.X,Y=origin.Y,Z=origin.Z+190}
      -- The retail glyph rises by 40 Slate units nearby and 24 at range.
      lift=40-16*math.max(0,math.min(1,(distance-1000)/11500))
     else
      anchor=returned and e.homeAnchor or loose_flag_anchor(flag,b)
      lift=8
     end
     projected=project(e,s.pc,anchor,lift)==true
     if w.TimerIsActive and w.ResetDuration>0 then
      local material=w.TimerFill:GetDynamicMaterial()
      if valid(material) then
       local progress=(w['Reset Time']-s.gs:GetServerWorldTimeSeconds())/w.ResetDuration
       material:SetScalarParameterValue(FName('Progress'),math.max(0,math.min(1,progress)))
      end
     end
    end
    w:ShowOverlay(visible)
    w:SetVisibility(visible and 4 or 1)
    if projected and not e.projected then
     e.projected=true
     report('FLAG_MARKER_PROJECTED|team='..flag.r_TeamId)
    end
    local status=tostring(flag.r_TeamId)..'|'..text..'|'..tostring(ownCarried)..'|returned='..tostring(returned)
    if status~=e.status then e.status=status;report('FLAG_MARKER_STATE|'..status) end
   end
  end
 end
 local schedule
 schedule=function()
  ExecuteInGameThreadWithDelay(16,function()
   if stopped then return end
   local ok,why=pcall(function() env.scope();pulse();schedule() end)
   if not ok then stopped=true;report('OPTIONAL_FLAG_MARKER_ERROR|'..tostring(why):sub(1,500)) end
  end)
 end
 schedule();report('FLAG_MARKERS_READY')
 return function(pc,ps,gs)
  if not valid(pc) or not valid(ps) or not valid(gs) or pc:HasAuthority() or not pc:IsLocalPlayerController() or (ps.r_TeamId~=1 and ps.r_TeamId~=2) then return end
  if not same(pc:GetWorld(),gs:GetWorld()) then return end
  if state and (state.gameState~=gs:GetFullName() or not same(state.pc,pc) or not same(state.ps,ps)) then clear() end
  if not state then state={pc=pc,ps=ps,gs=gs,gameState=gs:GetFullName(),entries={}} end
  local parent
  for _,o in ipairs(FindAllOf('UI_Game_Overlays_C') or {}) do if valid(o) and o:GetFullName():find('/Engine/Transient.',1,true) and same(o:GetWorld(),pc:GetWorld()) and valid(o.Flags) then assert(not parent,'multiple_runtime_flag_hud_containers');parent=o.Flags end end
  if not parent then return end
  local visibility=parent:GetVisibility()
  if visibility==1 or visibility==2 then parent:SetVisibility(4) end
  for key,e in pairs(state.entries) do
   if not valid(e.flag) or not valid(e.widget) or not same(e.flag:GetWorld(),pc:GetWorld()) then
    if e.owned and valid(e.widget) then e.widget:RemoveFromParent() end
    state.entries[key]=nil
   end
  end
  local cls=StaticFindObject(widgetPath);if not valid(cls) then cls=LoadAsset(widgetPath) end
  assert(valid(cls) and valid(library),'original_flag_ui_required')
  for _,flag in ipairs(FindAllOf('TopPickup_Flag') or {}) do
   if valid(flag) and same(flag:GetWorld(),pc:GetWorld()) and (flag.r_TeamId==1 or flag.r_TeamId==2) then
    local key=flag:GetFullName()..'|'..tostring(flag:GetAddress())
    local e=state.entries[key]
    if not e or not valid(e.widget) or not same(e.widget:GetParent(),parent) then
     if e and e.owned and valid(e.widget) then e.widget:RemoveFromParent() end
     local widget
     for i=0,parent:GetChildrenCount()-1 do local child=parent:GetChildAt(i);if valid(child) and child:IsA(cls) and same(child.CachedActor,flag) then assert(not widget,'duplicate_native_flag_marker');widget=child end end
     local owned=not valid(widget)
     if owned then widget=library:Create(pc,cls,pc);assert(valid(widget),'original_flag_marker_creation_failed') end
     -- The stock widget's Tick writes a second pixel position while the flag
     -- is away. The HUD pulse owns positioning and the reset meter instead.
     widget.TickFrequency=0
     widget:StopAllAnimations()
     if owned then parent:AddChildToCanvas(widget);widget:UpdateFlagActor(flag) end
     -- The HUD pulse lifts the glyph with the same viewport projection that
     -- tracks it. Clear native translations so they cannot apply a second lift.
     local content=widget.Content
     local container=content:GetParent()
     local center={X=0.5,Y=0.5}
     container.Slot:SetAnchors({Minimum=center,Maximum=center})
     container.Slot:SetAlignment(center)
     content.Slot:SetAlignment(center)
     content:SetRenderTranslation({X=0,Y=0})
     widget:SetRenderTranslation({X=0,Y=0})
     state.entries[key]={flag=flag,widget=widget,owned=owned}
     report('FLAG_MARKER_BOUND|team='..flag.r_TeamId..'|created='..tostring(owned))
    end
   end
  end
 end
end

local scoreBarFailed,shockLanceVisualFailed
local markerFailed
local function update_flag_markers(pc,ps,gs)
 if not markerService then
  local factory=@@SHOW_FLAG_INDICATORS@@ and enabled_flag_markers or assert(loadfile(@@FLAG_MARKERS@@))()
  markerService=factory({valid=valid,report=report,signature=signature,scope=scope})
 end
 markerService(pc,ps,gs)
end

local function observe_markers(pc,ps,gs)
 weaponInput(pc,ps)
 if not inputService then inputService=assert(loadfile(@@JETPACK_INPUT@@))()({valid=valid,report=report,signature=signature,scope=scope}) end
 inputService(pc,ps)
 if not @@SHOW_FLAG_INDICATORS@@ then
  update_flag_markers(pc,ps,gs)
 elseif not markerFailed then
  local ok,why=pcall(update_flag_markers,pc,ps,gs)
  if not ok then markerFailed=true;report('OPTIONAL_FLAG_MARKER_ERROR|'..tostring(why):sub(1,500)) end
 end
end

local clientWorld=nil
local lastJoin=0
local function community_radar_group(descriptor)
 local package=descriptor and descriptor.package
 return type(package)=='string' and package:match('^/Game/Maps/Community/([^/]+)/') or nil
end
-- Production network-client radar binding.
local releaseRadarGuardFactory=(function()
-- One owner for the network-client/explicit standalone diagnostic distinction.
return function(env)
 local valid,scope,signature=assert(env.valid),assert(env.scope),assert(env.signature)
 return function(pc,gs)
  scope()
  assert(valid(pc) and valid(gs) and pc:IsLocalPlayerController(),'radar_local_player_required')
  assert(valid(pc:GetWorld()) and valid(gs:GetWorld()) and pc:GetWorld():GetAddress()==gs:GetWorld():GetAddress(),'radar_same_world_required')
  if not pc:HasAuthority() then return 'network_client' end
  assert(env.allow_standalone==true,'radar_authoritative_client_requires_explicit_standalone_scope')
  signature('/Script/Engine.KismetSystemLibrary:IsStandalone',{{'WorldContextObject','ObjectProperty',0},{'ReturnValue','BoolProperty',8}})
  local system=StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
  assert(valid(system) and system:GetFullName()=='KismetSystemLibrary /Script/Engine.Default__KismetSystemLibrary','radar_native_system_library_required')
  assert(system:IsStandalone(pc)==true,'radar_listen_or_dedicated_host_is_not_standalone')
  return 'standalone_diagnostic'
 end
end

end)()
local releaseRadarHelperFactory=(function()
-- Local minimap capture and display. Native radars, teams, power and authored
-- authored ValWorldSettings remain owners. The native zoom stays intact.
return function(env)
 local valid,report,scope,signature=assert(env.valid),assert(env.report),assert(env.scope),assert(env.signature)
 local contracts=assert(env.blueprint_contracts);local prefix=assert(env.world_prefix)
 if env.allow_standalone then assert(type(env.client_context_guard)=='function','radar_standalone_requires_native_context_guard') end
 local state=nil;local retired=false;local checkedBlueprints=false
 local capturePath='/Game/Common/Blueprints/Cameras/BP_MinimapCapture.BP_MinimapCapture_C'
 local targetName='TextureRenderTarget2D /Game/Maps/Game/CrossFire/Crossfire_RenderTarget2D.Crossfire_RenderTarget2D'
 local function same(a,b) return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() end
 local function finite(n) return type(n)=='number' and n==n and n>-math.huge and n<math.huge end
 local function loaded(path,name)
  local o=StaticFindObject(path);assert(valid(o) and o:GetFullName()==name,'radar_client_loaded_identity='..path);return o
 end
 local function verify_blueprints()
  if checkedBlueprints then return end
  for name,contract in pairs(contracts) do
   assert((name=='UpdateTexture' or name=='UpdateSublevel' or name=='BindRadarSensors') and contract.parameters==0,'radar_client_unknown_blueprint_contract')
   local fn=loaded(contract.path,'Function '..contract.path);local found={};local count,want=0,0
   for _ in pairs(contract.fields) do want=want+1 end
   fn:ForEachProperty(function(p)
    local field=p:GetFName():ToString();local kind=p:GetFullName():match('^(%S+)')
    assert(not found[field] and contract.fields[field]==kind,'radar_client_blueprint_field_changed='..name..':'..field)
    found[field]=true;count=count+1
   end)
   assert(count==want,'radar_client_blueprint_schema_incomplete='..name)
  end
  assert(contracts.UpdateTexture and contracts.UpdateSublevel and contracts.BindRadarSensors);checkedBlueprints=true
 end
 local function original_settings(pc) return assert(env.world_settings_guard)(pc,env.descriptor) end
 local function own_world(pc,gs)
  scope();assert(not retired,'radar_client_retired')
  if env.client_context_guard then env.client_context_guard(pc,gs)
  else assert(valid(pc) and valid(gs) and pc:IsLocalPlayerController() and not pc:HasAuthority(),'radar_client_local_network_player_required') end
  assert(same(pc:GetWorld(),gs:GetWorld()) and gs:GetFullName():find(prefix,1,true),'radar_client_selected_world_required')
  if state then assert(same(pc,state.pc) and same(gs,state.gs) and same(pc:GetWorld(),state.world),'radar_client_world_changed') end
 end
 local function setup(pc,gs)
  own_world(pc,gs)
  local settings=original_settings(pc)
  if not settings then return end
  local size,world=settings.MapSize,pc:GetWorld()
  for _,actor in ipairs(FindAllOf('BP_MinimapCapture_C') or {}) do
   if valid(actor) and same(actor:GetWorld(),world) then
    state={pc=pc,gs=gs,world=world,map_owned_capture=true}
    report('BASE_RADAR_CLIENT_MAP_CAPTURE_PRESENT|map='..env.descriptor.name)
    return
   end
  end
  verify_blueprints()
  signature('/Script/UMG.Widget:GetOwningPlayer',{{'ReturnValue','ObjectProperty',0}})
  signature('/Script/UMG.PanelWidget:GetChildrenCount',{{'ReturnValue','IntProperty',0}})
  local bottom,top,meshes=env.capture_bounds(gs,env.descriptor,size)
  local class=StaticFindObject(capturePath);if not valid(class) then class=LoadAsset(capturePath) end
  assert(valid(class) and class:GetFullName()=='BlueprintGeneratedClass '..capturePath,'radar_client_original_capture_class_required')
  local height=math.max(100000,top+11000)
  -- Exact original Pitch=-90,Yaw=0,Roll=-90 converted by UE5.3's FRotator
  -- quaternion formula (UnrealMath.cpp530), avoiding opaque transform locals.
  local transform={Rotation={X=.5,Y=.5,Z=-.5,W=.5},Translation={X=0,Y=0,Z=height},Scale3D={X=1,Y=1,Z=1}}
  local api=loaded('/Script/Engine.Default__GameplayStatics','GameplayStatics /Script/Engine.Default__GameplayStatics')
  local actor=api:BeginDeferredActorSpawnFromClass(pc,class,transform,1,nil,0)
  assert(valid(actor),'radar_client_capture_begin_failed')
  state={pc=pc,gs=gs,world=world,settings=settings,map_size=size,capture_width=size,capture=actor,capture_name=actor:GetFullName(),widgets={},created=true,manual_capture=false}
  local finished=api:FinishSpawningActor(actor,transform,0);assert(same(actor,finished),'radar_client_capture_finish_identity')
  local component=actor.SceneCaptureComponent2D
  assert(valid(component) and same(component:GetOwner(),actor),'radar_client_original_capture_component_required')
  local target=component.TextureTarget
  assert(valid(target) and target:GetFullName()==targetName,'radar_client_original_material_target_required')
  assert(type(target.SizeX)=='number' and target.SizeX>0 and target.SizeX==target.SizeY,'radar_client_square_render_target_required')
  assert(component.ProjectionType==1,'radar_client_orthographic_projection_required')
  component.OrthoWidth=size
  component.MaxViewDistanceOverride=math.max(200000,math.sqrt(size*size/2+(height-bottom)^2)+1000)
  state.component=component;state.target=target
  report('BASE_RADAR_CLIENT_CAPTURE_CREATED|mapSize='..size..'|width='..component.OrthoWidth..'|projectionSource=ValWorldSettings.MapSize|height='..height..'|mapMeshes='..meshes..'|target='..target:GetFullName()..'|pixels='..target.SizeX..'x'..target.SizeY)
 end
 local function bind_native_radars(widget,record)
  local canvas=widget.RadarSensors
  if not valid(canvas) then return false end
  local before=canvas:GetChildrenCount();assert(type(before)=='number' and before>=0 and before<=64,'radar_client_native_radar_canvas_capacity')
  local perTeam=env.descriptor.radars_per_team or 1
  local expected=2*perTeam
  local teams={0,0}
  for _,actor in ipairs(FindAllOf('BP_Objective_RadarSensor_C') or {}) do
   if valid(actor) and same(actor:GetWorld(),state.world) then
    assert(actor:GetClass():GetFullName()=='BlueprintGeneratedClass /Game/Topaz/Game/Objectives/BP_Objective_RadarSensor.BP_Objective_RadarSensor_C','radar_client_original_radar_class_required')
    local team=actor.r_TeamId
    if team~=1 and team~=2 then return false end
    teams[team]=teams[team]+1
   end
  end
  if teams[1]~=perTeam or teams[2]~=perTeam then return false end
  -- Native initialization can run while only some replicated sensors exist.
  -- Rebuild that partial sensor layer once, after every team ID has arrived.
  if perTeam>1 and before>0 and before<expected and not record.rebuilt_partial_radars then
   local radarClass=StaticFindObject('/Game/UI/Components/Game/UI_Game_Minimap_Radar.UI_Game_Minimap_Radar_C')
   if not valid(radarClass) then return false end
   for index=0,before-1 do
    local child=canvas:GetChildAt(index)
    if not valid(child) or not same(child:GetClass(),radarClass) then return false end
   end
   record.rebuilt_partial_radars=true
   canvas:ClearChildren()
   before=canvas:GetChildrenCount()
  end
  if before==0 then
   -- Invoke the exact original zero-parameter Blueprint only on its empty
   -- native canvas; it owns creation, binding, friendliness and positions.
   widget:BindRadarSensors()
   local after=canvas:GetChildrenCount()
   if after~=expected then return false end
   record.radar_canvas_ready=true
   report('BASE_RADAR_CLIENT_RADAR_CANVAS_BOUND|widget='..widget:GetFullName()..'|before=0|after='..after..'|radarActors='..expected..'|owner=OriginalBindRadarSensors|onlineFlagWrites=0')
   return true
  end
  -- Native initialization may already have populated the full canvas.
  if before~=expected then return false end
  if not record.radar_canvas_ready then report('BASE_RADAR_CLIENT_RADAR_CANVAS_READY|widget='..widget:GetFullName()..'|before='..before..'|nativeBindCalls=0|radarActors='..expected);record.radar_canvas_ready=true end
  return true
 end
 local service={}
 function service.tick(pc,gs)
  own_world(pc,gs)
  if env.descriptor.hide_minimap==true then
   if not state then
    signature('/Script/UMG.Widget:GetOwningPlayer',{{'ReturnValue','ObjectProperty',0}})
    state={pc=pc,gs=gs,world=pc:GetWorld()}
   end
   local hidden=false
   for _,widget in ipairs(FindAllOf('UI_Game_Map_C') or {}) do
    if valid(widget) and same(widget:GetWorld(),state.world) and same(widget:GetOwningPlayer(),pc) then
     if widget:GetVisibility()~=1 then widget:SetVisibility(1) end -- ESlateVisibility::Collapsed
     hidden=true
    end
   end
   if hidden and not state.reported then
    state.reported=true;report('BASE_RADAR_CLIENT_MINIMAP_HIDDEN|map='..env.descriptor.name)
   end
   return hidden
  end
  if not state then setup(pc,gs) end
  if not state then return false end
  if state.map_owned_capture then return true end
  assert(valid(state.capture) and state.capture:GetFullName()==state.capture_name and same(state.capture:GetWorld(),state.world),'radar_client_capture_identity_changed')
  assert(same(original_settings(pc),state.settings) and state.settings.MapSize==state.map_size,'radar_client_authored_map_contract_changed')
  local count,projected,bound=0,0,0
  for _,widget in ipairs(FindAllOf('UI_Game_Map_C') or {}) do
   if valid(widget) and same(widget:GetWorld(),state.world) and same(widget:GetOwningPlayer(),pc) then
    count=count+1;local key=widget:GetAddress()
    local previous=state.widgets[key]
    if previous and (not valid(previous.widget) or previous.name~=widget:GetFullName()) then state.widgets[key]=nil end
    if not state.widgets[key] and valid(widget.MapTexture) and valid(widget.Material) then
     local prior=widget.MinimapCapture
     assert(not valid(prior) or same(prior,state.capture),'radar_client_foreign_widget_capture')
     state.widgets[key]={widget=widget,name=widget:GetFullName(),prior=prior}
     widget.MinimapCapture=state.capture
     widget:UpdateSublevel()
     assert(finite(widget.CachedMapScale) and math.abs(widget.CachedMapScale-1024/state.capture_width)<1e-8,
            'radar_client_native_widget_scale_mismatch')
     assert(finite(widget.MapScale) and math.abs(widget.MapScale-widget.CachedMapScale)<1e-8,
            'radar_client_marker_scale_mismatch')
     assert(same(widget.MapTexture.Brush.ResourceObject,widget.Material),'radar_client_native_material_binding_mismatch')
     report('BASE_RADAR_CLIENT_WIDGET_BOUND|widget='..widget:GetFullName()..'|cachedScale='..widget.CachedMapScale..'|mapScale='..widget.MapScale..'|projectionWidthCm='..state.capture_width..'|zoom='..tostring(widget.CachedZoom))
    end
    if state.widgets[key] then
     assert(same(widget.MinimapCapture,state.capture) and same(widget.MapTexture.Brush.ResourceObject,widget.Material),'radar_client_widget_binding_changed')
     projected=projected+1
     if not state.manual_capture then
      signature('/Script/Engine.SceneCaptureComponent2D:CaptureScene',{})
      state.component:CaptureScene()
      state.manual_capture=true
      report('BASE_RADAR_CLIENT_CAPTURE_REQUESTED|source=bound_community_map')
     end
     if env.descriptor.radars_per_team~=0 and bind_native_radars(widget,state.widgets[key]) then bound=bound+1 end
    end
   end
  end
  state.widgets_seen=count;state.widgets_bound=bound
  return projected>0
 end
 function service.owned() return state end
 function service.retire(reason)
  if retired then return false end
  retired=true
  -- The exact owned client world/process remains the capture's native lifetime
  -- owner. Keep the resource record until that owner confirms teardown; do not
  -- destroy a still-bound capture or clear a native widget during map travel.
  if state then state.retired_reason=tostring(reason or 'caller');state.engine_records_retained=true end
  report('BASE_RADAR_CLIENT_RETIRED|reason='..tostring(reason or 'caller')..'|engineRecordsRetained=true')
  return true
 end
 return service
end

end)()
local releaseRadarBlueprintContracts=(function()
-- Original complete schemas; CPF_Parm-derived zero-argument calls.
return {["UpdateTexture"]={["path"]="/Game/UI/Components/Game/UI_Game_Map.UI_Game_Map_C:UpdateTexture",["parameters"]=0,["fields"]={["CallFunc_GetLevelTexture_Texture"]="ObjectProperty",["CallFunc_IsValid_ReturnValue"]="BoolProperty",["CallFunc_IsValid_ReturnValue_1"]="BoolProperty"}},["UpdateSublevel"]={["path"]="/Game/UI/Components/Game/UI_Game_Map.UI_Game_Map_C:UpdateSublevel",["parameters"]=0,["fields"]={["CallFunc_GetWorldSettings_ReturnValue"]="ObjectProperty",["CallFunc_Divide_DoubleDouble_ReturnValue"]="DoubleProperty",["CallFunc_Multiply_DoubleDouble_ReturnValue"]="DoubleProperty",["CallFunc_GetGameState_ReturnValue"]="ObjectProperty",["CallFunc_SelectFloat_ReturnValue"]="DoubleProperty",["CallFunc_Multiply_VectorFloat_ReturnValue"]="StructProperty",["CallFunc_Conv_VectorToVector2D_ReturnValue"]="StructProperty",["CallFunc_Add_Vector2DVector2D_ReturnValue"]="StructProperty",["CallFunc_Divide_DoubleDouble_B_ImplicitCast"]="DoubleProperty",["K2Node_VariableSet_DefaultMaxZoom_ImplicitCast"]="DoubleProperty",["CallFunc_SelectFloat_B_ImplicitCast"]="DoubleProperty",["CallFunc_SelectFloat_A_ImplicitCast"]="DoubleProperty",["CallFunc_Multiply_VectorFloat_B_ImplicitCast"]="DoubleProperty"}},["BindRadarSensors"]={["path"]="/Game/UI/Components/Game/UI_Game_Map.UI_Game_Map_C:BindRadarSensors",["parameters"]=0,["fields"]={["Temp_int_Array_Index_Variable"]="IntProperty",["CallFunc_Create_ReturnValue"]="ObjectProperty",["Temp_int_Loop_Counter_Variable"]="IntProperty",["CallFunc_AddChildToCanvas_ReturnValue"]="ObjectProperty",["CallFunc_Add_IntInt_ReturnValue"]="IntProperty",["CallFunc_GetObjectClass_ReturnValue"]="ClassProperty",["CallFunc_Map_Find_Value"]="DoubleProperty",["CallFunc_Map_Find_ReturnValue"]="BoolProperty",["Temp_real_Variable"]="DoubleProperty",["CallFunc_Conv_DoubleToVector_ReturnValue"]="StructProperty",["Temp_bool_Variable"]="BoolProperty",["CallFunc_GetAllActorsOfClass_OutActors"]="ArrayProperty",["CallFunc_Array_Get_Item"]="ObjectProperty",["K2Node_Select_Default"]="DoubleProperty",["CallFunc_MakeVector2D_ReturnValue"]="StructProperty",["CallFunc_K2_GetActorLocation_ReturnValue"]="StructProperty",["CallFunc_IsValid_ReturnValue"]="BoolProperty",["CallFunc_Multiply_VectorVector_ReturnValue"]="StructProperty",["CallFunc_Conv_VectorToVector2D_ReturnValue"]="StructProperty",["CallFunc_Array_Length_ReturnValue"]="IntProperty",["CallFunc_Add_Vector2DVector2D_ReturnValue"]="StructProperty",["CallFunc_Less_IntInt_ReturnValue"]="BoolProperty",["CallFunc_Conv_DoubleToVector_InDouble_ImplicitCast"]="DoubleProperty"}}}

end)()
local releaseRadarBoundsFactory=(function()
-- The cooked world supplies its own structures and terrain, including maps
-- with multiple meshes. Bounds choose camera height and clipping only.
return function(env)
 local valid,signature,scope=assert(env.valid),assert(env.signature),assert(env.scope)
 local function same(a,b) return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() end
 local function finite(n) return type(n)=='number' and n==n and n>-math.huge and n<math.huge end
 return function(context,descriptor,size)
  scope();assert(valid(context) and context:GetFullName():find(descriptor.world,1,true),'radar_bounds_selected_world_required')
  local group=assert(community_radar_group(descriptor),'radar_bounds_community_package_required')
  local assetPrefix='StaticMesh /Game/Community/'..group..'/'
  local levelPrefix='StaticMesh /Game/Maps/Community/'..group..'/'
  signature('/Script/Engine.Actor:GetActorBounds',{{'bOnlyCollidingComponents','BoolProperty',0},{'Origin','StructProperty',8},{'BoxExtent','StructProperty',32},{'bIncludeFromChildActors','BoolProperty',56}})
  signature('/Script/Engine.PrimitiveComponent:GetCollisionEnabled',{{'ReturnValue','ByteProperty',0}})
  signature('/Script/Engine.PrimitiveComponent:GetCollisionObjectType',{{'ReturnValue','ByteProperty',0}})
  local world=context:GetWorld();local half=size/2
  local owned={bottom=math.huge,top=-math.huge,count=0}
  local shared={bottom=math.huge,top=-math.huge,count=0}
  for _,actor in ipairs(FindAllOf('StaticMeshActor') or {}) do
   if valid(actor) and same(actor:GetWorld(),world) and not actor.bHidden then
    local c=actor.StaticMeshComponent;local mesh=valid(c) and c.StaticMesh or nil
    if valid(mesh) and same(c:GetOwner(),actor) and same(c:GetWorld(),world)
     and not c.bHiddenInGame and c:GetCollisionEnabled()~=0 and c:GetCollisionObjectType()==0 then
     local origin,extent={},{};actor:GetActorBounds(true,origin,extent,false)
     if finite(origin.X) and finite(extent.X) and extent.X>=0 and math.abs(origin.X)<=half+extent.X
      and finite(origin.Y) and finite(extent.Y) and extent.Y>=0 and math.abs(origin.Y)<=half+extent.Y
      and finite(origin.Z) and finite(extent.Z) and extent.Z>=0 then
      local name=mesh:GetFullName()
      local bounds=(name:sub(1,#assetPrefix)==assetPrefix or name:sub(1,#levelPrefix)==levelPrefix) and owned or shared
      bounds.bottom=math.min(bounds.bottom,origin.Z-extent.Z)
      bounds.top=math.max(bounds.top,origin.Z+extent.Z)
      bounds.count=bounds.count+1
     end
    end
   end
  end
  local bounds=owned.count>0 and owned or shared
  if bounds.count==0 then return 0,0,0 end
  return bounds.bottom,bounds.top,bounds.count
 end
end

end)()
local releaseNativeWorldSettingsFactory=(function()
-- The original UILibrary selects UWorld's actual native settings object.
-- The client reads the capture width from the loaded level.
return function(env)
 local valid,signature,scope,report=assert(env.valid),assert(env.signature),assert(env.scope),assert(env.report)
 local library=nil;local emitted={}
 return function(context,descriptor)
  scope();assert(valid(context) and type(descriptor)=='table' and context:GetFullName():find(descriptor.world,1,true),'native_settings_selected_context_required')
  signature('/Script/ValhallaUI.UILibrary:GetWorldSettings',{{'WorldContextObject','ObjectProperty',0},{'ReturnValue','ObjectProperty',8}})
  if not valid(library) then library=StaticFindObject('/Script/ValhallaUI.Default__UILibrary') end
  assert(valid(library) and library:GetFullName()=='UILibrary /Script/ValhallaUI.Default__UILibrary','native_settings_original_library_required')
  local settings=library:GetWorldSettings(context);local world=context:GetWorld()
  local settingsClass='/Script/Valhalla.ValWorldSettings'
  if not valid(settings) or settings:GetClass():GetFullName()~='Class '..settingsClass then return nil end
  assert(valid(world) and valid(settings:GetWorld()) and settings:GetWorld():GetAddress()==world:GetAddress(),'native_settings_actual_same_world_owner_required')
  local size=settings.MapSize
  if not (type(size)=='number' and size>0 and size<math.huge) then return nil end
  local read,name=pcall(function() return settings.MapName:ToString() end)
  if not read or type(name)~='string' or not name:match('%S') then name=descriptor.name end
  local key=world:GetAddress()..'|'..settings:GetAddress()..'|'..settings:GetFullName()
  if not emitted[key] then
   emitted[key]=true
   report('BASE_WORLD_SETTINGS_NATIVE|map='..descriptor.name..'|size='..size..'|class='..settingsClass..'|mapName='..name:gsub('[\r\n|]',' '))
  end
  return settings
 end
end

end)()
local releaseRadarRuntimeFactory=(function()
-- Normal network clients only. Actual remote world owns map selection.
return function(env)
 local valid,report,scope=assert(env.valid),assert(env.report),assert(env.scope)
 local descriptors=assert(env.map_descriptors);local service=nil;local identity=nil;local retired={}
 local captureBounds=assert(env.capture_bounds_factory)(env)
 local guard=assert(env.guard_factory)(env)
 local nativeSettings=assert(env.world_settings_guard_factory)(env)
 local runtime={}
 function runtime.tick(pc,gs)
  scope();guard(pc,gs)
  assert(not pc:HasAuthority() and not gs:HasAuthority(),'radar_runtime_network_client_required')
  local world=pc:GetWorld();local name=gs:GetFullName();local key=name..'|'..gs:GetAddress()..'|'..world:GetAddress()
  if identity~=key then
   if service then service.retire('remote_world_changed');retired[#retired+1]=service end
   service=nil;identity=key
   local selected
   for _,descriptor in pairs(descriptors) do
    if community_radar_group(descriptor) and name:find(descriptor.world,1,true) then
     assert(not selected,'radar_runtime_ambiguous_actual_remote_map')
     selected=descriptor
    end
   end
   if not selected then return true end
   local e={};for k,v in pairs(env) do e[k]=v end
   e.world_prefix=selected.world;e.client_context_guard=guard;e.descriptor=selected;e.world_settings_guard=nativeSettings
   e.capture_bounds=captureBounds
   service=assert(env.helper_factory)(e)
  end
  if not service then return true end
  local ok,result=pcall(service.tick,pc,gs)
  if ok then return result end
  report('BASE_RADAR_CLIENT_ERROR|'..tostring(result):sub(1,500))
  service.retire('capture_failed');retired[#retired+1]=service;service=nil
  return false
 end
 function runtime.owned() return {current=service,identity=identity,retired=retired} end
 return runtime
end

end)()
local releaseRadarRuntime=releaseRadarRuntimeFactory({valid=valid,report=report,scope=scope,signature=signature,
 map_descriptors=mapDefinitions,guard_factory=releaseRadarGuardFactory,helper_factory=releaseRadarHelperFactory,
 capture_bounds_factory=releaseRadarBoundsFactory,world_settings_guard_factory=releaseNativeWorldSettingsFactory,blueprint_contracts=releaseRadarBlueprintContracts})

local postMatchEscapeBound=false
local observe_post_match_result
local function bind_post_match_escape(gs)
 if postMatchEscapeBound or not valid(gs) or gs:HasAuthority()
  or gs.r_GameplayPhaseInfo.Phase.TagName:ToString()~='GamePhase.GameplayEndedPhase' then return end
 local path='/Game/UI/RallyHereUpdates/UI_Scene_Result_Frontier_RH_v2.UI_Scene_Result_Frontier_RH_v2_C'
 local menuClass='WidgetBlueprintGeneratedClass /Game/UI/RallyHereUpdates/Shared/Scenes/UI_Scene_Menu_RH_v2.UI_Scene_Menu_RH_v2_C'
 local menuHide='/Script/RallyHereStart.RHWidget:OnHide'
 if not valid(StaticFindObject(menuHide)) then return end
 postMatchEscapeBound=true
 local pending,checked,failed,reported=false,false,false,false
 local closing
 local function same(a,b)
  return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() and a:GetFullName()==b:GetFullName()
 end
 local function results_world()
  scope()
  if stopped or failed then return end
  local gs=state()
  if not valid(gs) or gs:HasAuthority()
   or gs.r_GameplayPhaseInfo.Phase.TagName:ToString()~='GamePhase.GameplayEndedPhase' then return end
  return gs:GetWorld()
 end
 local function owns_widget(widget,world)
  if not valid(widget) or not same(widget:GetWorld(),world) then return false end
  local pc=widget:GetOwningPlayer()
  return valid(pc) and pc:IsLocalPlayerController() and not pc:HasAuthority() and same(pc:GetWorld(),world)
 end
 local function active_result()
  if closing then return end
  local world=results_world()
  if not valid(world) then return end
  local result=nil
  for _,widget in ipairs(FindAllOf('UI_Scene_Result_Frontier_RH_v2_C') or {}) do
   if owns_widget(widget,world) and widget:GetClass():GetFullName()=='WidgetBlueprintGeneratedClass '..path
    and widget:IsVisible() and widget:IsTopViewRoute() then
    if result then return end
    result=widget
   end
  end
  return result
 end
 local function fail(reason)
  pending=false
  if failed then return end
  failed=true
  report('POST_MATCH_ESCAPE_ERROR|'..tostring(reason))
 end
 local returning,resultAcceptsEscape=false,false
 observe_post_match_result=function()
  resultAcceptsEscape=active_result()~=nil
  if returning or not resultAcceptsEscape then return end
  returning=true
  report('POST_MATCH_SCOREBOARD_VISIBLE')
  ExecuteInGameThreadWithDelay(8000,function()
   scope()
   report('POST_MATCH_RETURN_READY')
  end)
 end
 local function on_escape()
  if not resultAcceptsEscape or closing or pending or failed or stopped then return end
  pending=true
  local queued,reason=pcall(ExecuteInGameThread,function()
   local ok,why=pcall(function()
    local result=active_result()
    if not result then pending=false;return end
    -- Let the normal press/release handler take the menu route first.
    ExecuteInGameThreadWithDelay(175,function()
     pending=false
     local handled,err=pcall(function()
      if not same(result,active_result()) then return end
      if not checked then signature(path..':OnNavigateMenu',{});checked=true end
      result:OnNavigateMenu()
      if not reported and result:GetViewManager():GetTopViewRoute():ToString()=='StartMenu' then
       reported=true;report('POST_MATCH_ESCAPE_MENU|route=StartMenu|nativeHandler=true')
      end
     end)
     if not handled then fail(err) end
    end)
   end)
   if not ok then fail(why) end
  end)
  if not queued then fail(reason) end
 end
 local ok,why=pcall(function()
  signature(menuHide,{})
  RegisterHook(menuHide,function(context)
   local observed,err=pcall(function()
    local world=results_world()
    local widget=context:get()
    if not valid(world) or not valid(widget) or widget:GetClass():GetFullName()~=menuClass
     or not owns_widget(widget,world) then return end
    -- A native Back can close StartMenu before the queued Escape callback.
    local token={}
    closing=token
    ExecuteInGameThreadWithDelay(250,function() if closing==token then closing=nil end end)
   end)
   if not observed then fail(err) end
  end)
  RegisterKeyBind(Key.ESCAPE,on_escape)
  report('POST_MATCH_ESCAPE_READY')
 end)
 if not ok then fail(why) end
end

local flagReleaseFactory=(function()
-- Initialize a detached flag proxy from its first authoritative movement update.
return function(env)
 local valid,scope,signature,report=env.valid,env.scope,env.signature,env.report
 local attach='/Script/Engine.Actor:OnRep_AttachmentReplication'
 local move='/Script/Engine.Actor:OnRep_ReplicatedMovement'
 local flagClass='BlueprintGeneratedClass /Game/Topaz/Pickups/BP_TopazPickup_Flag.BP_TopazPickup_Flag_C'
 local world=env.world
 local active,reported=true,false
 local pending={}
 local function same(a,b)return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()end
 local function bounded_vector(v)
  return type(v.X)=='number' and math.abs(v.X)<1e8
   and type(v.Y)=='number' and math.abs(v.Y)<1e8
   and type(v.Z)=='number' and math.abs(v.Z)<1e8
 end
 signature(attach,{})
 signature(move,{})
 signature('/Script/Engine.Actor:K2_SetActorLocation',{{'NewLocation','StructProperty',0},{'bSweep','BoolProperty',24},
  {'SweepHitResult','StructProperty',32},{'bTeleport','BoolProperty',264},{'ReturnValue','BoolProperty',265}})
 signature('/Script/Engine.GameplayStatics:RebaseZeroOriginOntoLocal',{{'WorldContextObject','ObjectProperty',0},
  {'WorldLocation','StructProperty',8},{'ReturnValue','StructProperty',32}})
 signature('/Script/Engine.GameplayStatics:GetTimeSeconds',{{'WorldContextObject','ObjectProperty',0},{'ReturnValue','DoubleProperty',8}})
 local statics=StaticFindObject('/Script/Engine.Default__GameplayStatics')
 assert(valid(statics),'flag_release_native_world_rebase_required')
 local function before_attach(context)
  local flag=context:get()
  if not active or not valid(flag) or flag:GetClass():GetFullName()~=flagClass
     or flag:HasAuthority() or not same(flag:GetWorld(),world) then return end
  scope()
  local root,holder=flag.RootComponent,flag.r_HeldBy
  if not valid(root) or not same(root:GetOwner(),flag) or not valid(root:GetAttachParent())
     or not valid(holder) then return end
  pending[flag:GetAddress()]={flag=flag,root=root,at=statics:GetTimeSeconds(world)}
 end
 local function on_movement(context)
  local flag=context:get()
  if not active or not valid(flag) then return end
  local id=flag:GetAddress()
  local release=pending[id]
  if not release then return end
  pending[id]=nil
  if not same(flag,release.flag) or not same(flag.RootComponent,release.root)
     or valid(release.root:GetAttachParent()) or valid(flag:GetOwner())
     or statics:GetTimeSeconds(world)-release.at>0.20 then return end
  local location=flag.ReplicatedMovement.Location
  if not bounded_vector(location) then return end
  local to=statics:RebaseZeroOriginOntoLocal(flag,{X=location.X,Y=location.Y,Z=location.Z})
  if not bounded_vector(to) then return end
  local from=flag:K2_GetActorLocation()
  local distance=(to.X-from.X)^2+(to.Y-from.Y)^2+(to.Z-from.Z)^2
  if distance<1 or distance>300^2 then return end
  if flag:K2_SetActorLocation({X=to.X,Y=to.Y,Z=to.Z},false,{},true) and not reported then
   reported=true
   report('FLAG_RELEASE_POSITION_SEEDED|distanceCm='..string.format('%.1f',math.sqrt(distance)))
  end
 end
 local function guarded(fn)
  return function(...)
   local ok,why=pcall(fn,...)
   if not ok and active then
    active=false;pending={}
    report('FLAG_RELEASE_HANDOFF_UNAVAILABLE|'..tostring(why))
   end
  end
 end
 local pre,post=RegisterHook(attach,guarded(before_attach),function()end)
 local ok,mp,mq=pcall(RegisterHook,move,function()end,guarded(on_movement))
 if not ok then UnregisterHook(attach,pre,post);error(mp) end
 return {retire=function()
  active=false;pending={}
  local detach=pcall(UnregisterHook,attach,pre,post)
  local movement=pcall(UnregisterHook,move,mp,mq)
  return detach and movement
 end}
end
end)()
local flagReleaseService,flagReleaseWorld
local function ensure_flag_release_handoff(gs)
 local world=gs:GetWorld()
 if valid(flagReleaseWorld) and flagReleaseWorld:GetAddress()==world:GetAddress() then return end
 if flagReleaseService then
  if not flagReleaseService.retire() then
   report('FLAG_RELEASE_HANDOFF_UNAVAILABLE|prior_hook_cleanup')
   return
  end
  flagReleaseService=nil
 end
 flagReleaseWorld=world
 local ok,service=pcall(flagReleaseFactory,{valid=valid,scope=scope,signature=signature,report=report,world=world})
 if ok then flagReleaseService=service
 else report('FLAG_RELEASE_HANDOFF_UNAVAILABLE|'..tostring(service)) end
end
local soundSettingsWorld, soundSettingsAttempts, soundSettingsApplied
local SOUND_SETTINGS_MAX_ATTEMPTS = 10
local function apply_saved_sound_settings(world)
    if not valid(world) then return end
    if not same_object(soundSettingsWorld, world) then
        soundSettingsWorld, soundSettingsAttempts, soundSettingsApplied = world, 0, false
    end
    if soundSettingsApplied or soundSettingsAttempts >= SOUND_SETTINGS_MAX_ATTEMPTS then return end
    soundSettingsAttempts = soundSettingsAttempts + 1
    local ok, why = pcall(function()
        signature('/Script/Engine.GameUserSettings:GetGameUserSettings',{{'ReturnValue','ObjectProperty',0}})
        signature('/Script/Valhalla.ValGameUserSettings:ApplySoundSettings',{})
        local defaults = loaded('/Script/Engine.Default__GameUserSettings',
                                'GameUserSettings /Script/Engine.Default__GameUserSettings')
        local settings = defaults:GetGameUserSettings()
        local class = loaded('/Script/Valhalla.ValGameUserSettings','Class /Script/Valhalla.ValGameUserSettings')
        assert(valid(settings) and settings:IsA(class),'native_sound_settings_required')
        settings:ApplySoundSettings()
    end)
    if ok then
        soundSettingsApplied = true
        report('SAVED_SOUND_SETTINGS_APPLIED')
    elseif soundSettingsAttempts == SOUND_SETTINGS_MAX_ATTEMPTS then
        report('SAVED_SOUND_SETTINGS_UNAVAILABLE|'..tostring(why):sub(1,300))
    end
    return ok
end

local update_match_music=(function()
    local busPath='/Game/Audio/Submixes/MUS_Game_Submix.MUS_Game_Submix'
    local soundtrack=@@MAP_SOUNDTRACK@@
    local world, bus, muted, failures
    local request, requestTime

    local function set_request(value, now)
        if not soundtrack or (value==request and (not value or now==requestTime)) then return end
        local file=io.open(soundtrack.directory..'/map-soundtrack-request','wb')
        if not file then return end
        file:write(value or '')
        file:close()
        request,requestTime=value,now
    end

    local function track_ready(map, now)
        local file=io.open(soundtrack.directory..'/map-soundtrack-ready','rb')
        if not file then return false end
        local raw=file:read(96) or ''
        file:close()
        local name, stamp=raw:match('^(%w[%w_]*) (%d+)$')
        stamp=tonumber(stamp)
        return name==map and stamp and stamp<=now and now-stamp<2
    end

    local function saved_sound_levels()
        local config=io.open(@@MUSIC_SETTINGS@@,'rb')
        if not config then return end
        local raw=config:read(1048577)
        config:close()
        if not raw or #raw>1048576 then return end
        if raw:sub(1,2)=='\255\254' or raw:sub(1,2)=='\254\255' then raw=raw:sub(3):gsub('%z','') end
        raw=raw:gsub('^\239\187\191','')
        local row
        for entry in ('\n'..raw):gmatch('[\r\n]SavedSettingsConfig%s*=%s*([^\r\n]*)') do row=entry end
        if not row then return end
        local music=tonumber(row:match('"MusicSoundVolume"%s*,%s*"([^"]+)"'))
        local master=tonumber(row:match('"MasterSoundVolume"%s*,%s*"([^"]+)"'))
        return music,master
    end

    return function(pc,gs)
        if not pc or not gs then set_request(nil,os.time()); return end
        local current=pc:GetWorld()
        if not valid(current) then return end
        local worldChanged=not same_object(current,world)
        if worldChanged then world=current;failures=0 end
        if failures>=3 then return end
        local ok,why=pcall(function()
            local music,master=saved_sound_levels()
            local now=os.time()
            local route
            if soundtrack then
                local fullname=gs:GetFullName()
                for _, row in pairs(mapDefinitions) do
                    if row.music_route and soundtrack.routes[row.music_route] and fullname:find(row.world,1,true) then
                        route=row.music_route
                        break
                    end
                end
            end
            local playing=route and gs.r_GameplayPhaseInfo.Phase.TagName:ToString()=='GamePhase.GameplayStartPhase'
            local ready=playing and track_ready(route,now)
            local wantMute=music==0 or ready==true
            if wantMute or (muted and (music~=nil or soundtrack)) then
                if not valid(bus) then
                    signature('/Script/Engine.SoundSubmix:SetSubmixOutputVolume',
                              {{'WorldContextObject','ObjectProperty',0},{'InOutputVolume','FloatProperty',8}})
                    bus=LoadAsset(busPath)
                    assert(valid(bus) and bus:GetFullName()=='SoundSubmix '..busPath,'match_music_submix_required')
                end
                -- Native sound settings can refresh the mixer during a phase.
                bus:SetSubmixOutputVolume(pc,wantMute and 0.0 or 1.0)
                if worldChanged or muted~=wantMute then report('MATCH_MUSIC_MUTE|'..tostring(wantMute)) end
                muted=wantMute
            end
            local gain=math.max(0,math.min(1,music or 1))*math.max(0,math.min(1,master or 1))
            set_request(route and string.format('%s %d %d',route,math.floor(gain*1000+0.5),ready and 1 or 0),now)
        end)
        if ok then failures=0
        else
            set_request(nil,os.time())
            failures=failures+1
            if failures==3 then report('MATCH_MUSIC_MUTE_UNAVAILABLE|'..tostring(why):sub(1,300)) end
        end
    end
end)()

local shieldWallPreviewChecked=false
local function configure_shield_wall_preview()
 if shieldWallPreviewChecked then return end
 shieldWallPreviewChecked=true
 local ok,why=pcall(function()
  local asset='/Game/Topaz/Abilities/Packs/ForceField/GA_Pack_ForceField'
  local class=LoadAsset(asset..'.GA_Pack_ForceField_C')
  local defaults=StaticFindObject(asset..'.Default__GA_Pack_ForceField_C')
  assert(valid(class) and class:GetFullName()=='BlueprintGeneratedClass '..asset..'.GA_Pack_ForceField_C'
   and valid(defaults) and defaults:IsA(class) and type(defaults.AlwaysUsePreview)=='boolean','shield_wall_preview_defaults_required')
  defaults.AlwaysUsePreview=true
  assert(defaults.AlwaysUsePreview==true,'shield_wall_preview_defaults_readback_failed')
 end)
 if not ok then report('SHIELD_WALL_PREVIEW_ERROR|'..tostring(why)) end
end
local configure_community_lighting=(function()
    -- Preserve the tuned properties when a newer cook supplies its own values.
    local profiles={
        ['/Game/Maps/Community/MinotaurT2/Arena_MinotaurT2_2026_P.Arena_MinotaurT2_2026_P:']={
            map='MinotaurT22026', sky=6, targetSky=3,
        },
        ['/Game/Maps/Community/BeggarsRunTWLT2/Arena_BeggarsRunTWLT2_2026_P.Arena_BeggarsRunTWLT2_2026_P:']={
            map='BeggarsRunTWLT22026', sky=9, targetSky=4,
        },
        ['/Game/Maps/Community/QuagmireTWLT2/Arena_QuagmireTWLT2_2026_P.Arena_QuagmireTWLT2_2026_P:']={
            map='QuagmireTWLT22026', sky=6, targetSky=3,
            fog={
                {field='FogDensity', setter='SetFogDensity', authored=0.45, target=0.14},
                {field='StartDistance', setter='SetStartDistance', authored=1575, target=3000},
                {field='FogMaxOpacity', setter='SetFogMaxOpacity', authored=1, target=0.82},
            },
        },
    }
    local attemptedWorld
    local function near(value,expected)
        return type(value)=='number' and math.abs(value-expected)<0.0001
    end
    local function component(world,prefix,kind,property)
        local path=prefix..'PersistentLevel.'..kind..'_0'
        local actor=StaticFindObject(path)
        if valid(actor) and actor:GetFullName()==kind..' '..path and same_object(actor:GetWorld(),world) then
            local owned=actor[property]
            if valid(owned) then return owned end
        end
    end
    return function(gs)
        local prefix=gs:GetFullName():match(' (/Game/[^ ]+:)PersistentLevel%.')
        local profile=profiles[prefix]
        if not profile then return end
        local world=gs:GetWorld()
        if not valid(world) or same_object(world,attemptedWorld) then return end
        local ok,why=pcall(function()
            local sky=component(world,prefix,'SkyLight','LightComponent')
            if not sky then return end
            local fog
            if profile.fog then
                fog=component(world,prefix,'ExponentialHeightFog','Component')
                if not fog then return end
            end
            attemptedWorld=world
            local matchesCook=near(sky.Intensity,profile.sky)
            for _,setting in ipairs(profile.fog or {}) do
                matchesCook=matchesCook and near(fog[setting.field],setting.authored)
            end
            if not matchesCook then
                report('COMMUNITY_MAP_LIGHTING_SKIPPED|map='..profile.map..'|authored_values_changed')
                return
            end
            signature('/Script/Engine.SkyLightComponent:SetIntensity',{{'NewIntensity','FloatProperty',0}})
            for _,setting in ipairs(profile.fog or {}) do
                signature('/Script/Engine.ExponentialHeightFogComponent:'..setting.setter,{{'Value','FloatProperty',0}})
            end
            sky:SetIntensity(profile.targetSky)
            assert(near(sky.Intensity,profile.targetSky),'skylight_intensity_readback_failed')
            for _,setting in ipairs(profile.fog or {}) do
                fog[setting.setter](fog,setting.target)
                assert(near(fog[setting.field],setting.target),setting.field..'_readback_failed')
            end
            report('COMMUNITY_MAP_LIGHTING_APPLIED|map='..profile.map)
        end)
        if not ok then
            attemptedWorld=world
            report('COMMUNITY_MAP_LIGHTING_UNAVAILABLE|map='..profile.map..'|'..tostring(why):sub(1,300))
        end
    end
end)()

local configure_stock_clouds=(function()
    local descriptor=mapDefinitions[@@STOCK_CLOUD_MAP@@]
    local attemptedWorld
    return function(gs,sys)
        if not descriptor or not gs:GetFullName():find(descriptor.world,1,true) then return end
        local world=gs:GetWorld()
        if not valid(world) or same_object(world,attemptedWorld) then return end
        local spawned
        local ok,why=pcall(function()
            local cloud
            for _,actor in ipairs(FindAllOf('VolumetricCloud') or {}) do
                if valid(actor) and same_object(actor:GetWorld(),world) then
                    assert(not cloud,'multiple_volumetric_clouds')
                    cloud=actor
                end
            end
            local myrkwood=descriptor.name=='KatabaticMyrkwood'
            if not cloud and not myrkwood then return end
            attemptedWorld=world
            local path='/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst.m_SimpleVolumetricCloud_Inst'
            local material=StaticFindObject(path)
            if not valid(material) then material=LoadAsset(path) end
            assert(valid(material) and material:GetFullName()=='MaterialInstanceConstant '..path,'stock_cloud_material_required')
            if not cloud then
                local class=loaded('/Script/Engine.VolumetricCloud','Class /Script/Engine.VolumetricCloud')
                spawned=world:SpawnActor(class,{X=0,Y=0,Z=0},{Pitch=0,Yaw=0,Roll=0})
                cloud=spawned
            end
            assert(valid(cloud) and same_object(cloud:GetWorld(),world),'volumetric_cloud_actor_required')
            local component=cloud.VolumetricCloudComponent
            assert(valid(component),'volumetric_cloud_component_required')
            component:SetMaterial(material)
            assert(same_object(component.Material,material),'stock_cloud_material_readback_failed')
            if descriptor.name~='Stonehenge2026' and component.ViewSampleCountScale<1 then
                component:SetViewSampleCountScale(1.0)
                assert(component.ViewSampleCountScale==1.0,'stock_cloud_sample_count_readback_failed')
            end
            if spawned or descriptor.name=='Stonehenge2026' then
                component:SetLayerBottomAltitude(3.5)
                component:SetLayerHeight(4.0)
                assert(component.LayerBottomAltitude==3.5 and component.LayerHeight==4.0,'stock_cloud_layer_readback_failed')
            end
            if descriptor.name~='Stonehenge2026' then
                -- Shipping clients ignore -ini overrides. Configure the
                -- native temporal reconstruction path in the selected world.
                sys:ExecuteConsoleCommand(gs,'r.VolumetricRenderTarget.Mode 2',nil)
                sys:ExecuteConsoleCommand(gs,'r.VolumetricRenderTarget 1',nil)
                assert(sys:GetConsoleVariableIntValue('r.VolumetricRenderTarget.Mode')==2 and
                       sys:GetConsoleVariableIntValue('r.VolumetricRenderTarget')==1,'stock_cloud_temporal_mode_readback_failed')
                report('STOCK_CLOUD_TEMPORAL_RECONSTRUCTION|map='..descriptor.name..'|mode=2')
            end
            report('STOCK_CLOUD_PROFILE_APPLIED|map='..descriptor.name)
        end)
        if not ok then
            attemptedWorld=world
            if valid(spawned) then pcall(function() spawned:K2_DestroyActor() end) end
            report('STOCK_CLOUD_PROFILE_UNAVAILABLE|'..tostring(why))
        end
    end
end)()

local function client_tick(sys)
    if joined and os.time()-lastJoin>=30 then
        local modes=FindAllOf('TopGameMode_Topaz') or {}
        if #modes==1 and valid(modes[1]) and modes[1]:GetFullName():find('/Game/Maps/Active/Drydock/Arena_Drydock_P.Arena_Drydock_P:',1,true) and sys:IsStandalone(modes[1]) then
            joined=false;report('RECONNECTING_TO_FIXED_SERVER')
        end
    end
    if not joined then
        local modes=FindAllOf("TopGameMode_Topaz") or {};if #modes~=1 or not valid(modes[1]) then return end
        local gm=modes[1]
        assert(gm:GetClass():GetFullName()==MODE and gm:GetFullName():find("/Game/Maps/Active/Drydock/Arena_Drydock_P.Arena_Drydock_P:",1,true) and gm:HasAuthority() and sys:IsStandalone(gm)==true,"initial_standalone_drydock_required")
        apply_saved_sound_settings(gm:GetWorld())
        signature("/Script/Engine.GameplayStatics:OpenLevel",{{"WorldContextObject","ObjectProperty",0},{"LevelName","NameProperty",8},{"bAbsolute","BoolProperty",16},{"Options","StrProperty",24}})
        local name=FName(DESTINATION);assert(name:ToString()==DESTINATION)
        joined=true;lastJoin=os.time();report("JOIN_REQUESTED")
        loaded("/Script/Engine.Default__GameplayStatics","GameplayStatics /Script/Engine.Default__GameplayStatics"):OpenLevel(gm,name,true,SPECTATOR_ROLE=="spectator" and "SpectatorOnly=1" or "")
        return
    end
    local gs=state();if not gs or gs:HasAuthority() then return end
    configure_geometry(gs)
    configure_community_lighting(gs)
    configure_stock_clouds(gs,sys)
    if clientWorld~=gs:GetFullName() then clientWorld=gs:GetFullName();report("CLIENT_WORLD|"..clientWorld) end
    local pcs=FindAllOf("ValPlayerController") or {};if #pcs~=1 or not valid(pcs[1]) then return end
    local pc=pcs[1];if not pc:IsLocalPlayerController() or pc:HasAuthority() then return end
    local world=pc:GetWorld()
    local settingsApplied=same_object(world,gs:GetWorld()) and apply_saved_sound_settings(world)
    if not valid(pc.PlayerState) then return end
    configure_weather(gs,pc)
    configure_base_lighting(gs)
    configure_water(gs,pc)
    local ps=pc.PlayerState
    if SPECTATOR_ROLE=="spectator" then
        if not spectatorRuntime then spectatorRuntime=assert(loadfile(@@SPECTATOR_RUNTIME@@))()({valid=valid,scope=scope,signature=signature,report=report,lease_id=SPECTATOR_LEASE,watch_id=SPECTATOR_WATCH,material_factory=assert(loadfile(@@SPECTATOR_MATERIAL_RUNTIME@@))()})end
        spectatorRuntime.tick(pc,ps,gs);return
    end
    assert(SPECTATOR_ROLE=="player","unknown_client_role")
    if nativeSpectatorPresentation~=false and (nativeSpectatorPresentation or ps.r_bDead==true) then
        local ok,why=pcall(function()
            if not nativeSpectatorPresentation then
                nativeSpectatorPresentation=assert(loadfile(@@SPECTATOR_RUNTIME@@))()({
                    valid=valid,scope=scope,signature=signature,report=report,passive=true,
                    material_factory=assert(loadfile(@@SPECTATOR_MATERIAL_RUNTIME@@))()
                })
            end
            nativeSpectatorPresentation.observe_native(pc,ps,gs)
        end)
        if not ok then
            nativeSpectatorPresentation=false
            report('NATIVE_SPECTATOR_PRESENTATION_ERROR|'..tostring(why))
        end
    end
    local pawnReady=valid(pc.Pawn) and pc.Pawn.bInitialized==true
    update_match_music(pc,gs,settingsApplied)
    configure_shield_wall_preview()
    if not scoreBarFailed then
        local ok,why=pcall(refresh_ctf_score_bar,pc,ps,gs)
        if not ok then scoreBarFailed=true;report('CTF_SCORE_BAR_ERROR|'..tostring(why):sub(1,300)) end
    end
    if not shockLanceVisualFailed then
        local ok,why=pcall(configure_shock_lance)
        if not ok then shockLanceVisualFailed=true;report('SHOCK_LANCE_CAMERA_EFFECTS_ERROR|'..tostring(why):sub(1,300)) end
    end
    ensure_flag_release_handoff(gs)
    bind_post_match_escape(gs)
    if observe_post_match_result then observe_post_match_result() end
    local plc=pc.PlayerLoadoutComponent;if not valid(plc) then return end
    local r=player_record(pc,ps)
    if pawnReady then
        observe_markers(pc,ps,gs)
        releaseRadarRuntime.tick(pc,gs)
        if not r.ready then r.ready=true;report("REMOTE_PAWN_READY|role=client") end
        return
    end
    if r.selectionAttempted or valid(pc.Pawn) or (ps.r_TeamId~=1 and ps.r_TeamId~=2) or not plc:IsComponentReady() then return end
    local choices=plc.r_PlayerLoadouts;if choices:GetArrayNum()==0 then return end;assert(choices:GetArrayNum()<=64)
    local chosen=nil
    choices:ForEach(function(i,element)
        assert(i<64);local item=element:get();assert(item:GetFullName()=="ScriptStruct /Script/Valhalla.PlayerLoadout")
        local id=item.LoadoutId;assert(type(id)=="number" and id%1==0 and id>0);if chosen==nil then chosen=id end
    end)
    assert(chosen~=nil)
    signature("/Script/Valhalla.PlayerLoadoutComponent:RequestLoadout",{{"LoadoutId","IntProperty",0}})
    r.selectionAttempted=true;plc:RequestLoadout(chosen);report("LOADOUT_REQUESTED|"..chosen)
end
local schedule
schedule=function()
    if stopped then return end
    assert(nextHandle==nil)
    local owned
    local function callback()
        if stopped then return end
        local ok,why=pcall(function()
            assert(owned~=nil and owned==nextHandle);nextHandle=nil
            client_tick(scope())
            schedule()
        end)
        if not ok then stopped=true;report("RUNTIME_ERROR|"..tostring(why)) end
    end
    local ok,handle=pcall(ExecuteInGameThreadWithDelay,1000,callback)
    if not ok or type(handle)~="number" or handle%1~=0 then stopped=true;report("RUNTIME_ERROR|timer_registration_unknown_no_retry");return end
    owned=handle;nextHandle=handle
end
report("RUNTIME_LOADED|client");schedule()
