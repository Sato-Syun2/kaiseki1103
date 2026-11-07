import csv
import json
import shutil
from pathlib import Path

import pytest

from corridor_tracking.compact_completed_run import compact_completed_run
from corridor_tracking.portable_depth_replay import create_replay
from depth_person_prototype import digest


def setup_completed(tmp_path):
    root, bundle, shared = tmp_path/'ssd', tmp_path/'bundle', tmp_path/'shared'
    bundle.mkdir(); shared.mkdir()
    svo = tmp_path/'original.svo2'; svo.write_bytes(b'raw original')
    (bundle/'cal.json').write_text(json.dumps({'visible_wall_Y_m':2.1}))
    row={'group':'2','recording':'recording_001','svo_path':str(svo), 'source_svo_sha256':digest(svo),
         'setup_id':'setup','calibration_sha256':digest(bundle/'cal.json'), 'body_manifest_sha256':'body',
         'frame_count':'1','calibration':'cal.json'}
    with (bundle/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=row); writer.writeheader(); writer.writerow(row)
    tag='g002_recording_001_compact01'; work=root/'analysis'/tag; merged=work/'merged'; part=work/'part_000000'
    person={'status':'surface_candidate','surface_corridor_m':[1.,2.,3.], 'region_bbox_xyxy':[1,2,3,4],
            'region_mask':'masks/mask.png'}
    frame={'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'review_image':'images/frame.jpg','people':[person]}
    for dest in (merged,part):
        (dest/'images').mkdir(parents=True); (dest/'masks').mkdir()
        (dest/'images'/'frame.jpg').write_bytes(b'overlay image')
        (dest/'masks'/'mask.png').write_bytes(b'person mask')
        data={'metadata':{'source_svo_sha256':row['source_svo_sha256'],'calibration_sha256':row['calibration_sha256']}, 'frames':[frame]}
        (dest/'results.json').write_text(json.dumps(data))
        hashes={name:digest(dest/name) for name in ('results.json','images/frame.jpg','masks/mask.png')}
        (dest/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256':hashes}))
    coord=root/'coordinates'/tag; coord.mkdir(parents=True)
    obs={'track_id':1,'depth_status':'surface_candidate','surface_corridor_m':[1.,2.,3.],'association_reason':'test'}
    meta={k:row[k] for k in ('recording','source_svo_sha256','setup_id','calibration_sha256','body_manifest_sha256')}
    meta.update(group=2,person_run_manifest_sha256=digest(merged/'manifest.json'))
    (coord/'positions.json').write_text(json.dumps({'metadata':meta,'frames':[{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'observations':[obs]}]}))
    (coord/'manifest.json').write_text(json.dumps({'status':'complete','source_svo_sha256':row['source_svo_sha256'],'positions_sha256':digest(coord/'positions.json')}))
    shutil.copytree(coord,shared/tag)
    create_replay(root,bundle,2,'recording_001','compact01')
    clip_tag=f'{tag}_000000_000000'; clip=root/'depth_clips'/clip_tag; depth=clip/'depth'; (depth/'images').mkdir(parents=True)
    (depth/'images'/'raw.jpg').write_bytes(b'raw source image')
    (depth/'zed_depth_points.npz').write_bytes(b'large point archive')
    with (depth/'frames.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['frame_index','image_file']); writer.writeheader(); writer.writerow({'frame_index':0,'image_file':'images/raw.jpg'})
    hashes={name:digest(depth/name) for name in ('images/raw.jpg','zed_depth_points.npz')}
    (depth/'manifest.json').write_text(json.dumps({'status':'complete','source_svo_sha256':row['source_svo_sha256'],'sample_count':1,'files_sha256':hashes}))
    (clip/'batch_summary.json').write_text(json.dumps({'status':'validated','source_svo_sha256':row['source_svo_sha256'],'first_frame':0,'frame_count':1}))
    args=dict(root=root,bundle=bundle,shared=shared,row=row,group=2,recording='recording_001',run_id='compact01',clips=[(0,1,clip_tag)])
    return args, root, shared, tag, clip, svo


def test_removes_only_validated_intermediates_and_preserves_replay_and_original(tmp_path):
    args, root, shared, tag, clip, svo = setup_completed(tmp_path)
    receipt=compact_completed_run(**args)
    assert receipt['status']=='complete' and len(receipt['files_removed'])==4
    assert not (clip/'depth'/'zed_depth_points.npz').exists() and not (clip/'depth'/'images'/'raw.jpg').exists()
    assert not (root/'analysis'/tag/'part_000000'/'images'/'frame.jpg').exists()
    assert (clip/'depth'/'manifest.json').is_file() and (clip/'batch_summary.json').is_file()
    assert (root/'analysis'/tag/'merged'/'images'/'frame.jpg').read_bytes()==b'overlay image'
    assert (root/'analysis'/tag/'merged'/'masks'/'mask.png').read_bytes()==b'person mask'
    assert (root/'analysis'/tag/'merged'/'portable_replay.html').is_file()
    assert (shared/tag/'positions.json').is_file() and svo.read_bytes()==b'raw original'
    assert json.loads((root/'analysis'/tag/'storage_retention.json').read_text())['status']=='complete'
    create_replay(root,args['bundle'],2,'recording_001','compact01')


def test_any_hash_failure_stops_before_any_intermediate_is_removed(tmp_path):
    args, root, shared, tag, clip, svo = setup_completed(tmp_path)
    (clip/'depth'/'images'/'raw.jpg').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='intermediate hash mismatch'):
        compact_completed_run(**args)
    assert (clip/'depth'/'zed_depth_points.npz').is_file()
    assert (root/'analysis'/tag/'part_000000'/'images'/'frame.jpg').is_file()
    assert not (root/'analysis'/tag/'storage_retention.json').exists()


def test_source_missing_or_unshared_result_blocks_removal(tmp_path):
    args, root, shared, tag, clip, svo = setup_completed(tmp_path)
    svo.unlink()
    with pytest.raises(ValueError, match='original SVO'):
        compact_completed_run(**args)
    assert (clip/'depth'/'zed_depth_points.npz').is_file()


def test_interrupted_cleanup_preserves_a_prepared_receipt_and_final_result(tmp_path, monkeypatch):
    args, root, shared, tag, clip, svo = setup_completed(tmp_path)
    original_unlink = Path.unlink
    def fail_on_source_image(path, *a, **kw):
        if path.name == 'raw.jpg': raise OSError('simulated failure')
        return original_unlink(path, *a, **kw)
    monkeypatch.setattr(Path, 'unlink', fail_on_source_image)
    with pytest.raises(OSError, match='simulated failure'):
        compact_completed_run(**args)
    receipt=json.loads((root/'analysis'/tag/'storage_retention.json').read_text())
    assert receipt['status']=='prepared'
    assert (root/'analysis'/tag/'merged'/'portable_replay.html').is_file()
    assert (root/'analysis'/tag/'part_000000'/'images'/'frame.jpg').is_file()
