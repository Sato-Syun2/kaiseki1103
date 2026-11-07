import csv
import copy
import json
from pathlib import Path
import subprocess
import sys

from corridor_tracking.data import sha256
from tests.sdk_fakes import FakeSource
from zed_sdk_package.tracking_v2.export_tracking import Settings,stream_export


def test_compare_runs_same_timeline_and_never_claims_head_overlap_is_truth(tmp_path):
    body=tmp_path/'body';heads=tmp_path/'heads';wrong=tmp_path/'wrong'
    stream_export(FakeSource(),body,Settings(),'a'*64,'test.svo2')
    stream_export(FakeSource(mode='heads'),heads,Settings(mode='heads'),'a'*64,'test.svo2')
    stream_export(FakeSource(mode='heads'),wrong,Settings(mode='heads'),'b'*64,'wrong.svo2')
    with (body/'frames.csv').open(newline='') as f:first=next(csv.DictReader(f))
    annotations=tmp_path/'annotations.json';annotations.write_text(json.dumps({'checkpoints':[dict(
        frame_index=0,t=0,timestamp_ns=first['image_timestamp_ns'],visible_head_bbox=[610,210,670,250],
        image_sha256=sha256(body/first['image_file']))]}))
    calibration=tmp_path/'calibration.json';calibration.write_text(json.dumps({'transform_camera_to_corridor':
        [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}))
    config=tmp_path/'config.json';config.write_text(json.dumps({'appearance_weight':0}))
    script=Path(__file__).resolve().parents[2]/'body'/ 'compare_goal_b_heads.py'
    def run(head,output):
        return subprocess.run([sys.executable,'-m','body.'+script.stem,'--body',str(body),'--heads',str(head),
            '--calibration',str(calibration),'--config',str(config),'--annotations',str(annotations),
            '--output',str(output)],capture_output=True,text=True)
    out=tmp_path/'comparison';result=run(heads,out)
    assert result.returncode==0,result.stderr
    report=json.loads((out/'summary.json').read_text())
    assert report['body_only']['frames']==report['body_plus_heads']['frames']==3
    assert report['head_observations_with_valid_boxes']==3
    candidate=report['reviewed_checkpoints'][0]['head_candidates'][0]
    assert candidate['overlaps_annotated_region'] and not candidate['supported_position']
    assert report['adoption']=='not_adopted_pending_independent_identity_and_position_evaluation'
    assert 'not identity truth' in report['limitations'][0]
    assert (out/'body_only/index.html').is_file() and (out/'body_plus_heads/index.html').is_file()
    bad=run(wrong,tmp_path/'invalid')
    assert bad.returncode!=0 and 'matching source_svo_sha256' in bad.stderr
    assert not (tmp_path/'invalid').exists()
    crowded=tmp_path/'crowded';source=FakeSource(mode='heads');read=source.read
    def crowded_first_frame():
        frame=read()
        if frame is not None and source.i==1:
            second=copy.deepcopy(frame['detections'][0]);second[0]['object_id']=8
            frame['detections'].append(second)
        return frame
    source.read=crowded_first_frame
    stream_export(source,crowded,Settings(mode='heads'),'a'*64,'test.svo2')
    crowded_out=tmp_path/'crowded_comparison';crowded_result=run(crowded,crowded_out)
    assert crowded_result.returncode==0,crowded_result.stderr
    review=json.loads((crowded_out/'summary.json').read_text())
    candidates=review['reviewed_checkpoints'][0]['head_candidates']
    assert len(candidates)==2
    assert all(c['id_status']=='ambiguous' and c['position_source']=='two_d_only' for c in candidates)
    assert all(c['association_reason']['reason']=='ambiguous_head_body_proximity' for c in candidates)
