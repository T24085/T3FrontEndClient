"""Check splash contact math without launching the retail game."""

import unittest
from pathlib import Path

try:
    from lupa.lua54 import LuaRuntime
except ImportError:
    LuaRuntime = None


@unittest.skipUnless(LuaRuntime, "Lua 5.4 test runtime required")
class DamnationWaterContactTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        source = Path(__file__).parent / "lua" / "damnation_water.lua"
        self.lua.globals().liquid_runtime = source.as_posix()
        _, self.contact, *_ = self.lua.execute(source.read_text(encoding="utf-8"))
        self.surface = self.lua.table(z=100, xmin=0, xmax=1000, ymin=0, ymax=1000)

    def point(self, x, z):
        return self.lua.table(X=x, Y=200, Z=z)

    def test_basin_entry_and_exit_interpolate_at_the_waterline(self):
        a, b = self.point(200, 170), self.point(400, 30)
        for previous, current, direction in ((a, b, "enter"), (b, a, "exit")):
            self.assertEqual(self.contact(previous, current, self.surface, .05), (300, 200, 2800, direction))

    def test_dry_ground_parallel_flight_and_small_bobbing_do_not_splash(self):
        for a, b in ((self.point(1100, 200), self.point(1300, 0)),
                     (self.point(0, 200), self.point(100, 190)),
                     (self.point(200, 102), self.point(200, 98))):
            self.assertIsNone(self.contact(a, b, self.surface, .05))

    def test_ski_landing_registers_above_surface_and_takeoff_does_not(self):
        self.surface.ski = True
        a, b = self.point(200, 150), self.point(300, 112)
        self.assertEqual(self.contact(a, b, self.surface, .05), (300, 200, 760, "enter"))
        self.assertIsNone(self.contact(b, a, self.surface, .05))

    def test_authored_river_keeps_its_map_sounds_without_a_separate_profile_pack(self):
        self.lua.execute('''
            local _,_,surface,profiles=assert(loadfile(liquid_runtime))()
            local sound='/Game/Community/ReversionTWLT2/Edition2026/Audio/SW_RVT2_Splash_Medium.SW_RVT2_Splash_Medium'
            local row=surface({
                id='ReversionWater',liquid_type='river_water',splash_pool_tag='CwSplash',
                box_min_cm={-100,-100,-100},box_max_cm={100,100,100},surface_z_cm=0,
                proposed_global_assets={sounds={medium=sound}},
            },profiles(nil,function()end))
            assert(row.profile.sounds.medium==sound and row.tag=='CwSplash')
        ''')

    def test_authored_water_uses_stock_audio_when_a_wave_is_missing(self):
        self.lua.execute('''
            local factory,contact,surface,profiles,tier=assert(loadfile(liquid_runtime))()
            local prefix='/Game/Community/Water/Audio/'
            local packs={{format=1,profiles={river_water={minimum=500,medium=800,hard=2000,
                   sounds={medium=prefix..'S.S',exit=prefix..'E.E'},attenuation=prefix..'A.A'}}},
                   {format=2,profiles={river_water={minimum=2000}}}}
            local liquid={id='TestPool',liquid_type='river_water',splash_pool_tag='CwSplash',
                          box_min_cm={-1000,-1000,-100},box_max_cm={1000,1000,0},surface_z_cm=0,
                          overrides={minimum=600},tint={.2,.3,.4}}
            local row=surface(liquid,profiles(packs,function()end))
            assert(row.profile.minimum==600 and row.profile.medium==800)
            assert(tier(row.profile,700,'enter')=='easy' and tier(row.profile,1400,'enter')=='medium')
            assert(tier(row.profile,2205,'enter')=='hard' and tier(row.profile,2205,'exit')=='exit')
            assert(not pcall(surface,{id='bad',liquid_type='river_water',splash_pool_tag='CwSplash',
                box_min_cm={-1000,-1000,-100},box_max_cm={1000,1000,0},surface_z_cm=20},profiles(packs,function()end)))
            local t,nextTick,z,camera=0,nil,35,{X=20,Y=20,Z=150}
            local world={GetAddress=function()return 1 end}
            local fromWorld=function()return world end
            local events, sounds={},{}
            local sound_class,attenuation_class={},{}
            local material={SetScalarParameterValue=function()end}
            function material:SetVectorParameterValue(name,value) assert(name=='SplashColor' and value.Y==.3) end
            local mesh={GetMaterial=function()return {}end,SetMaterial=function()end,
                        GetCollisionEnabled=function()return 0 end}
            local tag={get=function()return {ToString=function()return 'CwSplash' end}end}
            local actor={GetWorld=fromWorld,StaticMeshComponent=mesh,Tags={ForEach=function(_,f)f(1,tag)end}}
            function actor:K2_TeleportTo(p)self.impact=p; return true end
            function actor:SetActorScale3D()end
            function actor:SetActorHiddenInGame(value)self.hidden=value end
            function FindAllOf(class)assert(class=='StaticMeshActor');return {actor}end
            function FName(value)return value end
            local pawn={GetAddress=function()return 2 end,bInitialized=true,IsA=function()return true end,
                K2_GetActorLocation=function()return {X=40,Y=45,Z=z+20}end,
                CapsuleComponent={GetScaledCapsuleHalfHeight=function()return 20 end}}
            local player={GetWorld=fromWorld,GetPawn=function()return pawn end}
            local gs={GetFullName=function()return 'TestMap:PersistentLevel.State' end,GetWorld=fromWorld,
                PlayerArray={ForEach=function(_,f)f(1,{get=function()return player end})end}}
            local pc={PlayerCameraManager={GetCameraLocation=function()return camera end}}
            local statics={GetTimeSeconds=function()return t end}
            math.random=function()return 1 end
            function statics:SpawnSoundAtLocation(context,asset,p,rotation,gain,pitch,start,attenuation,concurrency,automatic)
                assert(context==gs and automatic and start==0 and math.abs(pitch-1.06)<.00001)
                local base_gain=#sounds==0 and .71 or .42
                assert(math.abs(gain-base_gain*1.10)<.00001 and asset and attenuation and p.Z==0)
                sounds[#sounds+1]=asset.path
            end
            function StaticFindObject(path)
                if path:find('GameplayStatics') then return statics end
                if path:find('KismetMaterialLibrary') then return {CreateDynamicMaterialInstance=function()return material end} end
                if path=='/Script/Engine.SoundBase' then return sound_class end
                if path=='/Script/Engine.SoundAttenuation' then return attenuation_class end
                if path=='/Script/Valhalla.ValCharacter' then return {} end
            end
            function LoadAsset(path)
                if path==prefix..'S.S' then return nil end
                local kind=path==prefix..'A.A' and attenuation_class or sound_class
                return {path=path,IsA=function(_,class)return class==kind end}
            end
            function ExecuteInGameThreadWithDelay(ms,cb)assert(ms==50);nextTick=cb end
            local tick=factory({valid=function(v)return v~=nil and v~=false end,
                descriptors={{name='TestMap',world='TestMap:',liquids={false,liquid},liquid_profile_packs=packs}},
                report=function(line)events[#events+1]=line end})
            tick(gs,pc);nextTick()
            z=-35;t=.05;nextTick()
            assert(sounds[1]:find('Land_Water_02.Land_Water_02',1,true) and actor.impact.Z==23 and actor.hidden==false)
            t=.20;nextTick()
            z=35;t=.26;nextTick()
            assert(sounds[2]==prefix..'E.E')
            camera={X=20000,Y=20000,Z=20000}
            t=.43;nextTick();t=.47;z=-35;nextTick()
            assert(#sounds==2)
            local joined=table.concat(events,string.char(10))
            assert(joined:find('LIQUID_READY|map=TestMap',1,true) and joined:find('LIQUID_ENTRY_SKIPPED',1,true))
            assert(not joined:find('LIQUID_ERROR',1,true) and not joined:find('LIQUID_AUDIO_ERROR',1,true))
        ''')

    def test_community_water_uses_stock_sound_and_effect_without_a_descriptor(self):
        self.lua.execute('''
            local factory=assert(loadfile(liquid_runtime))()
            local water='/Game/Community/Stonehenge/Wildlands2026/Materials/M_Lake.M_Lake'
            local acid='/Game/Community/HighOctane/Toxic2026/Materials/M_Acid.M_Acid'
            local rain='/Game/Community/RaindanceT2/Edition2026/Water/'
            local world={GetAddress=function()return 1 end}
            local function fromWorld()return world end
            local function mesh(path,collision,offset,sheet)
                return {GetCollisionEnabled=function()return collision end,offset=offset,
                        StaticMesh=sheet and {GetFullName=function()return 'StaticMesh '..sheet end} or nil,
                        GetMaterial=function()return {GetFullName=function()return 'Material '..path end}end,
                        K2_LineTraceComponent=function(_,p)assert(collision~=0);return p.X>offset end}
            end
            local actors={}
            for _,component in ipairs({mesh(water,0,300),mesh(acid,1,600),mesh(water,1,0),
                                       mesh(rain..'M_RT2_Water.M_RT2_Water',0,900,rain..'SM_RT2_WaterSurface.SM_RT2_WaterSurface'),
                                       mesh(rain..'M_RT2_Water.M_RT2_Water',0,1200)}) do
                actors[#actors+1]={GetWorld=fromWorld,StaticMeshComponent=component}
            end
            function FindAllOf(kind)assert(kind=='StaticMeshActor');return actors end
            function FName(value)return value end
            local now,x,z,update=0,-30,150,nil
            local pawn={GetAddress=function()return 2 end,bInitialized=true,IsA=function()return true end,
                K2_GetActorLocation=function()return {X=x,Y=0,Z=z+80}end,
                CapsuleComponent={GetScaledCapsuleHalfHeight=function()return 80 end}}
            local player={GetWorld=fromWorld,GetPawn=function()return pawn end}
            local gs={GetFullName=function()return 'Class /Game/Maps/Community/Map.Test:PersistentLevel.State' end,
                GetWorld=fromWorld,PlayerArray={ForEach=function(_,f)f(1,{get=function()return player end})end}}
            local pc={PlayerCameraManager={GetCameraLocation=function()return {X=x,Y=0,Z=z+80}end}}
            local events,sounds,effects={},{},{}
            local sound_class,fx_class,character_class={},{},{}
            local statics={GetTimeSeconds=function()return now end}
            function statics:SpawnSoundAtLocation(context,asset,point)
                assert(context==gs and point.Z==100)
                sounds[#sounds+1]=asset.path
                return {}
            end
            local niagara={}
            function niagara:SpawnSystemAtLocation(context,asset,point,rotation,size,destroy,activate,pool)
                assert(context==gs and point.Z==106 and destroy and activate and pool==0)
                effects[#effects+1]=asset.path
                return {}
            end
            local system={}
            function system:GetComponentBounds(component,origin,extent)
                origin.Origin={X=component.offset,Y=0,Z=99}
                extent.BoxExtent={X=100,Y=100,Z=1}
            end
            function StaticFindObject(path)
                if path:find('GameplayStatics') then return statics end
                if path:find('KismetSystemLibrary') then return system end
                if path:find('NiagaraFunctionLibrary') then return niagara end
                if path=='/Script/Engine.SoundBase' then return sound_class end
                if path=='/Script/Niagara.NiagaraSystem' then return fx_class end
                if path=='/Script/Valhalla.ValCharacter' then return character_class end
            end
            function LoadAsset(path)
                local expected=path:find('/Game/Audio/',1,true) and sound_class or fx_class
                return {path=path,IsA=function(_,class)return class==expected end}
            end
            function ExecuteInGameThreadWithDelay(ms,cb)assert(ms==50);update=cb end
            local tick=factory({valid=function(v)return v~=nil end,report=function(e)events[#events+1]=e end})
            tick(gs,pc)
            assert(events[1]=='WATER_SPLASH_READY|surfaces=2|splash_pool=0')
            local function sample(at,height)
                now=now+.05;x=at;z=height;update()
            end
            sample(-30,150);sample(-30,102)
            sample(300,150);sample(300,102)
            sample(600,150);sample(600,102)
            sample(1200,150);sample(1200,90)
            sample(1010,150);sample(1010,90)
            assert(#sounds==0 and #effects==0)
            sample(1010,150)
            sample(50,150);sample(50,102)
            assert(#sounds==1 and sounds[1]:find('Land_Water_02.Land_Water_02',1,true))
            assert(#effects==1 and effects[1]:find('NS_Sprint_Footstep_WaterSplash_A',1,true))
            assert(events[2]=='WATER_SPLASH|tier=medium|fx=true|audio=true')
            for _=1,5 do sample(900,150) end
            sample(900,102)
            assert(#sounds==1 and #effects==1)
            sample(900,92)
            assert(events[3]=='WATER_SPLASH|tier=easy|fx=true|audio=true')
            for _=1,5 do sample(900,92) end
            sample(900,150)
            assert(events[4]=='WATER_SPLASH|tier=exit|fx=true|audio=true')
        ''')
