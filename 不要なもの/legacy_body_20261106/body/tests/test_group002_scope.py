import copy
import pytest
from body.analyze_group002_tracking import scope_calibration


def test_scope_records_subpixel_changes_and_rejects_different_setups():
    original=dict(setup_id='fixed',applies_to=dict(serial_number=123,width=1920,height=1080,
        depth_mode='NEURAL',coordinate_units='meter',coordinate_system='IMAGE (x right, y down, z forward)',
        intrinsics_left=dict(fx=1000.,fy=1000.,cx=900.,cy=500.)))
    target=dict(setup_id='fixed',**original['applies_to'])
    target['coordinate_system']='IMAGE'
    target['intrinsics_left']=dict(fx=1000.1,fy=1000.1,cx=900.,cy=500.)
    before=copy.deepcopy(original)
    result=scope_calibration(original,target,'hash')
    assert original==before
    assert result['scope_transfer']['intrinsics_delta_px']['fx']==pytest.approx(.1)
    assert result['scope_transfer']['status']=='provisional_not_survey_validated'
    with pytest.raises(ValueError,match='Setup IDs differ'):
        scope_calibration(original,dict(target,setup_id='other'),'hash')
    with pytest.raises(ValueError,match='more than one pixel'):
        scope_calibration(original,dict(target,intrinsics_left=dict(fx=1002,fy=1000,cx=900,cy=500)),'hash')
