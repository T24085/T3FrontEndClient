"""Verified waves in one isolated native CTF process, with durable boundaries."""
import json
import csv
import math
import time

from defense_learning import lua_tactics
import offense_learning
from practice import HERE, check_between_matches
from train import publish, read_ready, replace_once


def wave_plan(trainer, wave):
    """Only generated numeric tactics and route data enter this private command."""
    def literal(value):
        if value is None:
            return 'nil'
        if isinstance(value, dict):
            return '{' + ','.join('['+literal(key)+']='+literal(item) for key, item in value.items()) + '}'
        if isinstance(value, str):
            return json.dumps(value)
        if type(value) in (int, float):
            import math
            if not math.isfinite(value):
                raise ValueError('Non-finite wave command.')
            return str(value)
        raise ValueError('Unsupported wave command.')

    assignments = {}
    for index, plan in trainer.guided.items():
        assignments[index] = dict(name=plan['approach_route'], layout=plan.get('layout'),
            runup=plan['pass_runup_cm'], guidance=plan['guidance'], **plan['policy'])
    flight = getattr(trainer, 'flight_plan', None)
    return ('return {wave='+str(wave)+',guided='+literal(assignments)
            +',defense_tactics='+lua_tactics(trainer.defense_tactics)
            +',offense_tactics='+lua_tactics(trainer.offense_tactics, offense_learning.TACTICS)
            +',aim_boosts='+literal(trainer.aim_boosts)
            +(',flight_plan='+literal(flight) if flight is not None else '')+'}\n')


def instrument(text, script='team_match.lua'):
    path = json.dumps((HERE/script).as_posix())
    text = replace_once(text, f' local train=assert(loadfile({path}))()({{', ' local training_env={')
    text = replace_once(text, 'scope=scope,signature=signature,report=report,valid=valid\n })',
        'scope=scope,signature=signature,report=report,valid=valid,wave=1\n }\n'
        f' local training_factory=assert(loadfile({path}))()\n'
        ' local train=training_factory(training_env)\n'
        f' local wave_reset=assert(loadfile({json.dumps((HERE/"team_wave_reset.lua").as_posix())}))()(training_env)')
    text = replace_once(text, '  if training_started then return end\n', '''  if training_started then
   if not training_env.wave_finished then return end
   local next_wave=training_env.wave+1
   local command=io.open(training_env.path..'/team-next-'..next_wave..'.lua','r')
   if not command then return end
   command:close()
   if not wave_reset.reset(gm,gs,entries) then return end
   local plan=assert(loadfile(training_env.path..'/team-next-'..next_wave..'.lua'))()
   assert(plan.wave==next_wave,'training_reuse_unverified|command_sequence')
   for key,value in pairs(plan) do training_env[key]=value end
   training_env.wave_finished=false
   train=training_factory(training_env)
   entries={};state=nil;reported=false;deadline=nil;last_observed=nil;training_started=false;training_settle=nil
  end
''')
    text = replace_once(text, 'entries[#entries+1]={bot=bot,team=team}',
        'entries[#entries+1]={bot=bot,team=team,training_spawn=bot:K2_GetActorLocation(),'
        'training_facing=start:K2_GetActorRotation()}')
    # A held bot cannot vacate its start. Try the regular row on each anchor
    # before probing other positions near the same team's selected anchors.
    spawn_script = json.dumps((HERE/'team_spawn.lua').as_posix())
    floor_script = json.dumps((HERE/'team_spawn_floor.lua').as_posix())
    text = replace_once(text, ' local function spawn_next(gm,state,requested_team)',
        f' local training_spawn=assert(loadfile({spawn_script}))()\n'
        f' local make_training_floor=assert(loadfile({floor_script}))()\n'
        ' local training_floor\n'
        ' local function spawn_next(gm,state,requested_team)')
    text = replace_once(text, '  local bot=state.library:SpawnBotFromDataWithTeamId', '''  local ordinal=0
  for _,entry in ipairs(entries) do if entry.team==team then ordinal=ordinal+1 end end
  local slot=#entries+1
  if state.training_spawn_slot~=slot then
   state.training_spawn_slot=slot;state.training_spawn_attempt=0
  end
  local position,fallback=training_spawn(start,ordinal,#starts,state.training_spawn_attempt)
  state.training_spawn_attempt=state.training_spawn_attempt+1
  training_floor=training_floor or make_training_floor(valid,signature)
  if not training_floor(start,position) then
   report('BOT_TEAM_SPAWN_NO_FLOOR|team='..team..'|slot='..slot..'|attempt='..state.training_spawn_attempt)
   return
  end
  local bot=state.library:SpawnBotFromDataWithTeamId''')
    text = replace_once(text, '   start:K2_GetActorLocation(),start:K2_GetActorRotation(),false,gm,nil)',
        '   position,start:K2_GetActorRotation(),false,gm,nil)')
    text = replace_once(text, '   entries[#entries+1]={bot=bot,team=team,training_spawn=',
        "   assert(type(bot.bCanBeDamaged)=='boolean','training_bot_damage_flag_unknown')\n"
        '   bot.bCanBeDamaged=false\n   entries[#entries+1]={bot=bot,team=team,training_spawn=')
    text = replace_once(text, '   bot.bCanBeDamaged=false\n   entries[#entries+1]',
        "   bot.bCanBeDamaged=false\n   if fallback then report('BOT_TEAM_ALTERNATE_SPAWN|team='..team..'|slot='..slot..'|pattern='..fallback) end\n"
        '   entries[#entries+1]')
    text = replace_once(text, "  if tree:IsRunning()~=true then return false end",
        "  if tree:IsRunning()~=true and not entry.training_held then return false end")
    text = replace_once(text, "  return true\n end\n local state", "  wave_reset.hold(entry)\n  return true\n end\n local state")
    # wave_reset is declared later than activate_bot; use a forward local.
    text = replace_once(text, ' local function activate_bot(', ' local wave_reset\n local function activate_bot(')
    text = replace_once(text, ' local training_started=false', ' local training_started=false\n local training_settle')
    text = replace_once(text, '  if ready==env.bots then\n   reported=true',
        '  if ready==env.bots then\n   training_settle=training_settle or os.time()+20\n'
        "   if not wave_reset.ready(entries) then\n"
        "    assert(os.time()<training_settle,'training_reuse_unverified|fresh_resources_settle_timeout');return\n"
        '   end\n   reported=true')
    text = replace_once(text, ' local wave_reset=assert(loadfile(', ' wave_reset=assert(loadfile(')
    return replace_once(text, '   local ok, why=pcall(train,gm,gs,entries)',
        '   wave_reset.start(gm,gs,entries,training_env.wave)\n'
        '   local ok, why=pcall(train,gm,gs,entries)')


def run_waves(trainer, out, process):
    trainer.match = out
    began = getattr(trainer, 'began', time.monotonic())
    trainer.wave_began = began
    current = trainer
    trainer.completed_waves = 0
    for wave in range(1, trainer.waves_per_launch+1):
        check_between_matches()
        if wave > 1:
            current = trainer.next_match()
            # Lineup experiments may change class composition. Never mutate a
            # running roster into a different one or advance unsaved learning.
            if current.roster != trainer.roster:
                return
            current.base_equipment = getattr(trainer, 'base_equipment', False)
            publish(out/f'team-next-{wave}.lua', wave_plan(current, wave))
        current.read_match(out, process, wave)
        result = current.result
        result.update(session=out.name, session_wave=wave, verified_reuse=wave > 1,
                      wall_seconds=round(time.monotonic()-began, 2))
        trainer.save_match(current)
        trainer.completed_waves += 1
        began = time.monotonic()
        trainer.wave_began = began
        check_between_matches()
        if result.get('base_equipment_changed'):
            return


def evidence_path(out, wave, name):
    return out / (('wave-'+str(wave)+'-' if wave > 1 else '') + name)


def ready_receipt(trainer, out, process, wave):
    if wave > 1:
        value = trainer.wait(out, process,
            lambda _: read_ready(evidence_path(out, wave, 'team-ready.csv')), 180)
        if value != f'{wave},{len(trainer.roster)}\n':
            raise RuntimeError('training_reuse_unverified|missing_team_reset_receipt')
        validate_reset(out, wave, len(trainer.roster))


def validate_reset(out, wave, bots):
    def rows(number):
        try:
            with (out/f'team-reset-{number}.csv').open(newline='') as source:
                values = [{key: float(value) for key, value in row.items()} for row in csv.DictReader(source)]
            if len(values) != bots or any(row['bot'] != index for index, row in enumerate(values,1)):
                raise ValueError('roster')
            for row in values:
                if (not all(map(math.isfinite, row.values())) or row['health'] != row['max_health']
                        or row['energy'] < 99 or sum(row[key]**2 for key in ('vx_cm_s','vy_cm_s','vz_cm_s')) > 1):
                    raise ValueError('resources')
            return values
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError('training_reuse_unverified|invalid_team_reset_evidence') from exc
    fresh, current = rows(1), rows(wave)
    if any(sum((first[key]-second[key])**2 for key in ('x_cm','y_cm','z_cm')) > 1
           for first, second in zip(fresh,current)):
        raise RuntimeError('training_reuse_unverified|changed_team_start_positions')
