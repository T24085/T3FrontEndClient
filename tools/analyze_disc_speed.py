"""Analyze bounded native disc observations without launching or changing a game."""
import argparse,hashlib,json,math
from pathlib import Path


def observations(path):
    raw=Path(path).read_bytes()
    if len(raw)>1024*1024:raise ValueError('Native events exceed their bound.')
    result=[]
    for line in raw.decode('utf-8',errors='replace').splitlines():
        if not line.startswith('DISC_SPEED_'):continue
        fields=line.split('|');row={'kind':fields[0]}
        for field in fields[1:]:
            if '='in field:
                key,value=field.split('=',1);row[key]=value
        result.append(row)
    return result


def vector(text):
    values=tuple(float(value)for value in text.split(','))
    if len(values)!=3 or not all(math.isfinite(v)for v in values):raise ValueError('Invalid native vector.')
    return values


def analyze(client_events,server_events):
    result={'passed':True,'scope':'Original Light Spinfusor launch speed and airborne forward/lateral inheritance and travel in an isolated loopback fixture. Character launch is controlled; projectile properties remain native. Stationary shots can hit existing geometry, so their later position samples do not qualify clear-flight travel. This does not establish off-site presentation or prediction quality.','roles':{}}
    for role,path in [('client',client_events),('host',server_events)]:
        rows=observations(path)
        if any(row.get('role')!=role for row in rows):raise ValueError('Native observation role differs from its evidence file.')
        if any(r['kind']=='DISC_SPEED_ERROR'for r in rows):raise ValueError('Native diagnostic reported an error.')
        defaults=[r for r in rows if r['kind']=='DISC_SPEED_DEFAULTS']
        if len(defaults)!=1:raise ValueError('Exactly one original class-default observation required per role.')
        default={name:float(defaults[0][name])for name in ('initial','max','forward','lateral')}
        if default!={'initial':13500.,'max':27000.,'forward':1.,'lateral':0.}:raise ValueError('Original Light Spinfusor defaults differ from the decoded reference.')
        groups={'stationary':[],'forward':[],'lateral':[]};shots=[];launch_speeds={};shot_groups={}
        for row in rows:
            if row['kind']!='DISC_SPEED_PROJECTILE':continue
            v=vector(row['velocity']);source=vector(row['sourceVelocity']);speed=math.sqrt(sum(x*x for x in v))
            if speed<=0:raise ValueError('Projectile has no initial motion.')
            if math.sqrt(sum(x*x for x in source))<1:group='stationary'
            elif source[0]>1000 and abs(source[1])<1:group='forward'
            elif source[1]>1000 and abs(source[0])<1:group='lateral'
            else:raise ValueError('Unexpected controlled character motion.')
            # With the original zero lateral inheritance the final direction
            # equals the launch direction; only its forward magnitude changes.
            projected=sum(x*y/speed for x,y in zip(source,v))
            expected=min(default['max'],max(0,default['initial']+projected*default['forward']))
            error=abs(speed-expected)
            shot={'group':group,'speed_m_per_s':speed/100,'source_velocity_cm_per_s':source,'expected_m_per_s':expected/100,'error_m_per_s':error/100}
            shots.append(shot);groups[group].append(shot)
            launch_speeds[row['id']]=speed
            shot_groups[row['id']]=group
            if error>25:result['passed']=False
            if float(row['initial'])!=default['initial']or float(row['max'])!=default['max']or float(row['gravity'])!=0:result['passed']=False
        if len(groups['stationary'])!=3 or len(groups['forward'])!=1 or len(groups['lateral'])!=1:result['passed']=False
        samples=[r for r in rows if r['kind']=='DISC_SPEED_SAMPLE']
        if not samples:result['passed']=False
        airborne=[]
        for row in samples:
            speed=float(row['distanceSpeed'])
            if not math.isfinite(speed)or row['id']not in launch_speeds:raise ValueError('Invalid trajectory observation.')
            if shot_groups[row['id']]=='stationary':continue
            airborne.append(row)
            if abs(speed-launch_speeds[row['id']])>25:result['passed']=False
            if abs(math.sqrt(sum(v*v for v in vector(row['velocity'])))-launch_speeds[row['id']])>25:result['passed']=False
        for group in ('forward','lateral'):
            if sum(shot_groups[r['id']]==group for r in airborne)<2:result['passed']=False
        result['roles'][role]={'original_defaults':default,'shots':shots,'airborne_trajectory_samples':len(airborne),'airborne_trajectory_speed_range_m_per_s':[min(float(r['distanceSpeed'])for r in airborne)/100,max(float(r['distanceSpeed'])for r in airborne)/100]if airborne else None,'stationary_samples_not_used_for_clear_flight':len(samples)-len(airborne)}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence',type=Path);args=parser.parse_args()
    proof=json.loads((args.evidence/'proof.json').read_bytes())
    if not proof['passed']or len(proof['owned_cleanup'])!=5 or any(row['active']!=0 for row in proof['owned_cleanup']):raise ValueError('Passing native evidence and original empty-Job records required.')
    result=analyze(args.evidence/'0-events.txt',args.evidence/'host-events.txt')
    result['analyzer_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['native_source_sha256']=proof['source_sha256']
    (args.evidence/'parity-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['passed']else 1


if __name__=='__main__':raise SystemExit(main())
