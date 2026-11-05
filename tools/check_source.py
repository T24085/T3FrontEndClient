"""Check the source inventory and paired protocol copies without starting a game."""
import argparse,ast,hashlib,json,os,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXCLUDE={'.git','.venv','__pycache__','.test-tools','.pytest_cache'}
BINARY={'.exe','.dll','.pyd','.pak','.sig','.zip','.uasset','.uexp','.ubulk','.dmp','.key','.pem','.pfx','.p12'}
SECRET=re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--peer',type=Path);args=p.parse_args()
 count=0
 for directory,dirs,names in os.walk(ROOT):
  dirs[:]=[d for d in dirs if d not in EXCLUDE]
  for name in names:
   path=Path(directory)/name;rel=path.relative_to(ROOT)
   assert path.suffix.lower()not in BINARY,'Non-source artifact in checkout: '+str(rel)
   assert path.stat().st_size<2*1024*1024,'Unexpected large source member: '+str(rel)
   raw=path.read_bytes();assert not SECRET.search(raw),'Possible credential in '+str(rel)
   if path.suffix in ('.py','.pyw'):ast.parse(raw,filename=str(rel));count+=1
 contract=json.loads((ROOT/'shared-contracts.json').read_bytes())
 assert contract['format']==1
 for name,expected in contract['files'].items():
  assert digest(ROOT/name)==expected,'Update coordinated contract for changed file: '+name
  if args.peer:assert digest(args.peer/name)==expected,'Paired source differs: '+name
 print(f'{count} Python sources parsed; {len(contract["files"])} shared contracts verified; source artifact/credential checks passed.')
if __name__=='__main__':main()
