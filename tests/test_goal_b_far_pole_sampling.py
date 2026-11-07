import csv
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image

from corridor_tracking.data import sha256


def test_far_pole_visualization_verifies_images_and_uses_saved_sample_indices(tmp_path):
    root=tmp_path/'depth';root.mkdir();(root/'images').mkdir()
    camera={'intrinsics_left':{'fx':1000,'fy':1000,'cx':0,'cy':0},'pixel_stride':8,'sample_period_s':.5}
    (root/'camera.json').write_text(json.dumps(camera))
    entries=[];points=[];times=[40.5,52.5,66.0,80.0]
    for i,(t,u,v) in enumerate(zip(times,[1170,1200,1215,1230],[315,275,245,225])):
        image=root/'images'/f'{i}.jpg';Image.new('RGB',(1920,1080),'gray').save(image)
        entries.append(dict(sample_index=i,frame_index=100+i*10,image_timestamp_ns=1000+i,
            elapsed_s=t,image_file=f'images/{i}.jpg',image_sha256=sha256(image),valid_depth_points=1))
        points.append([u*.01,v*.01,10.])
    with (root/'frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(entries[0]));w.writeheader();w.writerows(entries)
    np.savez_compressed(root/'zed_depth_points.npz',points_camera_image_m=np.asarray(points,dtype=np.float32),
        point_frame_index=np.arange(4,dtype=np.int32),frame_indices=np.arange(4,dtype=np.int32),
        frame_timestamps_ns=np.asarray([1000+i for i in range(4)],dtype=np.int64))
    names=['camera.json','frames.csv','zed_depth_points.npz']
    (root/'manifest.json').write_text(json.dumps({'files_sha256':{n:sha256(root/n) for n in names}}))
    script=Path(__file__).resolve().parents[1]/'diagnose_goal_b_far_pole_sampling.py'
    def run(out):
        return subprocess.run([sys.executable,str(script),'--depth-export',str(root),'--output',str(out)],
                              capture_output=True,text=True)
    output=tmp_path/'review';result=run(output)
    assert result.returncode==0,result.stderr
    report=json.loads((output/'summary.json').read_text())
    assert [x['station_m'] for x in report['selected']]==[9,11,13,15]
    assert [x['sample_index'] for x in report['selected']]==[0,1,2,3]
    assert [x['svo_frame_index'] for x in report['selected']]==[100,110,120,130]
    assert all(x['sampled_pixels_in_crop']==1 for x in report['selected'])
    assert (output/'far_pole_sampling.jpg').is_file()
    (root/'images/0.jpg').write_bytes(b'changed')
    bad=run(tmp_path/'invalid')
    assert bad.returncode!=0 and 'Image hash mismatch' in bad.stderr
    assert not (tmp_path/'invalid').exists()
