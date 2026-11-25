import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from lupa.lua54 import LuaRuntime

from dashboard_run import team_bot_metrics
from defense_learning import travel_reward_scale
from field_duel import pursuit_summary, qualified_pursuit_lead
from flight_training import measure_flight, qualified_flight_transfer, SCENARIO
from human_reference import import_recordings, load_reference
from mirrored_benchmark import archived_opponents, paired_results
from offense_learning import cap_windows
from practice import FIELDS


HERE = Path(__file__).resolve().parent


class FieldTrainingTest(unittest.TestCase):
    def test_open_travel_penalty_excludes_nearby_combat_and_grounded_skiing(self):
        raw = dict(phase='InProgress',vx_cm_s='330',vy_cm_s='0',grounded='1',ski='0',jet='0',
                   carrying='0',home_flag_cm='5000',enemy_flag_cm='6500')
        rows = [raw|dict(seconds=str(index/4),open_travel=open_travel,ski=ski)
                for index,(open_travel,ski) in enumerate([('1','0'),('0','0'),('1','1'),('1','1')])]
        data = team_bot_metrics(rows)
        self.assertEqual(data['ground_jog_seconds'],.5)
        self.assertEqual(data['open_travel_jog_ratio'],.5)
        self.assertEqual(travel_reward_scale(data['open_travel_jog_ratio']),.35)

    def test_pursuit_transfer_requires_confirmed_airborne_hits_on_both_sides(self):
        base = dict(chase_profile='short-lead',combat_complete=True,airborne_launches=2,
                    outcome='timeout',carrier_damage=500)
        rows = [dict(duel=base|dict(capper=side,airborne_hits=int(side == 1))) for side in (1,1,2,2)]
        self.assertFalse(pursuit_summary(rows)[0]['qualified'])
        rows[-1]['duel']['airborne_hits'] = 1
        self.assertTrue(pursuit_summary(rows)[0]['qualified'])

    def test_visible_carrier_gets_distinct_intercepts_and_sighting_expires(self):
        lua = LuaRuntime()
        factory = lua.execute((HERE/'field_tactics.lua').read_text())
        lua.eval('''function(factory)
            local spotted = true
            local function bot(id, role, x)
                return {index=id,role=role,pos={X=x,Y=0,Z=0},pawn={GetAddress=function() return id end,
                    CharacterMovement={Velocity={X=1400,Y=0,Z=0}}},
                    controller={LineOfSightTo=function() return spotted end}}
            end
            local first, second, heavy = bot(1,'Light defense',0), bot(2,'Medium defense',600), bot(3,'Heavy on flag',400)
            local enemy = bot(4,'Capper',3000)
            local observe = factory({signature=function() end},function(a,b) return math.abs(a.X-b.X) end)
            local groups, flags, stands = {{first,second,heavy},{enemy}}, {enemy.pawn}, {{X=0,Y=0,Z=0},{X=20000,Y=0,Z=0}}
            local intel, visible, jobs = observe(groups,flags,stands,0)
            assert(jobs[2].kind=='chase' and jobs[1].kind=='cutoff' and jobs[3]==nil and visible[1]==3000)
            assert(jobs[1].target.X > enemy.pos.X)
            spotted = false
            enemy.pos = {X=6000,Y=0,Z=0}
            intel,visible,jobs = observe(groups,flags,stands,1)
            assert(intel[1][4].pos.X==3000 and visible[1]==nil and jobs[2].sighting.seen==0)
            intel,visible,jobs = observe(groups,flags,stands,4)
            assert(intel[1][4]==nil and jobs[1]==nil and jobs[2]==nil)
        end''')(factory)

    def test_benchmark_spawn_cohorts_are_disjoint_and_reusable(self):
        lua = LuaRuntime()
        split = lua.execute((HERE/'spawn_cohort.lua').read_text())
        lua.eval('''function(split)
            local function pool()
                local starts = {{},{}}
                for t=1,2 do for i=8,1,-1 do
                    starts[t][#starts[t]+1]={GetFullName=function() return tostring(i) end}
                end end
                return starts
            end
            local train, first, other = pool(),pool(),pool()
            split(train,false,1); split(first,true,1); split(other,true,2)
            assert(#train[1]==6 and #first[1]==2 and train[1][6]:GetFullName()=='6')
            assert(first[1][1]:GetFullName()=='7' and other[1][1]:GetFullName()=='8')
        end''')(split)

    def test_benchmark_excludes_unmatched_native_starts(self):
        blue = dict(benchmark_pair=1,candidate_team=1,blue=3,red=1,spawn_fingerprint=[[0,0,0]],opponent='Saved lineup 1')
        red = blue | dict(candidate_team=2,blue=1,red=3,spawn_fingerprint=[[0,0,1]])
        self.assertEqual(paired_results([blue,red])['excluded_pairs'],1)
        red['spawn_fingerprint'] = blue['spawn_fingerprint']
        self.assertEqual(paired_results([blue,red])['mean_margin'],4)

    def test_benchmark_rotates_distinct_archived_opponents(self):
        role = 'Light defense'
        defense = SimpleNamespace(history={role:{'Native':[],'Close':[],'Far':[]}})
        offense = SimpleNamespace(history={})
        def match(tactic):
            return dict(bots=[dict(bot=1,team=1,role=role)],defense_tactics={'1':tactic})
        archived = archived_opponents([('older',[match('Far')]),('newer',[match('Close')])],
                                      dict(baseline={role:'Native'}),defense,offense)
        self.assertEqual([item['tactics'][role] for item in archived],['Native','Close','Far'])

    def test_qualified_flight_and_pursuit_transfer_pin_the_map_revision(self):
        with TemporaryDirectory() as folder:
            runs = Path(folder)/'DashboardRuns'
            current = {'map_revision':'map:current'}
            for index,(mode,revision) in enumerate((('flight','old'),('flight','current'),('duel','current')),1):
                run = runs/f'run202611201201{index:02d}deadbeef'
                run.mkdir(parents=True)
                (run/'request.json').write_text(json.dumps(dict(mode=mode,map='HighOctane2026',
                                                               provenance={'map_revision':'map:'+revision})))
                checkpoint = dict(scenario=SCENARIO,course='recovery',
                                  comparison=dict(qualified=True,profile='short-jets' if revision=='old' else 'long-jets'),
                                  pursuit_profiles=[dict(qualified=True,profile='short-lead',score=.8)])
                (run/'progress.json').write_text(json.dumps(checkpoint))
            path = runs/'local-play'
            self.assertEqual(qualified_flight_transfer(path,'HighOctane2026',current)['recovery']['profile'],'long-jets')
            self.assertEqual(qualified_pursuit_lead(path,'HighOctane2026',current)['lead'],.35)

    def test_support_credit_requires_a_nearby_clear_and_same_carry(self):
        event = lambda seconds, name: dict(seconds=seconds,event=name,team=1,bot=1)
        frames = {4:{2:((100,0,0),0,0,False),3:((5000,0,0),0,0,False)}}
        match = dict(equipment_events=[dict(seconds=4,team=2,pos_cm=(0,0,0))],
                     events=[event(8,'flag_pickup'),event(22,'cap')])
        self.assertEqual(cap_windows(match,frames,1,{2,3}),{2:{(1,22)}})
        match['events'].append(event(13,'flag_lost'))
        self.assertEqual(cap_windows(match,frames,1,{2,3}),{})

    def test_recovery_requires_measured_lateral_shove_and_sustained_forward_speed(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'flight.csv'
            rows = ['0,0,0,900,1,0,1,32,0,0,500,0,9,0',
                    '.25,2,1300,0,0,1,1,27,200,50,400,0,9,0',
                    '.50,5,1500,0,0,1,1,21,500,50,300,0,9,0',
                    '.76,9,1700,0,1,0,1,20,900,50,200,0,9,0']
            header = 'seconds,forward_m,vx_cm_s,vy_cm_s,grounded,jet,ski,energy,x_cm,y_cm,z_cm,heading_deg,course_drop_m,cross_m\n'
            path.write_text(header+'\n'.join(rows)+'\n')
            measured = measure_flight(path,'recovery',strict=True)
            self.assertEqual(measured['recovery_seconds'],.76)
            rows[0] = rows[0].replace(',900,',',0,')
            path.write_text(header+'\n'.join(rows)+'\n')
            with self.assertRaisesRegex(ValueError,'sideways shove'):
                measure_flight(path,'recovery',strict=True)

    def test_human_reference_requires_three_unique_active_traces(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            catalog = base/'catalog.json'
            catalog.write_text(json.dumps(dict(map_fingerprints={'HighOctane2026':'a'*64})))
            config = dict(runs=str(base/'Sessions'),map_catalog=str(catalog))
            for index in range(3):
                path = base/f'recording-{index}.csv'
                with path.open('w',newline='') as source:
                    writer = csv.writer(source)
                    writer.writerow(FIELDS.split(','))
                    for frame in range(350):
                        writer.writerow((1,frame*.05,1,frame*100,0,0,1600,0,0,0,0,25+index,
                                         int(frame%40 < 20),1,0,1,int(frame%40>=20)))
                result = import_recordings(config,'HighOctane2026',[path,path])
                self.assertEqual(result['recordings'],index+1)
                if index < 2:
                    self.assertEqual(load_reference(config,'HighOctane2026'),{})
            self.assertGreater(load_reference(config,'HighOctane2026')['jet_reserve'],0)
