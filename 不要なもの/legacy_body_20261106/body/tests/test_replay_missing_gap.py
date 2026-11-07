import json
from pathlib import Path
import shutil
import subprocess
import sys

import cv2
import numpy as np
import pytest

from body.corridor_tracking.replay import write_replay
from body.tests.test_tracking import observation


@pytest.mark.skipif(not shutil.which('google-chrome'),reason='Chrome unavailable')
def test_replay_does_not_draw_across_missing_sdk_frames(tmp_path):
    """The browser draws one adjacent segment, not a bridge across frame 1."""
    image=tmp_path/'source.jpg';cv2.imwrite(str(image),np.zeros((720,1280,3),dtype=np.uint8))
    frames=[dict(frame_index=i,t=round(i*.1,3),timestamp_ns=str(10**18+i*10**8),image_path=str(image)) for i in range(4)]
    obs=[observation(i,round(i*.1,3),x=10-i*.1) for i in [0,2,3]]
    data=dict(frames=frames,observations=obs,camera={'width':1280,'height':720},duration_s=.3)
    result=dict(observations=[],derived=[],config={})
    output=tmp_path/'recording_001';output.mkdir()
    write_replay(output,data,result,{},'recording_001')
    html=(output/'index.html').read_text()
    hook='''<script>
      window.trackStrokes=0;
      const originalStroke=CanvasRenderingContext2D.prototype.stroke;
      CanvasRenderingContext2D.prototype.stroke=function(){
        if(this.canvas.id==='plan' && ['#0b8a67','#285db5','#cc6b16','#a4488f','#12899a','#9c4c39'].includes(this.strokeStyle))window.trackStrokes++;
        return originalStroke.call(this);
      };
    </script>'''
    html=html.replace("<script>\n'use strict';",hook+"<script>\n'use strict';",1)
    html+='''<script>
      const mode=document.getElementById('mode'),slider=document.getElementById('slider');
      mode.value='baseline';mode.dispatchEvent(new Event('change'));
      window.trackStrokes=0;slider.value='.3';slider.dispatchEvent(new Event('input'));
      document.body.dataset.strokeCount=window.trackStrokes;
    </script>'''
    smoke=output/'smoke.html';smoke.write_text(html)
    result=subprocess.run(['google-chrome','--headless','--disable-gpu','--no-sandbox',
        '--disable-background-networking','--no-first-run',f'--user-data-dir={tmp_path}/chrome',
        '--allow-file-access-from-files','--virtual-time-budget=1000','--dump-dom',smoke.as_uri()],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert 'data-stroke-count="1"' in result.stdout


@pytest.mark.parametrize('legacy',[False,True])
def test_reference_builder_supports_old_and_new_gap_handling(tmp_path,legacy):
    image=tmp_path/'source.jpg';cv2.imwrite(str(image),np.zeros((720,1280,3),dtype=np.uint8))
    root=tmp_path/'run';folder=root/'recording_001';folder.mkdir(parents=True)
    frames=[dict(frame_index=i,t=round(i*.1,3),timestamp_ns=str(10**18+i*10**8),image_path=str(image)) for i in range(3)]
    data=dict(frames=frames,observations=[observation(0,0),observation(2,.2)],
              camera={'width':1280,'height':720},duration_s=.2)
    write_replay(folder,data,dict(observations=[],derived=[],config={}),{},'recording_001')
    page=folder/'index.html'
    if legacy:
        text=page.read_text();old="&&p.t>prev.t&&adjacent)"
        assert old in text
        page.write_text(text.replace(old,"&&p.t>prev.t&&($('mode').value==='baseline'||adjacent))",1))
    metrics=dict(baseline_points=2,candidate_points=0,baseline_tracks=1,candidate_tracks=0)
    (root/'summary.json').write_text(json.dumps({'records':[{'recording':'recording_001','metrics':metrics}]}))
    script=Path(__file__).resolve().parents[2]/'body'/ 'build_group002_reference_pages.py'
    result=subprocess.run([sys.executable,'-m','body.'+script.stem,str(root),'--group','3'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    revised=(folder/'sdk_reference_gap_aware.html').read_text()
    assert '<option value="baseline" selected>' in revised
    assert "&&p.t>prev.t&&adjacent)" in revised
