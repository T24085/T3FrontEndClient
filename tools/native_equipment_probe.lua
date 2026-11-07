-- Read-only current native loadout requests and selected-slot schemas.
return function(env)
 local valid,scope,report=env.valid,env.scope,env.report;local done=false
 local function value(o,n)
  local ok,v=pcall(function()return o[n]end);if not ok then return'unreadable'end
  if type(v)=='number'or type(v)=='boolean'or type(v)=='string'then return tostring(v)end
  ok,v=pcall(function()return v:ToString()end);return ok and v or'opaque'
 end
 local function fields(o,label)
  o:ForEachProperty(function(p)local n=p:GetFName():ToString();report('EQUIPMENT_FIELD|owner='..label..'|name='..n..'|type='..p:GetFullName()..'|value='..value(o,n))end)
 end
 local function probe(pc)
  if done or not valid(pc.Pawn)or not pc.Pawn.bInitialized then return end
  scope();assert(pc:IsLocalPlayerController()and not pc:HasAuthority(),'equipment_probe_local_owner')
  local plc=pc.PlayerLoadoutComponent;if not valid(plc)then return end
  done=true
  local class=plc:GetClass()
  for depth=1,5 do
   if not valid(class)then break end
   class:ForEachFunction(function(fn)
    local n=fn:GetFName():ToString()
    if n:find('Loadout',1,true)or n:find('Slot',1,true)or n:find('Ability',1,true)then
     local params={};fn:ForEachProperty(function(p)params[#params+1]=p:GetFullName()..'@'..p:GetOffset_Internal()end)
     report('EQUIPMENT_API|'..fn:GetFullName()..'|'..table.concat(params,';'))
    end
   end)
   class=class:GetSuperStruct()
  end
  local data=pc.PlayerState.r_PlayerLoadout
  fields(data,'selected_loadout')
  data.LoadoutSlots:ForEach(function(_,p)
   local slot=p:get();fields(slot,'selected_slot')
   for _,key in ipairs({'EquipSlot','LoadoutItem'})do
    local v=slot[key];local ok,why=pcall(function()
     local schema=StaticFindObject(v:GetFullName());assert(valid(schema),'slot_schema_required')
     schema:ForEachProperty(function(prop)local n=prop:GetFName():ToString();report('EQUIPMENT_NESTED|owner='..key..'|name='..n..'|type='..prop:GetFullName()..'|value='..value(v,n))end)
    end)
    if not ok then report('EQUIPMENT_NESTED_ERROR|'..key..'|'..tostring(why))end
   end
   local items={};local ok,why=pcall(function()plc:GetLoadoutEquipSlotItems(data.LoadoutId,slot.EquipSlot,items)end)
   report('EQUIPMENT_INVENTORY|slot='..value(slot.EquipSlot,'TagName')..'|ok='..tostring(ok)..'|count='..#items..'|detail='..tostring(why))
   if ok then for i,item in ipairs(items)do
    local ok,valueObject=pcall(function()return item:get()end)
    if ok then item=valueObject end
    report('EQUIPMENT_ITEM_TYPE|index='..i..'|type='..type(item)..'|value='..tostring(item))
    for _,key in ipairs({'ItemId','CustomName','GameplayTags','ItemSource'})do report('EQUIPMENT_ITEM|index='..i..'|name='..key..'|value='..value(item,key))end
   end end
  end)
  pc.Pawn.AbilitySystemComponent.ActivatableAbilities.Items:ForEach(function(_,p)
   local spec=p:get();if spec.InputID==5 and valid(spec.Ability)then report('EQUIPMENT_GUN|handle='..spec.Handle.Handle..'|class='..spec.Ability:GetClass():GetFullName())end
  end)
  report('EQUIPMENT_PROBE_COMPLETE|readonly=true')
 end
 return function(pc)local ok,why=pcall(probe,pc);if not ok then done=true;report('EQUIPMENT_PROBE_ERROR|'..tostring(why));report('EQUIPMENT_PROBE_COMPLETE|inventoryQualified=false')end end
end
