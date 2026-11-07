#!/usr/bin/env python3
"""Full-frame, auditable ZED export. Run body and head detection in separate passes."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

VERSION = '2.0.0'
FRAME_FIELDS = ['frame_index','sample_index','svo_frame_index','image_timestamp_ns','elapsed_s',
                'detection_timestamp_ns','is_new','retrieve_status','image_file','body_count','object_count']
COMMON_FIELDS = ['frame_index','sample_index','image_timestamp_ns','elapsed_s','detection_timestamp_ns',
                 'is_new','tracking_state','confidence','position_json','velocity_json',
                 'position_covariance_json','bounding_box_2d_json','bounding_box_3d_json',
                 'mask_file','missing_fields_json']
BODY_FIELDS = COMMON_FIELDS + ['body_id','keypoints_2d_json','keypoints_3d_camera_json',
                              'keypoint_confidence_json','keypoints_covariance_json','head_position_json']
HEAD_FIELDS = COMMON_FIELDS + ['object_id','label','sublabel']


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def jsonable(value):
    if isinstance(value,np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value,(list,tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value,(np.integer,int)):
        return int(value)
    if isinstance(value,(np.floating,float)):
        return float(value) if math.isfinite(value) else None
    return value


def enum_name(value):
    return str(getattr(value,'name',value)).split('.')[-1]


@dataclass
class Settings:
    mode: str = 'body'
    body_model: str = 'ACCURATE'
    body_fitting: bool = True
    image_period_s: float = .1
    detection_confidence: float = 35
    minimum_keypoints: int = 8
    prediction_timeout_s: float = .2
    skeleton_smoothing: float = 0.
    depth_mode: str = 'NEURAL'
    jpeg_quality: int = 88
    segmentation: bool = False
    max_frames: int = 0
    setup_id: str | None = None

    def validate(self):
        if self.body_model not in ('ACCURATE','MEDIUM'):
            raise ValueError('Body model must be ACCURATE or MEDIUM (GEN_2)')
        if self.mode == 'body' and not self.body_fitting:
            raise ValueError('BODY_34 tracking automatically enables body fitting in this SDK; --no-body-fitting cannot produce a fitting-disabled comparison')
        if self.mode not in ('body','body18','heads') or self.image_period_s<=0 or not math.isfinite(self.image_period_s):
            raise ValueError('Mode must be body/body18/heads; image period must be finite and positive')
        if not 0<=self.prediction_timeout_s<=1 or not 0<=self.skeleton_smoothing<=1:
            raise ValueError('Prediction timeout and smoothing must be in [0,1]')
        if not 1<=self.detection_confidence<=100 or not 0<=self.minimum_keypoints<=(18 if self.mode=='body18' else 34):
            raise ValueError('Confidence must be [1,100]; minimum keypoints [0,34]')
        if not 0<=self.jpeg_quality<=100 or self.max_frames<0:
            raise ValueError('Invalid JPEG quality or frame limit')


def serialize_detection(obj,mode,segmentation):
    row = {'body_id' if mode in ('body','body18') else 'object_id':int(obj.id),
           'tracking_state':enum_name(obj.tracking_state),'confidence':jsonable(float(obj.confidence))}
    missing = {}
    attributes = {'position_json':'position','velocity_json':'velocity',
                  'position_covariance_json':'position_covariance','bounding_box_2d_json':'bounding_box_2d',
                  'bounding_box_3d_json':'bounding_box'}
    if mode in ('body','body18'):
        attributes.update(keypoints_2d_json='keypoint_2d',keypoints_3d_camera_json='keypoint',
                          keypoint_confidence_json='keypoint_confidence',
                          keypoints_covariance_json='keypoints_covariance',head_position_json='head_position')
    else:
        row.update(label=enum_name(obj.label),sublabel=enum_name(obj.sublabel))
    for field,attr in attributes.items():
        try:
            value = jsonable(getattr(obj,attr))
            row[field] = json.dumps(value,allow_nan=False,separators=(',',':'))
        except (AttributeError,RuntimeError) as exc:
            row[field] = 'null'
            missing[field] = type(exc).__name__+': '+str(exc)
    mask = None
    if segmentation:
        try:
            mat=obj.mask
            if mat.is_init():
                mask=np.asarray(mat.get_data()).copy()
            else:
                missing['mask_file']='SDK mask not initialized (state/depth may be invalid)'
        except (AttributeError,RuntimeError) as exc:
            missing['mask_file']=str(exc)
    else:
        missing['mask_file']='segmentation disabled explicitly'
    row['missing_fields_json']=json.dumps(missing,ensure_ascii=False)
    row['mask_file']=''
    return row,mask


class SDKSource:
    """Actual SDK adapter; no simulated detections in the production path."""
    def __init__(self,svo,settings):
        self.svo,self.settings=svo,settings
        self.camera=None
        self.positional_enabled=self.detector_enabled=False
        self.grabbed_frames=0

    def __enter__(self):
        import pyzed.sl as sl
        self.sl=sl
        try:
            init=sl.InitParameters()
            init.set_from_svo_file(str(self.svo.resolve()))
            init.svo_real_time_mode=False
            init.coordinate_units=sl.UNIT.METER
            init.coordinate_system=sl.COORDINATE_SYSTEM.IMAGE
            init.depth_mode=getattr(sl.DEPTH_MODE,self.settings.depth_mode)
            init.depth_minimum_distance=.25
            init.depth_maximum_distance=25.
            self.camera=sl.Camera()
            self.check(self.camera.open(init),'open')
            positional=sl.PositionalTrackingParameters()
            positional.set_as_static=True
            self.check(self.camera.enable_positional_tracking(positional),'positional tracking')
            self.positional_enabled=True
            if self.settings.mode in ('body','body18'):
                params=sl.BodyTrackingParameters()
                params.detection_model=getattr(sl.BODY_TRACKING_MODEL,'HUMAN_BODY_'+self.settings.body_model)
                params.model_gen=sl.BODY_TRACKING_MODEL_GEN.GEN_2
                params.body_format=sl.BODY_FORMAT.BODY_18 if self.settings.mode=='body18' else sl.BODY_FORMAT.BODY_34
                params.enable_body_fitting=self.settings.body_fitting
                runtime=sl.BodyTrackingRuntimeParameters()
                runtime.minimum_keypoints_threshold=self.settings.minimum_keypoints
                runtime.skeleton_smoothing=self.settings.skeleton_smoothing
                self.detections=sl.Bodies()
            else:
                params=sl.ObjectDetectionParameters()
                params.detection_model=sl.OBJECT_DETECTION_MODEL.PERSON_HEAD_BOX_ACCURATE
                runtime=sl.ObjectDetectionRuntimeParameters()
                self.detections=sl.Objects()
            params.enable_tracking=True
            params.enable_segmentation=self.settings.segmentation
            params.prediction_timeout_s=self.settings.prediction_timeout_s
            params.max_range=25.
            runtime.detection_confidence_threshold=self.settings.detection_confidence
            enable=self.camera.enable_body_tracking if self.settings.mode in ('body','body18') else self.camera.enable_object_detection
            self.check(enable(params),'enable '+self.settings.mode)
            self.detector_enabled=True
            self.detection_runtime=runtime
            self.runtime=sl.RuntimeParameters()
            self.runtime.measure3D_reference_frame=sl.REFERENCE_FRAME.CAMERA
            self.mat=sl.Mat()
            info=self.camera.get_camera_information()
            cfg=info.camera_configuration
            intr=cfg.calibration_parameters.left_cam
            self.expected_frames=int(self.camera.get_svo_number_of_frames())
            self.metadata=dict(sdk_version=str(sl.Camera.get_sdk_version()),camera_model=enum_name(info.camera_model),
                serial_number=int(info.serial_number),width=int(cfg.resolution.width),height=int(cfg.resolution.height),
                fps=float(cfg.fps),intrinsics_left={k:float(getattr(intr,k)) for k in ['fx','fy','cx','cy']},
                coordinate_units='meter',coordinate_system='IMAGE',reference_frame='CAMERA',
                image_view='LEFT_rectified',image_color_layout='SDK_BGRA_to_JPEG_BGR',
                depth_mode=enum_name(init.depth_mode),body_format=('BODY_18' if self.settings.mode=='body18' else 'BODY_34') if self.settings.mode in ('body','body18') else None,
                body_tracking_model='HUMAN_BODY_'+self.settings.body_model if self.settings.mode in ('body','body18') else None,
                body_tracking_model_gen='GEN_2' if self.settings.mode in ('body','body18') else None,
                detection_model=enum_name(params.detection_model),positional_tracking_static=True,
                body_fitting=bool(params.enable_body_fitting) if self.settings.mode in ('body','body18') else None,prediction_timeout_s=float(params.prediction_timeout_s),
                body_fitting_setting_source='requested_parameters_not_independently_queried' if self.settings.mode in ('body','body18') else None,
                detection_confidence_threshold=float(runtime.detection_confidence_threshold),
                minimum_keypoints_threshold=int(runtime.minimum_keypoints_threshold) if self.settings.mode in ('body','body18') else None,
                skeleton_smoothing=float(runtime.skeleton_smoothing) if self.settings.mode in ('body','body18') else None,
                segmentation=bool(params.enable_segmentation),setup_id=self.settings.setup_id)
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def check(self,status,operation):
        if status!=self.sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f'{operation}: {status}')

    def read(self):
        status=self.camera.grab(self.runtime)
        if status==self.sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
            return None
        self.check(status,'grab')
        self.grabbed_frames+=1
        stamp=int(self.camera.get_timestamp(self.sl.TIME_REFERENCE.IMAGE).get_nanoseconds())
        if self.settings.mode in ('body','body18'):
            status=self.camera.retrieve_bodies(self.detections,self.detection_runtime)
            objects=self.detections.body_list
        else:
            status=self.camera.retrieve_objects(self.detections,self.detection_runtime)
            objects=self.detections.object_list
        self.check(status,'retrieve '+self.settings.mode)
        return dict(image_timestamp_ns=str(stamp),svo_frame_index=int(self.camera.get_svo_position()),
                    detection_timestamp_ns=str(self.detections.timestamp.get_nanoseconds()),
                    is_new=bool(self.detections.is_new),retrieve_status=enum_name(status),
                    detections=[serialize_detection(o,self.settings.mode,self.settings.segmentation) for o in objects])

    def image(self):
        self.check(self.camera.retrieve_image(self.mat,self.sl.VIEW.LEFT,self.sl.MEM.CPU),'retrieve image')
        bgra=np.asarray(self.mat.get_data())
        if bgra.ndim!=3 or bgra.shape[2]!=4:
            raise RuntimeError(f'Expected SDK BGRA image, got {bgra.shape}')
        return cv2.cvtColor(bgra,cv2.COLOR_BGRA2BGR)

    def __exit__(self,*args):
        if self.camera is not None:
            try:
                if self.detector_enabled:
                    if self.settings.mode in ('body','body18'):
                        self.camera.disable_body_tracking()
                    else:
                        self.camera.disable_object_detection()
                if self.positional_enabled:
                    self.camera.disable_positional_tracking()
            finally:
                self.camera.close()


def stream_export(source,output,settings,source_hash,source_path,command=None):
    """Save every acquired frame. The independent image clock never skips detection calls."""
    settings.validate()
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    start=time.monotonic()
    manifest=dict(schema_version=2,exporter_version=VERSION,status='running',mode=settings.mode,
                  source_svo_sha256=source_hash,settings=asdict(settings),command=command,
                  total_svo_frames=source.expected_frames,planned_frames=min(source.expected_frames,settings.max_frames)
                  if settings.max_frames else source.expected_frames,acquired_frames=0,saved_frames=0,
                  saved_images=0,saved_observations=0,errors=[],completion_scope=None)
    write_json(output/'manifest.json',manifest)
    metadata=dict(source.metadata,schema_version=2,source_svo=str(source_path),source_svo_sha256=source_hash,
                  exporter_version=VERSION,detection_kind=settings.mode,requested_settings=asdict(settings))
    write_json(output/'camera.json',metadata)
    first_stamp=last_stamp=None
    last_svo=None
    next_image_s=0.
    data_filename='bodies.csv' if settings.mode in ('body','body18') else 'heads.csv'
    try:
        (output/'images').mkdir()
        if settings.segmentation:
            (output/'masks').mkdir()
        with ExitStack() as stack:
            def writer(filename,fields):
                f=stack.enter_context((output/filename).open('w',newline='',encoding='utf-8'))
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
                return w
            frames=writer('frames.csv',FRAME_FIELDS)
            objects=writer(data_filename,BODY_FIELDS if settings.mode in ('body','body18') else HEAD_FIELDS)
            assets=writer('assets.csv',['path','sha256','frame_index','image_timestamp_ns','kind'])
            while True:
                if settings.max_frames and manifest['acquired_frames']>=settings.max_frames:
                    manifest['completion_scope']='requested_frame_limit'
                    break
                f=source.read()
                if f is None:
                    manifest['completion_scope']='full_svo_eof'
                    break
                idx=manifest['acquired_frames']
                manifest['acquired_frames']+=1
                stamp=int(f['image_timestamp_ns'])
                if last_stamp is not None and stamp<=last_stamp:
                    raise ValueError('Non-increasing image timestamps')
                if last_svo is not None and int(f['svo_frame_index'])!=last_svo+1:
                    raise ValueError('SVO position skipped or repeated')
                last_stamp,last_svo=stamp,int(f['svo_frame_index'])
                if first_stamp is None:
                    first_stamp=stamp
                elapsed=(stamp-first_stamp)/1e9
                image_file=''
                if elapsed+1e-9>=next_image_s:
                    image_file=f'images/frame_{idx:08d}.jpg'
                    pixels=source.image()
                    if tuple(pixels.shape[:2])!=(metadata['height'],metadata['width']):
                        raise ValueError('Image resolution differs from camera metadata')
                    if not cv2.imwrite(str(output/image_file),pixels,[cv2.IMWRITE_JPEG_QUALITY,settings.jpeg_quality]):
                        raise OSError('Could not save '+image_file)
                    assets.writerow(dict(path=image_file,sha256=sha256(output/image_file),frame_index=idx,
                                         image_timestamp_ns=str(stamp),kind='image'))
                    manifest['saved_images']+=1
                    next_image_s=(math.floor((elapsed+1e-9)/settings.image_period_s)+1)*settings.image_period_s
                common=dict(frame_index=idx,sample_index=idx,image_timestamp_ns=str(stamp),elapsed_s=elapsed,
                            detection_timestamp_ns=f['detection_timestamp_ns'],is_new=str(f['is_new']).lower())
                for j,(row,mask) in enumerate(f['detections']):
                    if mask is not None:
                        mask_file=f'masks/frame_{idx:08d}_detection_{j:04d}.png'
                        if not cv2.imwrite(str(output/mask_file),mask):
                            raise OSError('Could not save '+mask_file)
                        row=dict(row,mask_file=mask_file)
                        assets.writerow(dict(path=mask_file,sha256=sha256(output/mask_file),frame_index=idx,
                                             image_timestamp_ns=str(stamp),kind='mask'))
                    objects.writerow(dict(row,**common))
                    manifest['saved_observations']+=1
                frames.writerow(dict(common,svo_frame_index=f['svo_frame_index'],retrieve_status=f['retrieve_status'],
                                     image_file=image_file,body_count=len(f['detections']) if settings.mode in ('body','body18') else 0,
                                     object_count=len(f['detections']) if settings.mode=='heads' else 0))
                manifest['saved_frames']+=1
                if idx%300==0:
                    print(f'{idx+1}/{manifest["planned_frames"]} frames; {elapsed:.2f} s',flush=True)
            if not manifest['saved_frames'] or manifest['saved_frames']!=manifest['planned_frames']:
                raise ValueError(f'Incomplete frame count: {manifest["saved_frames"]}/{manifest["planned_frames"]}')
        manifest['file_hashes']={name:sha256(output/name) for name in ['camera.json','frames.csv',data_filename,'assets.csv']}
        manifest['status']='complete'
    except BaseException as exc:
        manifest.update(status='failed',errors=[dict(type=type(exc).__name__,message=str(exc))])
        raise
    finally:
        manifest['acquired_frames']=getattr(source,'grabbed_frames',manifest['acquired_frames'])
        manifest.update(elapsed_wall_s=time.monotonic()-start,first_image_timestamp_ns=str(first_stamp),
                        last_image_timestamp_ns=str(last_stamp),exporter_sha256=sha256(Path(__file__)))
        write_json(output/'manifest.json',manifest)
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('svo',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['body','body18','heads'],default='body')
    p.add_argument('--body-model',choices=['ACCURATE','MEDIUM'],default='ACCURATE',help='BODY_18/BODY_34 GEN_2 model; used in body mode')
    p.add_argument('--no-body-fitting',dest='body_fitting',action='store_false',help='Request disabled fitting in body18 mode; BODY_34 requires fitting')
    p.add_argument('--image-period-s',type=float,default=.1)
    p.add_argument('--detection-confidence',type=float,default=35)
    p.add_argument('--minimum-keypoints',type=int,default=8)
    p.add_argument('--prediction-timeout-s',type=float,default=.2)
    p.add_argument('--skeleton-smoothing',type=float,default=0.)
    p.add_argument('--depth-mode',default='NEURAL')
    p.add_argument('--jpeg-quality',type=int,default=88)
    p.add_argument('--segmentation',action='store_true')
    p.add_argument('--max-frames',type=int,default=0,help='0=whole SVO; positive=smoke test only')
    p.add_argument('--setup-id')
    a=p.parse_args()
    settings=Settings(**{k:getattr(a,k) for k in Settings.__dataclass_fields__})
    settings.validate()
    if a.output.exists():
        p.error('Output must be a new directory')
    print('Hashing original SVO (read only)…',flush=True)
    source_hash=sha256(a.svo)
    # Startup failures are visible at the requested output as a failed manifest too.
    try:
        with SDKSource(a.svo,settings) as source:
            manifest=stream_export(source,a.output,settings,source_hash,str(a.svo.resolve()),sys.argv)
        print(json.dumps(manifest,ensure_ascii=False,indent=2))
    except BaseException as exc:
        if not a.output.exists():
            a.output.mkdir(parents=True)
            write_json(a.output/'manifest.json',dict(schema_version=2,status='failed',stage='SDK startup',
                       source_svo_sha256=source_hash,settings=asdict(settings),errors=[str(exc)]))
        raise
    return 0


if __name__=='__main__':
    raise SystemExit(main())
