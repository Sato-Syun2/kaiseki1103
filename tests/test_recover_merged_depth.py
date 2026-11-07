import csv
import json
from pathlib import Path
import sys

import pytest

from corridor_tracking import recover_merged_depth as recovery
from corridor_tracking.compact_batch import validate_existing
from corridor_tracking.merge_depth_person_runs import main as merge


def make_fixture(tmp_path, monkeypatch):
    root=tmp_path/'ssd';root.mkdir()
    shared=tmp_path/'shared';shared.mkdir()
    bundle=tmp_path/'bundle';bundle.mkdir()
    svo=tmp_path/'source.svo2';svo.write_bytes(b'svo')
    (bundle/'models').mkdir();(bundle/'models/yolov8n-seg.pt').write_bytes(b'model')
    (bundle/'corridor_tracking').mkdir();(bundle/'corridor_tracking/depth_tracking.py').write_text('# original tracking\n')
    project=Path(__file__).resolve().parents[1]
    for name in ('depth_person_prototype.py','corridor_tracking/data.py','corridor_tracking/merge_depth_person_runs.py'):
        (bundle/name).write_bytes((project/name).read_bytes())
    (bundle/'cal.json').write_text(json.dumps({'visible_wall_Y_m':2.1,'other_wall_inference':None}))
    timeline={'body_manifest_sha256':'bodyhash','camera':{},'frames':[{'frame_index':str(i),'svo_frame_index':str(i),
                'image_timestamp_ns':str(1_000_000_000+i*30_000_000)} for i in range(2)]}
    (bundle/'timeline.json').write_text(json.dumps(timeline))
    row={'group':'4','recording':'recording_032','svo_path':str(svo),'setup_id':'setup',
         'source_svo_sha256':recovery.sha256(svo),'frame_count':'2','body_manifest_sha256':'bodyhash',
         'timeline':'timeline.json','calibration':'cal.json','calibration_sha256':recovery.sha256(bundle/'cal.json')}
    with (bundle/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
    files={p.relative_to(bundle).as_posix():recovery.sha256(p) for p in bundle.rglob('*') if p.is_file()}
    (bundle/'bundle_manifest.json').write_text(json.dumps({'status':'prepared_not_windows_validated','files_sha256':files}))
    tag='g004_recording_032_compact_test';work=root/'analysis'/tag;part=work/'part_000000';part.mkdir(parents=True)
    clip=root/'depth_clips'/f'{tag}_000000_000001';(clip/'depth').mkdir(parents=True)
    (clip/'depth/manifest.json').write_text('{"status":"complete"}')
    dh=recovery.sha256(clip/'depth/manifest.json')
    (clip/'batch_summary.json').write_text(json.dumps({'status':'validated','source_svo_sha256':row['source_svo_sha256'],
        'first_frame':0,'frame_count':2,'point_archive_mode':'compressed'}))
    metadata={'method':'mask','source_svo_sha256':row['source_svo_sha256'],'setup_id':'setup',
        'calibration_sha256':row['calibration_sha256'],'selection':{'min_points':20},
        'model_sha256':recovery.sha256(bundle/'models/yolov8n-seg.pt'),'model_task':'segment',
        'ultralytics_version':'8.4.89','confidence':.15,'imgsz':1280,'device':'cpu',
        'depth_manifest_sha256':dh,'limits':[]}
    frames=[]
    for i in range(2):
        image=f'images/frame_{i}.jpg';mask=f'masks/frame_{i}.png'
        for name in (image,mask):
            f=part/name;f.parent.mkdir(exist_ok=True);f.write_bytes(b'asset'+str(i).encode())
        person={'label':'person','status':'surface_candidate','region_bbox_xyxy':[i,0,i+10,20],
                'surface_camera_image_m':[.01*i,0.,3.], 'surface_corridor_m':[3.,1.,1.], 'region_mask':mask}
        frames.append({'frame_index':i,'timestamp_ns':str(1_000_000_000+i*30_000_000),'elapsed_s':i*.03,
                       'review_image':image,'people':[person]})
    (part/'results.json').write_text(json.dumps({'metadata':metadata,'frames':frames}))
    hashes={p.relative_to(part).as_posix():recovery.sha256(p) for p in part.rglob('*') if p.is_file()}
    (part/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256':hashes,
        'script_sha256':recovery.sha256(bundle/'depth_person_prototype.py'),
        'transform_code_sha256':recovery.sha256(bundle/'corridor_tracking/data.py')}))
    alignment={'status':'matched','continuous':True,'depth_manifest_sha256':dh,'body_manifest_sha256':'bodyhash',
        'body_frames':2,'source_svo_sha256':row['source_svo_sha256'],'setup_id':'setup','depth_frames':2,'first_frame':0,'last_frame':1}
    alignment_path=work/'alignment_000000.json';alignment_path.write_text(json.dumps(alignment))
    monkeypatch.setattr(sys,'argv',['merge','--part',str(part),str(alignment_path),'--first-frame','0',
                                     '--frame-count','2','--require-full-svo','--output',str(work/'merged')])
    merge()
    (work/'timing.json').write_text(json.dumps({'clip_frames':69,'point_archive_mode':'compressed'}))
    monkeypatch.setattr(recovery.importlib.metadata,'version',lambda name:'8.4.89')
    return root,shared,bundle,row,work


def test_recovers_complete_merged_result_without_overwriting_or_sdk(tmp_path, monkeypatch):
    root,shared,bundle,row,work=make_fixture(tmp_path,monkeypatch)
    before=recovery.sha256(work/'merged/manifest.json')
    tag=recovery.recover(bundle,root,shared,4,'recording_032','compact_test','compact_test')
    assert tag=='g004_recording_032_compact_test_retry01'
    assert recovery.sha256(work/'merged/manifest.json')==before
    assert (work/'part_000000/results.json').is_file()
    assert (root/'depth_clips'/'g004_recording_032_compact_test_000000_000001/depth/manifest.json').is_file()
    positions=json.loads((shared/tag/'positions.json').read_text())
    assert len(positions['frames'])==2 and positions['metadata']['recovery']['source_intermediates_retained']
    assert (root/'analysis'/tag/'merged/portable_replay.html').is_file()
    receipt=json.loads((root/'analysis'/tag/'storage_retention.json').read_text())
    assert receipt['status']=='complete' and receipt['files_removed']==[]
    validate_existing(row,root,shared,bundle,'compact_test_retry01','compact_test')


def test_rejects_modified_alignment_before_creating_recovery(tmp_path, monkeypatch):
    root,shared,bundle,row,work=make_fixture(tmp_path,monkeypatch)
    (work/'alignment_000000.json').write_text('{}')
    with pytest.raises(ValueError,match='mismatched part'):
        recovery.recover(bundle,root,shared,4,'recording_032','compact_test','compact_test')
    assert list(shared.iterdir())==[]
    assert not (root/'analysis/g004_recording_032_compact_test_retry01').exists()


def test_share_failure_preserves_local_work_and_retry_uses_new_output(tmp_path, monkeypatch):
    from zed_sdk_package.tracking_v2 import exchange_copy
    root,shared,bundle,row,work=make_fixture(tmp_path,monkeypatch)
    original=exchange_copy.copy_batch
    monkeypatch.setattr(exchange_copy,'copy_batch',lambda *args,**kwargs:(False,'disconnected'))
    with pytest.raises(OSError,match='shared publication failed'):
        recovery.recover(bundle,root,shared,4,'recording_032','compact_test','compact_test')
    assert (work/'merged/results.json').is_file()
    assert (root/'analysis/g004_recording_032_compact_test_retry01/merged/portable_replay.html').is_file()
    assert list(shared.iterdir())==[]
    monkeypatch.setattr(exchange_copy,'copy_batch',original)
    tag=recovery.recover(bundle,root,shared,4,'recording_032','compact_test','compact_test')
    assert tag=='g004_recording_032_compact_test_retry02'
    validate_existing(row,root,shared,bundle,'compact_test_retry02','compact_test')
