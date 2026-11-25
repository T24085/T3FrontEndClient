import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from paired_flag_screen import SCREEN_ROUTES, ScreenTrainer, main
from practice import TrainingPaused
from train import METRICS, publish
from lupa.lua54 import LuaRuntime
from dashboard.serve_dashboard import read_screen_metrics


class ScreeningReuseTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rows = [dict(spawn=1, offset_cm=0, policy=dict(pulse=.25, period=1.8, ski=1,
                         turn=0, approach_cm=2200, flank=-1), pass_runup_cm=9500, guidance=4,
                         approach_route='left')]

    def prepare(self, trials=2, verified=True):
        for trial in range(1, trials + 1):
            metrics = dict.fromkeys(METRICS, 0)
            metrics.update(id=trial, seconds=30, start_energy=100)
            prefix = f'lane-1-'
            publish(self.root/f'{prefix}result-{trial}.csv', ','.join(str(metrics[key]) for key in METRICS))
            publish(self.root/f'{prefix}contact-{trial}.csv', '0')
            publish(self.root/f'{prefix}pass-{trial}.csv', '0,100,100,0,0')
            if trial > 1 and verified:
                publish(self.root/f'{prefix}verified-reset-{trial}.csv', '1\n')

    def test_two_waves_have_distinct_trace_and_command_files(self):
        self.prepare()
        saved = []
        trainer = ScreenTrainer(self.rows, waves_per_launch=2, next_wave=lambda:self.rows,
                                save_wave=lambda *args:saved.append(args))
        trainer.wait = lambda out, process, ready, seconds: ready('BOT_SCREEN_READY|1|3')
        trainer.run(self.root, None)
        self.assertEqual(trainer.completed_waves, 2)
        self.assertEqual([args[3] for args in saved], [1, 2])
        self.assertTrue(saved[0][1][0]['trace'].endswith('trace-1.csv'))
        self.assertTrue(saved[1][1][0]['trace'].endswith('trace-2.csv'))
        self.assertTrue((self.root/'lane-1-trial-2.csv').is_file())

    def test_warm_wave_requires_native_reset_receipt(self):
        self.prepare(verified=False)
        trainer = ScreenTrainer(self.rows)
        trainer.wait = lambda out, process, ready, seconds: ready('')
        with self.assertRaisesRegex(RuntimeError, 'missing_reset_receipt'):
            trainer.run_wave(self.root, None, 2)

    def test_pause_keeps_completed_wave_and_does_not_launch_the_next(self):
        self.prepare()
        saved = []
        trainer = ScreenTrainer(self.rows, waves_per_launch=2, next_wave=lambda:self.rows,
                                save_wave=lambda *args:saved.append(args))
        trainer.wait = lambda out, process, ready, seconds: ready('BOT_SCREEN_READY|1|3')
        with patch('paired_flag_screen.check_between_matches', side_effect=[None, TrainingPaused()]):
            with self.assertRaises(TrainingPaused):
                trainer.run(self.root, None)
        self.assertEqual(len(saved), 1)
        self.assertFalse((self.root/'lane-1-trial-2.csv').exists())

    def test_reset_checks_effect_state_and_rejects_changed_abilities(self):
        lua = LuaRuntime()
        factory = lua.execute(Path(__file__).with_name('verify_trial_reset.lua').read_text())
        exercise = lua.eval('''function(factory)
            local spec = {Handle={Handle=1},ActiveCount=0,InputPressed=false}
            local pawn = {CharacterMovement={bIsJetpackActive=false,IsSkiing=function() return false end}}
            pawn.GetHealth = function() return 100 end
            pawn.GetHealthMax = function() return 100 end
            pawn.GetEnergy = function() return 100 end
            pawn.AbilitySystemComponent = {
                ActiveGameplayEffects={GameplayEffects_Internal={ForEach=function(_, fn)
                    fn(1,{get=function() return {Spec={Def={GetFullName=function() return 'Passive' end},
                        StackCount=1,Duration=-1,Period=0},StartWorldTime=0,bIsInhibited=false} end})
                end}},
                ActivatableAbilities={Items={ForEach=function(_, fn)
                    fn(1,{get=function() return spec end})
                end}}
            }
            StaticFindObject=function() return {} end
            FindAllOf=function() return {} end
            local check=factory({valid=function(x) return x~=nil end,
                report=function() end,signature=function() end,reset_participants={pawn}}, {},pawn)
            assert(check(false))
            assert(check(true))
            spec.ActiveCount=1
            local ok,why=check(true)
            assert(not ok and why=='active_effects_or_abilities')
        end''')
        exercise(factory)

    def test_failed_warm_reset_preserves_wave_and_finishes_with_fresh_hosts(self):
        prior = self.root/'prior.json'
        route = dict(policy=self.rows[0]['policy'], runup_cm=9500, guidance=4)
        publish(prior, json.dumps(dict(attempts=[], configuration=dict(routes={name:route for name in SCREEN_ROUTES}))))
        config = self.root/'config.json'
        publish(config, json.dumps(dict(runs=str(self.root/'sessions'))))
        output = self.root/'results'
        launches = []

        def native_start(config, trainer):
            launches.append(trainer.waves_per_launch)
            trainer.match = self.root/'sessions'/str(len(launches))
            execution = trainer.match/'host/execution'
            execution.mkdir(parents=True)
            publish(execution/'execution.json', '{"job_active_processes_after_cleanup":0}')
            trainer.save_wave(trainer.rows, [], 100, 1, trainer.match)
            trainer.completed_waves = 1
            if len(launches) == 1:
                raise RuntimeError('training_reuse_unverified|pawn_resources_or_input')

        args = ['screen', str(config), str(prior), str(output), '--five-bots', '--matches', '3',
                '--bots', '1', '--waves-per-launch', '2']
        with patch('sys.argv', args), patch('paired_flag_screen.start', side_effect=native_start), \
                patch('paired_flag_screen.Campaign.retire_game_copy') as cleanup:
            main()
            self.assertEqual(cleanup.call_count, 3)
            main()
        report = json.loads((output/'progress.json').read_bytes())
        self.assertEqual(launches, [2, 1, 1])
        self.assertEqual(len(report['waves']), 3)
        self.assertEqual(report['reset_fallbacks'][0]['after_wave'], 1)

    def test_dashboard_resolves_warm_wave_metrics_and_rejects_wrong_lane(self):
        session = self.root/'Sessions/training-20261119-010000-abcdef12'
        session.mkdir(parents=True)
        trace = session/'lane-1-trace-2.csv'
        trace.touch()
        metrics = dict.fromkeys(METRICS, 0)
        metrics.update(id=2, average_kmh=88, jet_frames=30, ski_frames=120)
        publish(session/'lane-1-result-2.csv', ','.join(str(metrics[key]) for key in METRICS))
        self.assertEqual(read_screen_metrics(self.root, trace, 1),
                         dict(average_kmh=88, jet_frames=30, ski_frames=120))
        with self.assertRaises(ValueError):
            read_screen_metrics(self.root, trace, 2)


if __name__ == '__main__':
    unittest.main()
