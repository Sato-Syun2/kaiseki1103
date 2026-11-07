import csv
import json
from pathlib import Path
import subprocess
import sys

from corridor_tracking.data import sha256
from tests.sdk_fakes import FakeSource
from zed_sdk_package.tracking_v2.export_tracking import Settings, stream_export


def test_head_review_uses_exact_recording_and_produces_candidates(tmp_path):
    body=tmp_path/'body';heads=tmp_path/'heads';wrong=tmp_path/'wrong'
    stream_export(FakeSource(),body,Settings(),'a'*64,'test.svo2')
    stream_export(FakeSource(mode='heads'),heads,Settings(mode='heads'),'a'*64,'test.svo2')
    stream_export(FakeSource(mode='heads'),wrong,Settings(mode='heads'),'b'*64,'other.svo2')
    with (body/'frames.csv').open(newline='') as f: first=next(csv.DictReader(f))
    annotations=tmp_path/'annotations.json'
    annotations.write_text(json.dumps({'checkpoints':[dict(frame_index=0,t=0,
        timestamp_ns=first['image_timestamp_ns'],visible_head_bbox=[610,210,670,250],
        image_sha256=sha256(body/first['image_file']))]}))
    calibration=tmp_path/'calibration.json'
    calibration.write_text(json.dumps({'transform_camera_to_corridor':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}))
    script=Path(__file__).resolve().parents[2]/'body'/ 'review_goal_b_heads.py'
    def invoke(head_path,output):
        return subprocess.run([sys.executable,'-m','body.'+script.stem,'--body',str(body),'--heads',str(head_path),
            '--calibration',str(calibration),'--annotations',str(annotations),'--output',str(output)],
            capture_output=True,text=True)
    out=tmp_path/'review';result=invoke(heads,out)
    assert result.returncode==0,result.stderr
    review=json.loads((out/'review.json').read_text())
    assert review['checkpoints'][0]['head_detections'][0]['object_id']==7
    assert (out/'head_candidates_review.jpg').is_file()
    failed=invoke(wrong,tmp_path/'invalid')
    assert failed.returncode!=0 and 'matching source_svo_sha256' in failed.stderr
    assert not (tmp_path/'invalid').exists()
