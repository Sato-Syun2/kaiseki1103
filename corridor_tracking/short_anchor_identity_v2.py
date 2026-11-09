"""Use short, motion-supported anchors for separate, unverified 10 m ID candidates.

This process uses the existing candidate publisher in its own Python process;
the running original watcher and its source files are not modified.
"""
import argparse
import collections
import fcntl
import json
from pathlib import Path
import time

import corridor_tracking.propose_trusted10_identities_live as publisher
from corridor_tracking.audit_depth_tracking import digest, read
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.reassign_depth_identity_temporal import propose_backwards

OUTPUT=Path('results/tracking_v2/identity_short_anchor_v2_live_20261107_01')
ORIGINAL_STATES=Path('results/tracking_v2/identity_proposals_10m_all_live_20261107_01/states')
THIS=Path(__file__)


def evaluate(frames):
    """Try every ID with >=5 positions as target, and >=10 as reference.

    The temporal method still checks at least five target positions, at least
    three valid speed samples and all its per-observation gates. Multiple
    eligible pairs are returned to the caller to withhold as ambiguous.
    """
    counts=collections.Counter(o['track_id'] for f in frames for o in f['observations']
                               if o['track_id'] is not None and o.get('surface_corridor_m') is not None)
    options=[]
    targets=sorted(k for k,v in counts.items() if v>=5)
    references=sorted(k for k,v in counts.items() if v>=10)
    for target in targets:
        for reference in references:
            if target==reference:continue
            try:
                frames_out,changes,diagnostics=propose_backwards(frames,target,reference)
                if len(changes)>=5:options.append((target,reference,frames_out,changes,diagnostics))
            except ValueError:
                continue
    return options,dict(counts)


def reuse_if_equal(row, original, source_hash):
    """Reuse an old candidate only when the new exhaustive search agrees exactly."""
    state=ORIGINAL_STATES/(row['tag']+'.json')
    if not state.is_file():return None
    old=read(state).get('result',{})
    if old.get('status')!='candidate' or old.get('source_positions_sha256')!=source_hash:
        return None
    options,_=evaluate(original['frames'])
    if len(options)!=1:return None
    target,reference,frames,changes,_=options[0]
    if (old.get('target_id'),old.get('reference_id'),old.get('proposed_count'))!=(target,reference,len(changes)):
        return None
    folder=Path(old['candidate_path']).parent
    manifest=read(folder/'manifest.json');candidate=read(folder/'positions.json')
    if candidate.get('reassignment_candidate',{}).get('condition_id')!=row.get('condition_id'):
        return None
    if (manifest.get('status')!='proposed_not_verified' or manifest.get('source_positions_sha256')!=source_hash or
            manifest.get('positions_sha256')!=digest(folder/'positions.json') or
            manifest.get('assignments_sha256')!=digest(folder/'assignments.json') or
            manifest.get('report_sha256')!=digest(folder/'index.html') or
            candidate['frames']!=frames or validate_candidate(original,candidate,source_hash)!=len(changes)):
        raise ValueError('previous candidate does not match; preserve it for review')
    return {'status':'candidate','candidate_path':str(folder/'index.html'),'candidate_page_sha256':digest(folder/'index.html'),
            'candidate_positions_sha256':digest(folder/'positions.json'),'candidate_assignments_sha256':digest(folder/'assignments.json'),
            'candidate_manifest_sha256':digest(folder/'manifest.json'),'target_id':target,'reference_id':reference,
            'proposed_count':len(changes),'reused':True}


def configure():
    # Scoped to this process: other running watchers use their own module state.
    publisher.evaluate=evaluate
    publisher.prior_candidate=reuse_if_equal
    publisher.EVALUATOR=THIS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=120)
    a=p.parse_args()
    if a.interval<30:p.error('interval must be at least 30 seconds')
    configure();OUTPUT.mkdir(parents=True,exist_ok=True)
    with (OUTPUT/'.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('short-anchor candidate watcher already running')
        while True:
            failures=publisher.scan(output=OUTPUT)
            if not a.watch:return 1 if failures else 0
            time.sleep(a.interval)


if __name__=='__main__':raise SystemExit(main())
