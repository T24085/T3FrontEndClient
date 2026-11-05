"""Measure camera-relative component poses; never infer rendered particle quality."""
import argparse,json,math
from pathlib import Path


def vector(text):
    values=tuple(map(float,text.split(',')))
    if len(values)!=3 or not all(math.isfinite(x) for x in values):raise ValueError('Expected a finite three-vector.')
    return values


def ahead(position,camera,rotation):
    """Unreal rotator order is pitch, yaw, roll; world X alone is insufficient."""
    pitch,yaw,_=map(math.radians,vector(rotation))
    direction=(math.cos(pitch)*math.cos(yaw),math.cos(pitch)*math.sin(yaw),math.sin(pitch))
    return sum((a-b)*c for a,b,c in zip(vector(position),vector(camera),direction))


def records(path):
    if path.stat().st_size>1024**2:raise ValueError('Event size bound exceeded.')
    rows=[]
    for line in path.read_text(errors='replace').splitlines():
        if not line.startswith('DISC_'):continue
        parts=line.split('|');row={'kind':parts[0]}
        row.update(part.split('=',1) for part in parts[1:] if '=' in part)
        if row.get('role')!='client':continue
        rows.append(row)
    return rows


def analyze(root):
    root=Path(root);proof=json.loads((root/'proof.json').read_bytes());rows=records(root/'0-events.txt')
    turns=[r for r in rows if r['kind']=='DISC_SPEED_TURN'];requests=[r for r in rows if r['kind']=='DISC_VISUAL_REQUEST']
    shots=[]
    for birth in (r for r in rows if r['kind']=='DISC_VISUAL_BIRTH'):
        poses=[r for r in rows if r['kind']=='DISC_VISUAL_POSE' and r['id']==birth['id']]
        if not poses:raise ValueError('Birth lacks pose evidence.')
        request=next((r for r in requests if r['prediction']==birth['prediction']),None)
        initial=poses[0];flight=[r for r in poses if r['stopped']=='false' and r['exploded']=='false']
        usable=[r for r in flight if r.get('cameraRotation','none')!='none' and r.get('camera','none')!='none']
        shot={'prediction':birth['prediction'],'time':float(birth['time']),'source_velocity_cm_s':vector(initial['sourceVelocity']),'pose_count':len(poses),'camera_relative_samples':len(usable)}
        if usable:
            shot['min_visual_ahead_camera_cm']=min(ahead(r['visual'],r['camera'],r['cameraRotation']) for r in usable)
            shot['camera_rotations']=list(dict.fromkeys(r['cameraRotation'] for r in usable))
        if initial.get('muzzle','none')!='none':shot['birth_visual_muzzle_error_cm']=math.dist(vector(initial['visual']),vector(initial['muzzle']))
        if request:
            shot['request_to_birth_ms']=1000*(float(birth['time'])-float(request['time']))
            preceding=[r for r in turns if float(r['time'])<=float(request['time'])]
            if preceding:
                turn=preceding[-1];shot.update(controlled_yaw=float(turn['yaw']),turn_to_request_ms=1000*(float(request['time'])-float(turn['time'])))
        shots.append(shot)
    return {'native_proof_passed':proof['passed'],'owned_jobs_empty':bool(proof['owned_cleanup']) and all(r['active']==0 for r in proof['owned_cleanup']),
            'controlled_turns':turns,'shots':shots,'input_state_events':[r for r in rows if r['kind']=='DISC_VISUAL_INPUT_STATE'],
            'limitations':['Component transforms do not measure individual Niagara particles or input-to-photon delay.','Requested 25ms input-state polling can be late or miss short presses; reflected hooks do not cover all native input.','Native SetControlRotation plus ASC taps are a controlled fixture, not mouse-look or a skiing route.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('evidence',type=Path);args=parser.parse_args()
    result=analyze(args.evidence);(args.evidence/'first-person-analysis.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
