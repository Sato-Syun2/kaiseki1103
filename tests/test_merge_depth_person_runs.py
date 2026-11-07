import copy
import json
import sys
import pytest

from corridor_tracking.depth_tracking import associate_frames
from corridor_tracking.merge_depth_person_runs import main, validate_parts
from depth_person_prototype import digest


def part(first,last,depth_hash):
    meta={'method':'mask','source_svo_sha256':'svo','setup_id':'setup','calibration_sha256':'cal',
          'selection':{'min_points':20},'model_sha256':'model','model_task':'segment',
          'ultralytics_version':'test','confidence':.15,'imgsz':1280,'device':'cpu',
          'depth_manifest_sha256':depth_hash}
    frames=[{'frame_index':i,'timestamp_ns':str(10**18+i*30_000_000),'elapsed_s':i*.03} for i in range(first,last+1)]
    alignment={'status':'matched','continuous':True,'depth_manifest_sha256':depth_hash,
               'body_manifest_sha256':'body','body_frames':4,'source_svo_sha256':'svo','setup_id':'setup',
               'depth_frames':len(frames),'first_frame':first,'last_frame':last}
    return {'data':{'metadata':meta,'frames':frames},'alignment':alignment,
            'manifest':{'script_sha256':'script','transform_code_sha256':'transform'}}


def test_join_sorts_parts_and_requires_full_timeline():
    a,b=part(0,1,'a'),part(2,3,'b')
    ordered=validate_parts([b,a],0,4,require_full_svo=True)
    assert [x['alignment']['first_frame'] for x in ordered]==[0,2]
    with pytest.raises(ValueError,match='full SVO'):
        validate_parts([a],0,2,require_full_svo=True)


def test_join_refuses_setting_mismatch_and_missing_or_duplicate_frame():
    a,b=part(0,1,'a'),part(2,3,'b')
    wrong=copy.deepcopy(b);wrong['data']['metadata']['model_sha256']='different'
    with pytest.raises(ValueError,match='configuration'):
        validate_parts([a,wrong],0,4)
    with pytest.raises(ValueError,match='missing frames'):
        validate_parts([a],0,4)
    with pytest.raises(ValueError,match='timestamps|overlap'):
        validate_parts([a,b,b],0,4)


def test_join_refuses_wrong_alignment_or_inconsistent_clock():
    a,b=part(0,1,'a'),part(2,3,'b')
    wrong=copy.deepcopy(b);wrong['alignment']['body_manifest_sha256']='other'
    with pytest.raises(ValueError,match='different depth or BODY'):
        validate_parts([a,wrong],0,4)
    wrong=copy.deepcopy(b);wrong['data']['frames'][0]['elapsed_s']=.8
    with pytest.raises(ValueError,match='elapsed time'):
        validate_parts([a,wrong],0,4)


def test_join_accepts_svo_timeline_without_falsely_claiming_body():
    a,b=part(0,1,'a'),part(2,3,'b')
    for item in (a,b):
        align=item['alignment']
        align['timeline_sha256']=align.pop('body_manifest_sha256')
        align['reference_frames']=align.pop('body_frames')
        align['reference_kind']='svo_sdk_timeline_no_body'
    assert len(validate_parts([a,b],0,4,require_full_svo=True))==2
    wrong=copy.deepcopy(b);wrong['alignment']['timeline_sha256']='different'
    with pytest.raises(ValueError):
        validate_parts([a,wrong],0,4,require_full_svo=True)


def test_merged_files_keep_tracking_continuous_across_boundary(tmp_path,monkeypatch):
    paths=[]
    for first,last,dh in [(0,1,'a'),(2,3,'b')]:
        item=part(first,last,dh);root=tmp_path/f'part{first}';root.mkdir()
        item['data']['metadata']['limits']=[]
        for frame in item['data']['frames']:
            i=frame['frame_index'];image=f'images/frame_{i}.jpg';mask=f'masks/frame_{i}.png'
            for name in (image,mask):
                path=root/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'test'+str(i).encode())
            frame['review_image']=image
            frame['people']=[{'label':'person','region_bbox_xyxy':[i,0,i+10,20],
                              'surface_camera_image_m':[.01*i,0,3], 'status':'surface_candidate',
                              'region_mask':mask}]
        (root/'results.json').write_text(json.dumps(item['data']))
        files=[p for p in root.rglob('*') if p.is_file()]
        item['manifest'].update(status='complete',files_sha256={str(p.relative_to(root)):digest(p) for p in files})
        (root/'manifest.json').write_text(json.dumps(item['manifest']))
        alignment=tmp_path/f'align{first}.json';alignment.write_text(json.dumps(item['alignment']))
        paths.append((root,alignment))
    output=tmp_path/'merged'
    monkeypatch.setattr(sys,'argv',['merge','--part',str(paths[1][0]),str(paths[1][1]),
        '--part',str(paths[0][0]),str(paths[0][1]),'--first-frame','0','--frame-count','4',
        '--require-full-svo','--output',str(output)])
    main()
    result=json.loads((output/'results.json').read_text())
    tracked=associate_frames(result['frames'])
    assert [f['observations'][0]['track_id'] for f in tracked]==[1,1,1,1]
    assert result['metadata']['merged_frame_range']['full_svo_verified']
    assert (output/'images/frame_3.jpg').is_file()
