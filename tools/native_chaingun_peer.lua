-- Private second-client diagnostic. Original native callbacks only; no gameplay
-- writes, spawned objects, cue replay, RPC invocation, or rendering claims.
-- RegisterBeginPlayPostHook's callback shape is demonstrated by the packaged
-- pinned1ba38db4 BPModLoaderMod/Scripts/main.lua:275. No verified deregistration
-- API exists in retained evidence: that disabled callback stays owned through
-- the ORIGINAL client process lifetime, whose Job cleanup must be checked.
return function(env)
 local valid,scope,signature,report=assert(env.valid),assert(env.scope),assert(env.signature),assert(env.report)
 local world_getter,local_pawn,accept_source=assert(env.world),assert(env.local_pawn),assert(env.accept_source)
 assert(type(world_getter)=='function'and type(local_pawn)=='function'and type(accept_source)=='function','peer_observer_getters_required')
 local started,active=false,false;local hooks={};local begin_registered=false
 local rows,bytes=0,0;local seen={};local seen_count=0;local totals={};local partials={}
 local can_get_owner,can_get_av,can_read_tag=false,false,false
 local projectile_native,pawn_native
 local classes={}
 for _,variant in ipairs({'LightChaingun','Chaingun','ChainCannon'})do
  classes['BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/'..variant..'/BP_Projectile_Topaz_'..variant..'.BP_Projectile_Topaz_'..variant..'_C']=true
 end
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function safe(x)return tostring(x):gsub('[\r\n|]',' '):sub(1,230)end
 local function emit(kind,row,final)
  if rows>=(final and 64 or 62)or bytes>=96000 then return end
  local text='CHAINGUN_PEER_'..kind;local keys={};for k in pairs(row)do keys[#keys+1]=k end;table.sort(keys)
  for _,key in ipairs(keys)do text=text..'|'..key..'='..safe(row[key])end
  assert(#text<=3000,'peer_observer_record_bound');rows=rows+1;bytes=bytes+#text;report(text)
 end
 local function optional(fn)local ok,value=pcall(fn);if not ok then return 'unknown:'..safe(value)end;return value end
 local function partial(key,why)
  if partials[key]then return end;partials[key]=true;emit('COVERAGE_UNKNOWN',{subject=key,reason=why})
 end
 local function selected_source(source,world)
  local mine=local_pawn()
  if not valid(source)or not valid(mine)or same(source,mine)or not same(source:GetWorld(),world)or not same(mine:GetWorld(),world)then return false end
  if not source:IsA(pawn_native)then return false end
  return accept_source(source)==true
 end
 local function observe_projectile(actor,origin)
  if not active then return end;scope()
  local world=world_getter()
  if not valid(actor)or not valid(world)or not same(actor:GetWorld(),world)or not actor:IsA(projectile_native)then return end
  local class=actor:GetClass():GetFullName();if not classes[class]then return end
  totals[origin]=(totals[origin]or 0)+1
  local source=actor.Instigator
  if not selected_source(source,world)then
   totals.unresolved_or_other_source=(totals.unresolved_or_other_source or 0)+1
   return
  end
  totals.accepted_source_events=(totals.accepted_source_events or 0)+1
  local key=actor:GetFullName()..'@'..actor:GetAddress()
  if not seen[key]then
   if seen_count>=32 then partial('projectile_identity_budget','32_original_projectile_identities_observed');return end
   seen_count=seen_count+1;seen[key]=true
  end
  if rows>=62 then return end
  local row={origin=origin,actor=actor:GetFullName(),class=class,source=source:GetFullName(),sourceMatchesActualReplicatedShooter=true,sourceDiffersFromLocalPawn=true,
   authority=actor:HasAuthority(),renderedAppearance='unverified',scope='original_peer_native_actor_event_no_polling_absence_claim'}
  row.replicates=optional(function()local value=actor.bReplicates;assert(type(value)=='boolean');return value end)
  row.actorHidden=optional(function()return actor.bHidden end)
  row.stopped=optional(function()return actor.bStopped end)
  row.localProjectile=optional(function()local value=actor.bIsLocalProjectile;assert(type(value)=='boolean');return value end)
  row.trailComponent=optional(function()
   local trail=actor.NS_Projectile_Trail
   if not valid(trail)then return 'absent_at_this_callback'end
   assert(same(trail:GetWorld(),world),'peer_trail_foreign_world');return trail:GetFullName()
  end)
  row.actualTrailAsset=optional(function()local trail=actor.NS_Projectile_Trail;return valid(trail)and valid(trail.Asset)and trail.Asset:GetFullName()or'absent_at_this_callback'end)
  row.trailVisible=optional(function()local trail=actor.NS_Projectile_Trail;assert(valid(trail));return trail.bVisible end)
  row.trailHiddenInGame=optional(function()local trail=actor.NS_Projectile_Trail;assert(valid(trail));return trail.bHiddenInGame end)
  if can_get_av then
   local ok,av=pcall(function()return actor:GetAudioVisual()end)
   row.audioVisual=ok and valid(av)and av:GetFullName()or 'unknown_or_absent'
   if ok and valid(av)then row.trail3P=optional(function()local asset=av.ProjectileTrail3P;return valid(asset)and asset:GetFullName()or 'absent'end)end
  end
  emit('PROJECTILE',row)
 end
 local cues={
  {name='NetMulticast_InvokeGameplayCueExecuted_WithParams',schema={{'GameplayCueTag','StructProperty',0},{'PredictionKey','StructProperty',8},{'GameplayCueParameters','StructProperty',32}},tag=true},
  {name='NetMulticast_InvokeGameplayCueExecuted',schema={{'GameplayCueTag','StructProperty',0},{'PredictionKey','StructProperty',8},{'EffectContext','StructProperty',32}},tag=true},
  {name='NetMulticast_InvokeGameplayCueExecuted_FromSpec',schema={{'Spec','StructProperty',0},{'PredictionKey','StructProperty',120}},tag=false}
 }
 local function observe_cue(item,context,first_param)
  if not active then return end;scope()
  local world=world_getter();local asc=context:get()
  if not valid(world)or not valid(asc)or not same(asc:GetWorld(),world)then return end
  totals[item.name]=(totals[item.name]or 0)+1
  local source
  if can_get_owner then source=asc:GetOwner()end
  if not selected_source(source,world)then
   totals.unattributed_cue_calls=(totals.unattributed_cue_calls or 0)+1
   partial('cue_owner_attribution','native_ASC_owner_unavailable_or_does_not_match_actual_replicated_shooter')
   return
  end
  totals.accepted_source_cues=(totals.accepted_source_cues or 0)+1
  local row={method=item.name,context=asc:GetFullName(),source=source:GetFullName(),sourceMatchesActualReplicatedShooter=true,sourceDiffersFromLocalPawn=true,
   coverage='original_peer_native_multicast_handler_invocation',renderedAppearance='unverified',argumentWrites=0}
  if item.tag and can_read_tag then row.tag=optional(function()
   local value=first_param:get();assert(type(value)=='userdata','borrowed_native_GameplayTag_required')
   local name=value.TagName:ToString();assert(type(name)=='string'and #name<=256);return name
  end)end
  emit('CUE',row)
 end
 local function install(path,fields,callback)
  local ok,why=pcall(function()
   local fn=StaticFindObject(path);assert(valid(fn)and fn:GetFullName()=='Function '..path,'peer_exact_native_function_required')
   signature(path,fields)
   local pre,post=RegisterHook(path,callback,function()end)
   assert(type(pre)=='number'and type(post)=='number','peer_native_hook_handles_required')
   hooks[#hooks+1]={path=path,pre=pre,post=post,retained=true}
   emit('HOOK',{path=path,schemaValidated=true})
  end)
  if not ok then partial(path,why)end
 end
 local service={}
 function service.start()
  assert(not started,'peer_observer_single_start');scope();assert(valid(world_getter()),'peer_selected_world_required')
  projectile_native=StaticFindObject('/Script/Valhalla.ValProjectile');pawn_native=StaticFindObject('/Script/Engine.Pawn')
  assert(valid(projectile_native)and valid(pawn_native),'peer_native_class_identities_required')
  started=true;active=true
  local ok,why=pcall(function()signature('/Script/Engine.ActorComponent:GetOwner',{{'ReturnValue','ObjectProperty',0}})end)
  can_get_owner=ok;if not ok then partial('ASC_GetOwner',why)end
  ok,why=pcall(function()signature('/Script/Valhalla.ValProjectile:GetAudioVisual',{{'ReturnValue','ObjectProperty',0}})end)
  can_get_av=ok;if not ok then partial('GetAudioVisual',why)end
  ok,why=pcall(function()
   local cls=StaticFindObject('/Script/GameplayTags.GameplayTag');assert(valid(cls),'native_gameplay_tag_struct_required')
   local count=0;cls:ForEachProperty(function(p)
    count=count+1;assert(count==1 and p:GetFullName()=='NameProperty /Script/GameplayTags.GameplayTag:TagName'and p:GetOffset_Internal()==0,'native_gameplay_tag_schema_required')
   end);assert(count==1,'native_gameplay_tag_exact_schema_required')
  end)
  can_read_tag=ok;if not ok then partial('GameplayTag_schema',why)end
  for _,item in ipairs(cues)do
   install('/Script/GameplayAbilities.AbilitySystemComponent:'..item.name,item.schema,function(context,first_param)
    local worked,reason=pcall(observe_cue,item,context,first_param);if not worked then partial(item.name,reason)end
   end)
  end
  for _,item in ipairs({{'OnProjectileStopped',{{'HitResult','StructProperty',0}}},{'OnRep_PredictionID',{}},{'OnRep_ValProjReplicatedMovement',{}}})do
   install('/Script/Valhalla.ValProjectile:'..item[1],item[2],function(context)
    local worked,reason=pcall(function()observe_projectile(context:get(),item[1])end);if not worked then partial(item[1],reason)end
   end)
  end
  ok,why=pcall(function()
   assert(type(RegisterBeginPlayPostHook)=='function','pinned_begin_play_callback_API_unavailable')
   RegisterBeginPlayPostHook(function(context)
    if not active then return end
    local worked,reason=pcall(function()observe_projectile(context:get(),'begin_play_post')end)
    if not worked then partial('begin_play_post',reason)end
   end)
   begin_registered=true
  end)
  if not ok then partial('begin_play_registration',why)end
  emit('READY',{nativeFunctionHooks=#hooks,processLifetimeBeginPlayCallbacks=begin_registered and 1 or 0,recordBudget=64,renderedAppearance='unverified',stateWrites=0})
 end
 function service.stop()
  active=false
  local retained={}
  for _,hook in ipairs(hooks)do
   local ok,why=pcall(UnregisterHook,hook.path,hook.pre,hook.post)
   if not ok then hook.cleanupFailure=safe(why);retained[#retained+1]=hook end
  end
  hooks=retained
  local row={nativeFunctionHooksRetained=#hooks,beginPlayCallbackDisabled=begin_registered,processLifetimeRegistrationsRetained=begin_registered and 1 or 0,
   processLifetimeCleanup='requires_original_client_Job_active_process_count_zero',projectileIdentities=seen_count,renderedAppearance='unverified'}
  for key,value in pairs(totals)do row[key]=value end;emit('TOTALS',row,true)
  return {nativeFunctionHooksReleased=#hooks==0,callbackDisabled=not active,processLifetimeRegistrationsRetained=begin_registered and 1 or 0,requiresOriginalClientProcessCleanup=begin_registered}
 end
 function service.owned()return {hooks=hooks,totals=totals,projectileIdentities=seen_count,rows=rows,bytes=bytes,active=active,
  processLifetimeRegistrationsRetained=begin_registered and 1 or 0,requiresOriginalClientProcessCleanup=begin_registered}end
 return service
end
