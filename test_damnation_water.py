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

    def test_authored_profiles_use_pack_and_map_overrides_through_native_effect_calls(self):
        self.lua.execute('''
            local factory,contact,surface,profiles,tier=assert(loadfile(liquid_runtime))()
            local prefix='/Game/Community/Water/Audio/'
            local packs={{format=1,profiles={pool={minimum=500,medium=800,hard=2000,
                   sounds={medium=prefix..'S.S',exit=prefix..'E.E'},attenuation=prefix..'A.A'}}},
                   {format=2,profiles={pool={minimum=2000}}}}
            local liquid={id='TestPool',liquid_type='pool',splash_pool_tag='CwSplash',
                          box_min_cm={-1000,-1000,-100},box_max_cm={1000,1000,0},surface_z_cm=0,
                          overrides={minimum=600},tint={.2,.3,.4}}
            local row=surface(liquid,profiles(packs,function()end))
            assert(row.profile.minimum==600 and row.profile.medium==800)
            assert(tier(row.profile,700,'enter')=='easy' and tier(row.profile,1400,'enter')=='medium')
            assert(tier(row.profile,2205,'enter')=='hard' and tier(row.profile,2205,'exit')=='exit')
            assert(not pcall(surface,{id='bad',liquid_type='pool',splash_pool_tag='CwSplash',
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
                return {}
            end
            function LoadAsset(path)
                local kind=path==prefix..'A.A' and attenuation_class or sound_class
                return {path=path,IsA=function(_,class)return class==kind end}
            end
            function ExecuteInGameThreadWithDelay(ms,cb)assert(ms==50);nextTick=cb end
            local tick=factory({valid=function(v)return v~=nil and v~=false end,
                descriptors={{name='TestMap',world='TestMap:',liquids={false,liquid},liquid_profile_packs=packs}},
                report=function(line)events[#events+1]=line end})
            tick(gs,pc);nextTick()
            z=-35;t=.05;nextTick()
            assert(sounds[1]==prefix..'S.S' and actor.impact.Z==23 and actor.hidden==false)
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
