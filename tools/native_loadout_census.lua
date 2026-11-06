-- Read-only local-player loadout/menu observations for private qualification.
return function(env)
 local valid,report,scope=assert(env.valid),assert(env.report),assert(env.scope)
 local seen={}
 local function same(a,b)return valid(a)and valid(b)and a:GetAddress()==b:GetAddress()end
 local function fields(object,prefix)
  if not valid(object)then return end
  local cls=object:GetClass();local count=0
  for depth=1,6 do
   if not valid(cls)then break end
   cls:ForEachFunction(function(fn)
    local name=fn:GetFName():ToString()
    if name:find('Loadout',1,true)or name:find('Inventory',1,true)or name:find('Scene',1,true)or name:find('Menu',1,true)or name:find('View',1,true)or name:find('ItemAsset',1,true)then
     count=count+1;assert(count<=256,'loadout_api_bound')
     local params={};fn:ForEachProperty(function(p)params[#params+1]=p:GetFullName()..'@'..p:GetOffset_Internal()end)
     report('LOADOUT_API|'..prefix..'|'..fn:GetFullName()..'|'..table.concat(params,';'))
    end
   end)
   cls=cls:GetSuperStruct()
  end
 end
 local function scalar_struct(value,label)
  if type(value)=='userdata'then
   local ok,unwrapped=pcall(function()return value:get()end)
   if ok then value=unwrapped end
  end
  if type(value)=='table'then
   local parts={};for k,v in pairs(value)do if type(v)=='number'or type(v)=='boolean'or type(v)=='string'then parts[#parts+1]=k..'='..tostring(v)end end
   report('LOADOUT_VALUE|'..label..'|'..table.concat(parts,';'));return
  end
  local parts={}
  value:ForEachProperty(function(p)
   local name=p:GetFName():ToString();local kind=p:GetFullName():match('^(%S+) ')
   if kind=='IntProperty'or kind=='ByteProperty'or kind=='BoolProperty'then parts[#parts+1]=name..'='..tostring(value[name])
   elseif kind=='ArrayProperty'then parts[#parts+1]=name..'.count='..value[name]:GetArrayNum()
   elseif kind=='StructProperty'then
    local s=value[name];s:ForEachProperty(function(nested)
     if nested:GetFName():ToString()=='TagName'then parts[#parts+1]=name..'='..s.TagName:ToString()end
    end)
   end
  end)
  report('LOADOUT_VALUE|'..label..'|'..table.concat(parts,';'))
 end
 return function(pc,ps,gs)
  scope();assert(valid(pc)and pc:IsLocalPlayerController()and not pc:HasAuthority()and same(pc.PlayerState,ps),'loadout_local_owner_required')
  local plc=pc.PlayerLoadoutComponent
  if not valid(plc)or not plc:IsComponentReady()or not valid(pc.Pawn)or not pc.Pawn.bInitialized then return end
  local key=pc:GetFullName()..'@'..pc:GetAddress();if seen[key]then return end;seen[key]=true
  local ok,why=pcall(function()
   fields(plc,'component');fields(pc,'controller');if valid(pc.MyHUD)then fields(pc.MyHUD,'hud')end
   report('LOADOUT_COMPONENT|ready='..tostring(plc:IsComponentReady())..'|choices='..plc.r_PlayerLoadouts:GetArrayNum()..'|selected='..ps.r_PlayerLoadout.LoadoutId)
   plc.r_PlayerLoadouts:ForEach(function(_,entry)
    local loadout=entry:get();scalar_struct(loadout,'choice')
    loadout.LoadoutSlots:ForEach(function(_,slot)scalar_struct(slot:get(),'choice'..loadout.LoadoutId..'.slot')end)
   end)
   for _,name in ipairs({'GetEquippedLoadoutItem','GetLoadoutEquipSlotItems'})do
    local fn=StaticFindObject('/Script/Valhalla.PlayerLoadoutComponent:'..name)
    if valid(fn)then fn:ForEachProperty(function(p)report('LOADOUT_PARAMETER|'..p:GetFullName()..'@'..p:GetOffset_Internal())end)end
   end
   local function asset_lookup(owner,name,id,label)
    local out={}
    local ok,result=pcall(function()return owner[name](owner,id,out)end)
    local values={}
    for k,v in pairs(out)do
     local inspected,identity=pcall(function()return v:GetFullName()end)
     values[#values+1]=tostring(k)..'='..(inspected and identity or tostring(v))
    end
    report('LOADOUT_ASSET|'..label..'|id='..id..'|call='..tostring(ok)..'|return='..tostring(result)..'|out='..table.concat(values,';'))
   end
   local library=StaticFindObject('/Script/Valhalla.Default__ValBlueprintLibrary')
   local fn=StaticFindObject('/Script/Valhalla.ValBlueprintLibrary:GetValItemAsset')
   if valid(fn)then fn:ForEachProperty(function(p)report('LOADOUT_PARAMETER|'..p:GetFullName()..'@'..p:GetOffset_Internal())end)end
   for _,slotName in ipairs({'EquipSlot.WeaponSlot.1','EquipSlot.WeaponSlot.2','EquipSlot.WeaponSlot.3'})do
    local slot={TagName=FName(slotName)};local item={};local options={}
    local got,result=pcall(function()return plc:GetEquippedLoadoutItem(ps.r_PlayerLoadout.LoadoutId,slot,item)end)
    report('LOADOUT_EQUIPPED|slot='..slotName..'|call='..tostring(got)..'|return='..tostring(result));if got then scalar_struct(item,slotName..'.equipped')end
    local success,err=pcall(function()plc:GetLoadoutEquipSlotItems(ps.r_PlayerLoadout.LoadoutId,slot,options)end)
    report('LOADOUT_OPTIONS|slot='..slotName..'|call='..tostring(success)..'|count='..#options..'|error='..tostring(err))
    if success then for i,option in ipairs(options)do
     local inspected,why=pcall(function()
      local value=option
      if type(value)=='userdata'then local ok,v=pcall(function()return value:get()end);if ok then value=v end end
      scalar_struct(value,slotName..'.option'..i)
      local id=value.ItemId
      asset_lookup(plc,'GetItemAsset',id,'component')
      if valid(library)then asset_lookup(library,'GetValItemAsset',id,'library')end
     end)
     if not inspected then report('LOADOUT_OPTION_ERROR|'..tostring(why))end
    end end
   end
   local widgets=FindAllOf('WBP_ClassLoadoutOptionSection_C')or{}
   report('LOADOUT_SECTIONS|count='..#widgets)
   for _,widget in ipairs(widgets)do if valid(widget)then report('LOADOUT_SECTION|class='..widget:GetFullName()..'|loadout='..widget.CachedLoadoutId..'|slot='..widget.DefaultEquipSlot.TagName:ToString()..'|options='..widget.CachedOptions:GetArrayNum())end end
  end)
  if not ok then report('LOADOUT_CENSUS_ERROR|'..tostring(why))end
 end
end
