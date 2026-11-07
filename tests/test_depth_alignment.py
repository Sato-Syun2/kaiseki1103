import pytest
from corridor_tracking.depth_alignment import verify_metadata


def inputs():
    camera={'source_svo_sha256':'a'*64,'setup_id':'hall','serial_number':1,'width':12,'height':12,
            'depth_mode':'NEURAL','coordinate_units':'meter','coordinate_system':'IMAGE',
            'intrinsics_left':{'fx':1.,'fy':1.,'cx':1.,'cy':1.}}
    body=[{'frame_index':str(i),'image_timestamp_ns':str(1000+i*10),'svo_frame_index':str(i)} for i in range(3)]
    return camera, [dict(x) for x in body], body


def test_alignment_checks_requested_contiguous_frames():
    camera,depth,body=inputs()
    assert verify_metadata(camera,camera,depth,body,first=0,count=3)['continuous']
    with pytest.raises(ValueError,match='continuous range'):
        verify_metadata(camera,camera,depth[::2],body,first=0,count=3)


def test_alignment_rejects_timestamp_or_camera_mismatch():
    camera,depth,body=inputs()
    body[1]['image_timestamp_ns']='bad'
    with pytest.raises(ValueError,match='timeline differs'):
        verify_metadata(camera,camera,depth,body)
    camera,depth,body=inputs()
    with pytest.raises(ValueError,match='serial_number'):
        verify_metadata(camera,dict(camera,serial_number=2),depth,body)
