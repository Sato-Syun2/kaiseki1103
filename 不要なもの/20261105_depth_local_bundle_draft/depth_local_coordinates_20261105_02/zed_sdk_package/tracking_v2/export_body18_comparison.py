#!/usr/bin/env python3
"""Export one SVO twice with BODY_18 fitting off/on, locally first."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


def sha256(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--svo',type=Path,required=True)
    p.add_argument('--setup-id',required=True)
    p.add_argument('--tag',required=True)
    p.add_argument('--local-root',type=Path,default=Path.home()/'kaiseki1103_exchange')
    p.add_argument('--shared-dir',type=Path,required=True)
    a=p.parse_args()
    safe=re.compile(r'^[A-Za-z0-9_-]+$')
    if not safe.fullmatch(a.tag) or not safe.fullmatch(a.setup_id):p.error('tag/setup-id must contain only letters, numbers, underscore and hyphen')
    if not a.svo.is_file() or a.svo.suffix.lower() not in ('.svo','.svo2'):p.error(f'SVO does not exist: {a.svo}')
    output=a.local_root/a.tag; stage=a.local_root/'.sdk_tools'/('body18_'+a.tag)
    if output.exists() or stage.exists() or a.shared_dir.exists():p.error('Local output, staged tools, or shared destination already exists; use a new tag')
    stage.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(Path(__file__).resolve().parent,stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    output.mkdir(parents=True,exist_ok=False)
    manifest={'status':'running','source_svo':str(a.svo.resolve()),'setup_id':a.setup_id,
              'tool_sha256':{f.name:sha256(f) for f in stage.glob('*.py')},'staged_tools':str(stage),
              'note':'BODY_18 fitting on/off is an experiment; applied SDK behavior and output topology must be checked'}
    (output/'batch_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    result=[]
    for name,extra in [('fitting_off',['--no-body-fitting']),('fitting_on',[])]:
        dest=output/name/'body';dest.parent.mkdir(parents=True,exist_ok=True)
        cmd=[sys.executable,str(stage/'export_tracking.py'),str(a.svo.resolve()),'--output',str(dest),'--setup-id',a.setup_id,'--mode','body18','--body-model','ACCURATE',*extra]
        print(f'Processing {name} ...',flush=True)
        with (dest.parent/'export.log').open('wb') as log:
            log.write(('Command: '+repr(cmd)+'\n').encode('utf-8'));log.flush()
            rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
        validation=None
        if rc==0:
            with (dest.parent/'validation.log').open('wb') as log:
                validation=subprocess.run([sys.executable,str(stage/'validate_export.py'),str(dest)],stdout=log,stderr=subprocess.STDOUT).returncode
        result.append(dict(setting=name,export_code=rc,validation_code=validation,output=str(dest),log=str(dest.parent/'export.log')))
        print(f'  export={rc}, validation={validation}',flush=True)
    with (output/'batch_summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    ok=all(x['export_code']==0 and x['validation_code']==0 for x in result)
    manifest.update(status='complete' if ok else 'failed',results=result)
    (output/'batch_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('Local output:',output,flush=True)
    if not ok:
        print('Some exports failed. Local results and logs are retained; retry with a new tag after diagnosis.',file=sys.stderr)
        return 1
    rc=subprocess.run([sys.executable,str(stage/'sync_exchange.py'),'--local-dir',str(output),'--shared-dir',str(a.shared_dir)]).returncode
    if rc:
        print('Shared sync failed; local results are retained.',file=sys.stderr)
        return 1
    print('Shared output:',a.shared_dir,flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
