import csv
import json
import shutil

import pytest

from corridor_tracking.migrate_depth_results import copy_tree_checked
from corridor_tracking.portable_depth_replay import create_replay, joined_frames, validate_candidate
from depth_person_prototype import digest


def test_join_keeps_image_and_coordinate_times_and_person_order():
    person = [{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'review_image':'images/0.jpg',
               'people':[{'status':'surface_candidate','surface_corridor_m':[1.,2.,3.], 'region_bbox_xyxy':[2,3,4,5]}]}]
    positions = [{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'observations':[
        {'track_id':2,'depth_status':'surface_candidate','surface_corridor_m':[1.,2.,3.], 'association_reason':'new_track'}]}]
    merged = joined_frames(person, positions)
    assert merged[0]['review_image'] == 'images/0.jpg'
    assert merged[0]['observations'][0]['track_id'] == 2
    assert merged[0]['observations'][0]['region_bbox_xyxy'] == [2,3,4,5]
    positions[0]['timestamp_ns'] = '101'
    with pytest.raises(ValueError, match='timestamps'):
        joined_frames(person, positions)
    positions[0]['timestamp_ns'] = '100'
    positions[0]['observations'][0]['surface_corridor_m'] = [1.,2.,4.]
    with pytest.raises(ValueError, match='observations'):
        joined_frames(person, positions)


def test_migration_never_overwrites_conflicting_destination(tmp_path):
    source, dest = tmp_path/'C'/'analysis', tmp_path/'G'/'analysis'
    (source/'part').mkdir(parents=True)
    (source/'part'/'file.bin').write_bytes(b'original')
    assert copy_tree_checked(source, dest) == (1, 0)
    assert (source/'part'/'file.bin').read_bytes() == b'original'
    assert copy_tree_checked(source, dest) == (0, 1)
    (dest/'part'/'file.bin').write_bytes(b'different')
    with pytest.raises(FileExistsError, match='differs'):
        copy_tree_checked(source, dest)
    assert (dest/'part'/'file.bin').read_bytes() == b'different'
    assert (source/'part'/'file.bin').read_bytes() == b'original'


@pytest.mark.parametrize(('group', 'run_id'), [(2, '20261105_01'), (4, 'compact_20261106_01')])
def test_portable_replay_survives_moving_root_and_reuses_images(tmp_path, group, run_id):
    root, bundle = tmp_path/'ssd', tmp_path/'bundle'
    bundle.mkdir(); (bundle/'cal.json').write_text(json.dumps({'visible_wall_Y_m':2.1}))
    row = {'group':str(group),'recording':'recording_001','source_svo_sha256':'svo','setup_id':'setup',
           'calibration_sha256':digest(bundle/'cal.json'),'body_manifest_sha256':'body','frame_count':'1','calibration':'cal.json'}
    with (bundle/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=row);w.writeheader();w.writerow(row)
    tag=f'g{group:03d}_recording_001_{run_id}'; merged=root/'analysis'/tag/'merged'; (merged/'images').mkdir(parents=True)
    (merged/'images'/'frame.jpg').write_bytes(b'original image')
    person={'status':'surface_candidate','surface_corridor_m':[1.,2.,3.], 'region_bbox_xyxy':[1,2,3,4]}
    source={'metadata':{'source_svo_sha256':'svo','calibration_sha256':row['calibration_sha256']},
            'frames':[{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'review_image':'images/frame.jpg','people':[person]}]}
    (merged/'results.json').write_text(json.dumps(source))
    (merged/'manifest.json').write_text(json.dumps({'status':'complete','files_sha256':{
        'results.json':digest(merged/'results.json'),'images/frame.jpg':digest(merged/'images'/'frame.jpg')}}))
    coord=root/'coordinates'/tag;coord.mkdir(parents=True)
    obs={'track_id':None,'depth_status':'surface_candidate','surface_corridor_m':[1.,2.,3.],'association_reason':'test'}
    meta={k:row[k] for k in ('recording','source_svo_sha256','setup_id','calibration_sha256','body_manifest_sha256')}
    meta.update(group=group,person_run_manifest_sha256=digest(merged/'manifest.json'))
    (coord/'positions.json').write_text(json.dumps({'metadata':meta,'frames':[{'frame_index':0,'timestamp_ns':'100','elapsed_s':0.,'observations':[obs]}]}))
    (coord/'manifest.json').write_text(json.dumps({'status':'complete','positions_sha256':digest(coord/'positions.json')}))
    page=create_replay(root,bundle,group,'recording_001',run_id)
    assert 'images/frame.jpg' in page.read_text()
    assert create_replay(root,bundle,group,'recording_001',run_id) == page
    import copy
    original=json.loads((coord/'positions.json').read_text());candidate=copy.deepcopy(original)
    candidate['reassignment_candidate']={'status':'proposed_not_verified','source_positions_sha256':digest(coord/'positions.json'),'target_id':3}
    candidate['frames'][0]['observations'][0].update(track_id=3,original_track_id=None,identity_assignment='proposed')
    packet=tmp_path/'packet';packet.mkdir();(packet/'positions.json').write_text(json.dumps(candidate))
    (packet/'manifest.json').write_text(json.dumps({'status':'proposed_not_verified','source_positions_sha256':digest(coord/'positions.json'),
        'positions_sha256':digest(packet/'positions.json'),'proposed_count':1}))
    index_before=(root/'depth_replay_index.html').read_bytes()
    proposal=create_replay(root,bundle,group,'recording_001',run_id,packet,update_gallery=False)
    assert '再割当ては未確認' in proposal.read_text()
    assert (root/'depth_replay_index.html').read_bytes() == index_before
    from corridor_tracking.spatial_filter import corridor_bounds, filter_frames
    bounds=corridor_bounds({'visible_wall_Y_m':2.1},fallback_width_m=2.4)
    filtered_original=copy.deepcopy(original);filtered_original['frames'],_,base_stats=filter_frames(original['frames'],bounds)
    filtered_base=tmp_path/'filtered_base';filtered_base.mkdir()
    (filtered_base/'positions.json').write_text(json.dumps(filtered_original))
    (filtered_base/'manifest.json').write_text(json.dumps({'status':'complete',
        'positions_sha256':digest(filtered_base/'positions.json'),'source_positions_sha256':digest(coord/'positions.json'),
        'bounds':bounds,'counts':base_stats}))
    base_replay=create_replay(root,bundle,group,'recording_001',run_id,update_gallery=False,filtered_dir=filtered_base)
    assert '範囲外の座標・ID枠は除外' in base_replay.read_text()
    filtered=copy.deepcopy(candidate);filtered['frames'],_,stats=filter_frames(candidate['frames'],bounds)
    filtered_packet=tmp_path/'filtered_packet';filtered_packet.mkdir()
    (filtered_packet/'positions.json').write_text(json.dumps(filtered))
    (filtered_packet/'manifest.json').write_text(json.dumps({'status':'proposed_not_verified',
        'positions_sha256':digest(filtered_packet/'positions.json'),'source_candidate_sha256':digest(packet/'positions.json'),
        'bounds':bounds,'counts':stats}))
    spatial=create_replay(root,bundle,group,'recording_001',run_id,packet,update_gallery=False,filtered_dir=filtered_packet)
    assert '範囲外の座標・ID枠は除外' in spatial.read_text()
    assert (root/'depth_replay_index.html').read_bytes() == index_before
    relocated=tmp_path/'relocated';shutil.copytree(root,relocated)
    assert (relocated/'depth_replay_index.html').is_file()
    assert (relocated/'analysis'/tag/'merged'/'images'/'frame.jpg').read_bytes() == b'original image'


def test_candidate_can_only_assign_an_unassigned_observation():
    original={'metadata':{'source':'svo'},'frames':[{'frame_index':0,'timestamp_ns':'10','elapsed_s':0.,
        'observations':[{'track_id':None,'surface_corridor_m':[1.,2.,3.],'depth_status':'surface_candidate'}]}]}
    import copy
    candidate=copy.deepcopy(original)
    candidate['reassignment_candidate']={'status':'proposed_not_verified','source_positions_sha256':'sourcehash','target_id':3}
    candidate['frames'][0]['observations'][0].update(track_id=3,original_track_id=None,identity_assignment='proposed')
    assert validate_candidate(original,candidate,'sourcehash') == 1
    candidate['frames'][0]['observations'][0]['surface_corridor_m'][0]=8.
    with pytest.raises(ValueError,match='other than an unassigned identity'):
        validate_candidate(original,candidate,'sourcehash')
