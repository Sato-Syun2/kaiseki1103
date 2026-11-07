import json
import re

from body.corridor_tracking.sdk_body_replay import make_page


def test_page_preserves_frame_data_and_escapes_html():
    frames = [{"frame_index": 6, "elapsed_s": 0.201, "image": "<image>.jpg", "bodies": []}]
    page = make_page(frames, "recording_<006>", "source_<006>.svo2")
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', page)
    assert match is not None
    assert json.loads(match.group(1))["frames"] == frames
    assert "<image>" not in match.group(1)
    assert "recording_&lt;006&gt;" in page
    assert "source_&lt;006&gt;.svo2" in page
