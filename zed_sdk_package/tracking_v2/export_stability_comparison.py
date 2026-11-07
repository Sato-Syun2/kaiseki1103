#!/usr/bin/env python3
"""Export controlled SDK alternatives for recorded BODY_34 data on the SDK PC."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

# One change at a time from the existing ACCURATE / fitting / prediction 0.2 / confidence 35 pass.
PRESETS={
    'medium': ['--body-model','MEDIUM'],
    'no_prediction': ['--prediction-timeout-s','0'],
    'confidence_50': ['--detection-confidence','50'],
}


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job',nargs=4,metavar=('GROUP','RECORDING','SETUP_ID','LOCAL_SVO'),action='append',required=True)
    p.add_argument('--tag',required=True,help='new output tag')
    p.add_argument('--local-root',type=Path,default=Path.home()/'kaiseki1103_exchange')
    p.add_argument('--shared-dir',type=Path,required=True,help='new shared destination for the completed batch')
    p.add_argument('--presets',nargs='+',choices=PRESETS,default=list(PRESETS))
    a=p.parse_args()
    safe=re.compile(r'^[A-Za-z0-9_-]+$')
    if not safe.fullmatch(a.tag):p.error('tag must contain only letters, digits, underscore or hyphen')
    if len(set(a.presets))!=len(a.presets):p.error('duplicate presets')
    jobs=[]; seen=set()
    for group,recording,setup,svo in a.job:
        if not safe.fullmatch(group) or not safe.fullmatch(recording) or not safe.fullmatch(setup):p.error('group, recording, setup must contain only letters, digits, underscore or hyphen')
        if (group,recording) in seen:p.error('duplicate group/recording')
        seen.add((group,recording)); source=Path(svo)
        if not source.is_file() or source.suffix.lower() not in ('.svo','.svo2'):p.error(f'local SVO does not exist: {source}')
        jobs.append((group,recording,setup,source.resolve()))
    output=a.local_root/a.tag; stage=a.local_root/'.sdk_tools'/('stability_'+a.tag)
    if output.exists() or stage.exists() or a.shared_dir.exists():p.error('Output, local tool snapshot, or shared destination already exists; choose a new tag/destination')
    stage.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(Path(__file__).resolve().parent,stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    output.mkdir(parents=True,exist_ok=False)
    manifest={'status':'running','presets':{x:PRESETS[x] for x in a.presets},'python':sys.executable,
              'staged_tools':str(stage),'tool_sha256':{x.name:sha256(x) for x in stage.glob('*.py')},
              'jobs':[{'group':g,'recording':r,'setup_id':s,'source_svo':str(v)} for g,r,s,v in jobs]}
    (output/'batch_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    result=[]
    for group,recording,setup,svo in jobs:
        for name in a.presets:
            dest=output/group/recording/name/'body';dest.parent.mkdir(parents=True,exist_ok=True)
            log=dest.parent/'export.log';validation=dest.parent/'validation.log'
            command=[sys.executable,str(stage/'export_tracking.py'),str(svo),'--output',str(dest),'--setup-id',setup,'--mode','body',*PRESETS[name]]
            print(f'Processing {group}/{recording}/{name}',flush=True)
            with log.open('w',encoding='utf-8') as f:
                f.write('Command: '+repr(command)+'\n');f.flush()
                rc=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT).returncode
            vrc=None
            if rc==0:
                with validation.open('w',encoding='utf-8') as f:
                    vrc=subprocess.run([sys.executable,str(stage/'validate_export.py'),str(dest)],stdout=f,stderr=subprocess.STDOUT).returncode
            result.append(dict(group=group,recording=recording,preset=name,export_code=rc,validation_code=vrc,output=str(dest),log=str(log)))
            print(f'  export={rc}, validation={vrc}',flush=True)
    with (output/'batch_summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    ok=all(r['export_code']==0 and r['validation_code']==0 for r in result)
    manifest['status']='complete' if ok else 'failed';manifest['results']=result
    (output/'batch_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('Local output:',output,flush=True)
    if not ok:
        print('Some exports failed; local output and logs were retained. Use a new tag after diagnosis.',file=sys.stderr)
        return 1
    sync=subprocess.run([sys.executable,str(stage/'sync_exchange.py'),'--local-dir',str(output),'--shared-dir',str(a.shared_dir)])
    if sync.returncode:
        print('Shared mirror failed. Local result remains available; retry sync_exchange.py with the same local path and a new shared destination.',file=sys.stderr)
        return 1
    print('Shared output:',a.shared_dir)
    return 0


if __name__=='__main__':raise SystemExit(main())
