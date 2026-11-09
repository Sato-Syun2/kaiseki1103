#!/usr/bin/env python3
"""Local-only full-SVO BODY_34 batch with original recording names and safe restart."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

RECORDING=re.compile(r'^recording_\d{3}$',re.I)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def discover(sources,extras):
    jobs=[];missing=[];seen=set()
    for group,root,setup in sources:
        root=Path(root)
        if not root.is_dir():raise ValueError(f'input folder not found: {root}')
        for folder in sorted(root.iterdir(),key=lambda x:x.name.casefold()):
            if not folder.is_dir() or not RECORDING.fullmatch(folder.name):continue
            files=[p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.svo','.svo2')]
            if not files:missing.append(str(folder));continue
            if len(files)!=1:raise ValueError(f'multiple SVO files, cannot choose: {folder}')
            jobs.append({'group':int(group),'recording':folder.name.lower(),'source':str(files[0].resolve()),'setup_id':setup})
    for group,alias,source,setup in extras:
        if not RECORDING.fullmatch(alias):raise ValueError(f'invalid extra recording alias: {alias}')
        source=Path(source)
        if not source.is_file():missing.append(str(source));continue
        if source.suffix.lower() not in ('.svo','.svo2'):raise ValueError(f'invalid SVO extension: {source}')
        jobs.append({'group':int(group),'recording':alias.lower(),'source':str(source.resolve()),'setup_id':setup})
    for job in jobs:
        key=(job['group'],job['recording'])
        if key in seen:raise ValueError(f'duplicate group and recording: {key}')
        seen.add(key)
    return sorted(jobs,key=lambda j:(j['group'],j['recording'])),missing


def command_logged(command,log,progress):
    with log.open('x',encoding='utf-8') as stream:
        stream.write('command: '+subprocess.list2cmdline(command)+'\n\n');stream.flush()
        process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT)
        started=time.monotonic()
        try:
            while True:
                try:code=process.wait(timeout=30);break
                except subprocess.TimeoutExpired:
                    print(f'{progress} Current recording elapsed: {int(time.monotonic()-started)} s; log: {log}',flush=True)
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            stream.write('\ninterrupted; partial output preserved\n');stream.flush()
            raise
        stream.write(f'\nexit_code: {code}\n');stream.flush()
        return code


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',nargs=3,action='append',metavar=('GROUP','ROOT','SETUP'),required=True)
    p.add_argument('--extra',nargs=4,action='append',metavar=('GROUP','ALIAS','SVO','SETUP'),default=[])
    p.add_argument('--local-root',type=Path,required=True)
    p.add_argument('--known-sources',type=Path,required=True)
    a=p.parse_args();jobs,missing=discover(a.source,a.extra)
    if not jobs:raise ValueError('no SVO files found')
    known=json.loads(a.known_sources.read_text(encoding='utf-8-sig'))
    expected={(int(x['group']),x['recording']):x for x in known['records']}
    for job in jobs:
        item=expected.get((job['group'],job['recording']))
        if item:
            if os.path.normcase(item['source'])!=os.path.normcase(job['source']):
                raise ValueError(f"source path differs from known depth result: {job['source']}")
            job['expected_sha256']=item['sha256']
    a.local_root.mkdir(parents=True,exist_ok=True)
    # OS advisory lock is released on process termination, including crashes.
    lock=(a.local_root/'.batch.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    if os.name=='nt':
        import msvcrt
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('another BODY batch is running')
    else:
        import fcntl
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    (a.local_root/('inventory_'+run_id+'.json')).write_text(json.dumps({'jobs':jobs,'missing':missing},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'BODY_34 local-only: {len(jobs)} recordings; {len(missing)} empty or missing sources.',flush=True)
    for path in missing:print(f'No SVO: {path}',flush=True)
    elapsed_new=[];failed=[];reused=0;exporter=Path(__file__).with_name('export_tracking.py');validator=Path(__file__).with_name('validate_export.py')
    for index,job in enumerate(jobs,1):
        record=a.local_root/f"g{job['group']:03d}"/job['recording'];record.mkdir(parents=True,exist_ok=True)
        valid=[]
        for marker in sorted(record.glob('attempt_*/complete.json')):
            try:
                info=json.loads(marker.read_text(encoding='utf-8-sig'))
                if (info['source'].casefold()==job['source'].casefold() and info['setup_id']==job['setup_id'] and
                    (not job.get('expected_sha256') or job['expected_sha256']==info['source_svo_sha256']) and
                    sha(marker.parent/'body'/'manifest.json')==info['manifest_sha256']):valid.append(marker)
            except (OSError,ValueError,KeyError):continue
        prefix=f'[{index}/{len(jobs)}] G{job["group"]:03d} {job["recording"]}'
        if len(valid)>1:raise ValueError(f'multiple completed attempts require review: {record}')
        if valid:
            # Validate files again; never skip a damaged output on a marker alone.
            result=subprocess.run([sys.executable,str(validator),str(valid[0].parent/'body')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if result.returncode!=0:raise ValueError(f'completed export failed revalidation: {valid[0].parent}')
            reused+=1;print(prefix+' already validated; reused',flush=True);continue
        attempt=record/('attempt_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);attempt.mkdir()
        eta=(sum(elapsed_new)/len(elapsed_new))*(len(jobs)-index+1) if elapsed_new else None
        print(prefix+f' starting; estimated remaining {int(eta/60)} min' if eta is not None else prefix+' starting; ETA after first completed recording',flush=True)
        t0=time.monotonic()
        cmd=[sys.executable,str(exporter),job['source'],'--output',str(attempt/'body'),'--mode','body',
             '--setup-id',job['setup_id'],'--image-period-s','0.1','--depth-mode','NEURAL',
             '--detection-confidence','35','--minimum-keypoints','8','--prediction-timeout-s','0.2','--skeleton-smoothing','0']
        code=command_logged(cmd,attempt/'body.log',prefix)
        if code==0:code=command_logged([sys.executable,str(validator),str(attempt/'body')],attempt/'validation.log',prefix)
        if code==0:
            camera=json.loads((attempt/'body'/'camera.json').read_text(encoding='utf-8-sig'))
            actual=camera['source_svo_sha256']
            if job.get('expected_sha256') and actual!=job['expected_sha256']:
                print(prefix+' ERROR: SVO hash differs from depth analysis; preserving attempt',flush=True);code=1
        if code:
            failed.append({'group':job['group'],'recording':job['recording'],'attempt':str(attempt)})
            print(prefix+f' FAILED; preserved {attempt}; stopping. Run same command to retry.',flush=True);break
        info={'status':'validated_full_svo','source':job['source'],'source_svo_sha256':actual,'setup_id':job['setup_id'],
              'manifest_sha256':sha(attempt/'body'/'manifest.json'),'group':job['group'],'recording':job['recording']}
        (attempt/'complete.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        elapsed_new.append(time.monotonic()-t0)
        print(prefix+f' validated; {int(elapsed_new[-1])} s',flush=True)
    print(json.dumps({'jobs':len(jobs),'new_validated':len(elapsed_new),'reused':reused,'failed':failed,'missing':missing},ensure_ascii=False),flush=True)
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
