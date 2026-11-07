from types import SimpleNamespace

import numpy as np

from zed_sdk_package.tracking_v2.export_tracking import serialize_detection


class FakeSource:
    """A tiny deterministic source for I/O/failure tests; not tracking accuracy truth."""
    def __init__(self,frames=3,fail_at=None,mode='body'):
        self.expected_frames=frames
        self.i=0
        self.fail_at=fail_at
        self.mode=mode
        self.image_calls=0
        self.metadata=dict(width=1280,height=720,body_format='BODY_34',coordinate_system='IMAGE',
                           coordinate_units='meter',depth_mode='NEURAL',serial_number=42,setup_id='test',
                           intrinsics_left=dict(fx=800.,fy=800.,cx=640.,cy=360.))

    def read(self):
        if self.i==self.fail_at:
            raise RuntimeError('injected SDK retrieval failure')
        if self.i==self.expected_frames:
            return None
        i=self.i;self.i+=1
        obj=SimpleNamespace(id=7,tracking_state='OK',confidence=99.,
                            position=np.array([0.,0.,5.]),velocity=np.zeros(3),position_covariance=np.ones(6),
                            bounding_box_2d=np.array([[600,200],[680,200],[680,400],[600,400]]),
                            bounding_box=np.zeros((8,3)),keypoint_2d=np.tile([640.,300.],(34,1)),
                            keypoint=np.tile([0.,0.,5.],(34,1)),keypoint_confidence=np.full(34,90.),
                            keypoints_covariance=np.zeros((34,6)),head_position=np.array([0.,-.7,5.]),
                            label='PERSON',sublabel='PERSON_HEAD')
        stamp=str(10**18+i*33333333)
        return dict(image_timestamp_ns=stamp,svo_frame_index=i,detection_timestamp_ns=stamp,is_new=True,
                    retrieve_status='SUCCESS',detections=[serialize_detection(obj,self.mode,False)])

    def image(self):
        self.image_calls+=1
        return np.zeros((720,1280,3),dtype=np.uint8)
