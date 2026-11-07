import csv
import json
from types import SimpleNamespace

import numpy as np
import pytest

from zed_sdk_package.tracking_v2.export_tracking import Settings,SDKSource,stream_export,sha256
from zed_sdk_package.tracking_v2.validate_export import validate_export
from tests.sdk_fakes import FakeSource


def test_full_rate_detections_independent_image_clock(tmp_path):
    source=FakeSource(frames=31)
    folder=tmp_path/'export'
    m=stream_export(source,folder,Settings(),'a'*64,'test.svo2')
    assert m['saved_frames']==31 and m['saved_observations']==31
    assert source.image_calls==10 # last stamp is just below 1.0 s
    assert validate_export(folder)['frames']==31
    with (folder/'frames.csv').open() as f:
        rows=list(csv.DictReader(f))
    assert rows[1]['image_file']==''
    assert rows[1]['image_timestamp_ns']=='1000000000033333333'


def test_failure_and_smoke_limit_are_never_full_svo(tmp_path):
    folder=tmp_path/'failed'
    with pytest.raises(RuntimeError,match='injected'):
        stream_export(FakeSource(fail_at=2),folder,Settings(),'a'*64,'test.svo2')
    m=json.loads((folder/'manifest.json').read_text())
    assert m['status']=='failed' and m['saved_frames']==2
    with pytest.raises(ValueError,match='not complete'):
        validate_export(folder)
    folder=tmp_path/'limited'
    stream_export(FakeSource(frames=10),folder,Settings(max_frames=2),'a'*64,'test.svo2')
    with pytest.raises(ValueError,match='Limited smoke test'):
        validate_export(folder)
    assert validate_export(folder,allow_limited=True)['frames']==2


def test_heads_are_real_separate_schema_and_tampering_is_detected(tmp_path):
    folder=tmp_path/'heads'
    stream_export(FakeSource(mode='heads'),folder,Settings(mode='heads'),'b'*64,'test.svo2')
    assert (folder/'heads.csv').exists() and not (folder/'bodies.csv').exists()
    assert validate_export(folder)['mode']=='heads'
    (folder/'images/frame_00000000.jpg').write_bytes(b'damaged')
    with pytest.raises(ValueError,match='Asset hash'):
        validate_export(folder)


def test_premature_eof_rejected_and_output_cannot_be_overwritten(tmp_path):
    source=FakeSource()
    original=source.read
    source.read=lambda: None if source.i==2 else original()
    folder=tmp_path/'incomplete'
    with pytest.raises(ValueError,match='Incomplete frame count'):
        stream_export(source,folder,Settings(),'a'*64,'test.svo2')
    with pytest.raises(FileExistsError):
        stream_export(FakeSource(),folder,Settings(),'a'*64,'test.svo2')


def test_sdk_bgra_conversion_keeps_red_blue_channels():
    source=SDKSource(None,Settings())
    source.sl=SimpleNamespace(VIEW=SimpleNamespace(LEFT=1),MEM=SimpleNamespace(CPU=1),
                              ERROR_CODE=SimpleNamespace(SUCCESS=0))
    source.camera=SimpleNamespace(retrieve_image=lambda *a:0)
    source.mat=SimpleNamespace(get_data=lambda:np.array([[[10,20,230,255]]],dtype=np.uint8))
    assert source.image()[0,0].tolist()==[10,20,230]


def test_validator_catches_reused_image_even_with_updated_csv_hash(tmp_path):
    folder=tmp_path/'export'
    stream_export(FakeSource(frames=5),folder,Settings(image_period_s=.03),'a'*64,'test.svo2')
    with (folder/'frames.csv').open() as f:
        rows=list(csv.DictReader(f))
    rows[1]['image_file']=rows[0]['image_file']
    with (folder/'frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    m=json.loads((folder/'manifest.json').read_text())
    m['file_hashes']['frames.csv']=sha256(folder/'frames.csv')
    (folder/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='Image reused'):
        validate_export(folder)


@pytest.mark.parametrize('mode,body_model',[('body','ACCURATE'),('body','MEDIUM'),('heads','ACCURATE')])
def test_real_sdk_adapter_calls_every_frame_and_closes_on_failure(tmp_path,monkeypatch,mode,body_model):
    import sys,types
    ns=SimpleNamespace
    sdk=types.ModuleType('pyzed.sl')
    sdk.ERROR_CODE=ns(SUCCESS='SUCCESS',END_OF_SVOFILE_REACHED='EOF')
    for key,values in dict(UNIT=['METER'],COORDINATE_SYSTEM=['IMAGE'],DEPTH_MODE=['NEURAL'],
                           BODY_TRACKING_MODEL=['HUMAN_BODY_ACCURATE','HUMAN_BODY_MEDIUM'],BODY_TRACKING_MODEL_GEN=['GEN_2'],
                           BODY_FORMAT=['BODY_34'],OBJECT_DETECTION_MODEL=['PERSON_HEAD_BOX_ACCURATE'],
                           REFERENCE_FRAME=['CAMERA'],TIME_REFERENCE=['IMAGE'],VIEW=['LEFT'],MEM=['CPU']).items():
        setattr(sdk,key,ns(**{v:v for v in values}))
    class Init:
        def set_from_svo_file(self,path):self.path=path
    sdk.InitParameters=Init
    for key in ['PositionalTrackingParameters','BodyTrackingParameters','BodyTrackingRuntimeParameters',
                'ObjectDetectionParameters','ObjectDetectionRuntimeParameters','RuntimeParameters']:
        setattr(sdk,key,ns)
    sdk.Bodies=lambda:ns(body_list=[],timestamp=ns(get_nanoseconds=lambda:10**18),is_new=True)
    sdk.Objects=lambda:ns(object_list=[],timestamp=ns(get_nanoseconds=lambda:10**18),is_new=True)
    sdk.Mat=lambda:ns(get_data=lambda:np.zeros((4,4,4),dtype=np.uint8))
    class Camera:
        get_sdk_version=staticmethod(lambda:'mock-5.5')
        def __init__(self):self.calls=[];self.i=0;self.closed=False
        def open(self,p):self.init=p;return 'SUCCESS'
        def enable_positional_tracking(self,p):return 'SUCCESS'
        def enable_body_tracking(self,p):self.params=p;return 'SUCCESS'
        def enable_object_detection(self,p):self.params=p;return 'SUCCESS'
        def get_camera_information(self):
            return ns(camera_model='ZED2i',serial_number=42,camera_configuration=ns(resolution=ns(width=4,height=4),
                       fps=30.,calibration_parameters=ns(left_cam=ns(fx=3.,fy=3.,cx=2.,cy=2.))))
        def get_svo_number_of_frames(self):return 3
        def grab(self,r):self.i+=1;return 'SUCCESS'
        def get_timestamp(self,*a):return ns(get_nanoseconds=lambda:10**18+(self.i-1)*33333333)
        def get_svo_position(self):return self.i-1
        def retrieve_bodies(self,d,r):self.calls.append(('body',self.i,r));return 'ERROR_RETRIEVE' if self.i==2 else 'SUCCESS'
        def retrieve_objects(self,d,r):self.calls.append(('heads',self.i,r));return 'ERROR_RETRIEVE' if self.i==2 else 'SUCCESS'
        def retrieve_image(self,*a):return 'SUCCESS'
        def disable_body_tracking(self):pass
        def disable_object_detection(self):pass
        def disable_positional_tracking(self):pass
        def close(self):self.closed=True
    sdk.Camera=Camera
    package=types.ModuleType('pyzed');package.sl=sdk
    monkeypatch.setitem(sys.modules,'pyzed',package);monkeypatch.setitem(sys.modules,'pyzed.sl',sdk)
    settings=Settings(mode=mode,body_model=body_model,prediction_timeout_s=.1,skeleton_smoothing=.2)
    source=SDKSource(tmp_path/'fake.svo2',settings)
    with pytest.raises(RuntimeError,match='ERROR_RETRIEVE'):
        with source:
            stream_export(source,tmp_path/'export',settings,'a'*64,'fake.svo2')
    assert source.camera.closed
    assert [(m,i) for m,i,r in source.camera.calls]==[(mode,1),(mode,2)]
    assert source.camera.params.prediction_timeout_s==.1
    if mode=='body':
        assert source.camera.params.detection_model=='HUMAN_BODY_'+body_model
        assert source.metadata['body_tracking_model']=='HUMAN_BODY_'+body_model
        assert source.camera.params.model_gen=='GEN_2' and source.camera.params.body_format=='BODY_34'
        assert source.camera.calls[0][2].skeleton_smoothing==.2
    else:
        assert source.camera.params.detection_model=='PERSON_HEAD_BOX_ACCURATE'
    manifest=json.loads((tmp_path/'export/manifest.json').read_text())
    assert manifest['status']=='failed' and manifest['acquired_frames']==2 and manifest['saved_frames']==1
