import numpy as np
import pytest

from corridor_tracking.calibration import rigid_fit,robust_fit,apply_transform,errors


def test_known_pose_recovers_independent_points():
    rng=np.random.default_rng(42)
    a=rng.uniform([-1,-1,2],[1,1,15],size=(30,3))
    angle=.22
    R=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
    b=a@R.T+[.3,1.2,2.1]
    m=rigid_fit(a[:20],b[:20])
    assert np.allclose(apply_transform(a[20:],m),b[20:])
    assert np.linalg.det(m[:3,:3])==pytest.approx(1)


def test_ransac_does_not_fit_bad_correspondence():
    rng=np.random.default_rng(7)
    a=rng.normal(size=(20,3));b=a+[1,2,3];b[-1]+=[5,5,5]
    m,mask=robust_fit(a,b,.05)
    assert not mask[-1] and mask[:-1].all()
    assert np.allclose(m[:3,3],[1,2,3])


def test_collinear_central_poles_rejected():
    a=np.array([[0,0,3],[0,0,5],[0,0,7],[0,0,9]])
    with pytest.raises(ValueError,match='Collinear'):
        rigid_fit(a,a)


def test_error_metrics_do_not_hide_signed_bias():
    r=errors([[1.1,2,3],[2.9,2,3]],[[1,2,3],[3,2,3]])
    assert r['bias_xyz_m'][0]==pytest.approx(0,abs=1e-12)
    assert r['mae_xyz_m'][0]==pytest.approx(.1)
    assert r['euclidean_rmse_m']==pytest.approx(.1)


def test_calibration_cli_keeps_holdout_separate_and_reports_missing(tmp_path):
    import csv,json,subprocess,sys
    from pathlib import Path
    from calibrate_corridor import FIELDS
    rng=np.random.default_rng(16)
    camera=rng.uniform([-1,-1,2],[1,1,10],size=(10,3))
    target=camera+[2,1,.5]
    rows=[dict(zip(FIELDS,[f'p{i}','train' if i<7 else 'test','calibration' if i<7 else 'validation',*a,*b]),status='valid')
          for i,(a,b) in enumerate(zip(camera,target))]
    rows.append(dict(zip(FIELDS,['missing','test','validation','','','',8,1,1]),status='missing'))
    path=tmp_path/'points.csv'
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=[*FIELDS,'status']);w.writeheader();w.writerows(rows)
    meta=tmp_path/'camera.json';meta.write_text(json.dumps(dict(setup_id='test_setup',width=1280,height=720)))
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'calibrate_corridor.py'),str(path),
             '--camera',str(meta),'--setup-id','test_setup','--output',str(tmp_path/'calibrated')]
    run=subprocess.run(command,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=json.loads((tmp_path/'calibrated/calibration.json').read_text())
    assert result['validation_errors']['all']['euclidean_rmse_m']<1e-10
    assert result['missing_point_rate']['validation']['rate']==.25
    assert result['provisional'] is True
    # Reusing calibration locations as independent validation must fail.
    for k in FIELDS[6:9]:
        rows[7][k]=rows[0][k]
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=[*FIELDS,'status']);w.writeheader();w.writerows(rows)
    run=subprocess.run([*command[:-1],str(tmp_path/'rejected')],capture_output=True,text=True)
    assert run.returncode!=0 and 'independent locations' in run.stderr
