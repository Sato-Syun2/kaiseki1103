#!/usr/bin/env python3
"""Add image-specific review notes to a separate copy of an existing replay.

Only the ten reviewed group003/recording_002 images are marked. An unmarked
image has not been reviewed, and no marking implies a person ID or 3D truth.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from corridor_tracking.data import sha256
from corridor_tracking.evaluation import cross_person_anchors


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path,help='New HTML next to the source replay')
    p.add_argument('--manifest',required=True,type=Path,help='New metadata JSON')
    a=p.parse_args()
    root=Path('results/tracking_v2/group003_20261104_analysis_01')
    recording=root/'recording_002';source=recording/'sdk_reference_gap_aware.html'
    visual=Path('results/tracking_v2/goal_b_visual_holdout_20261104_01')
    annotations=visual/'annotations.json';plan=visual/'plan.json';rawfile=recording/'observations.json'
    if a.output.exists() or a.manifest.exists():raise FileExistsError('Output or manifest already exists')
    if a.output.resolve().parent!=recording.resolve():raise ValueError('Output must be next to source replay for relative image links')
    reference=json.loads((root/'reference_gap_aware_manifest.json').read_text())
    expected=reference['pages_sha256']['recording_002/sdk_reference_gap_aware.html']
    if sha256(source)!=expected:raise ValueError('Source replay differs from its reference manifest')
    ann=json.loads(annotations.read_text());original=json.loads(rawfile.read_text());predeclared=json.loads(plan.read_text())
    if sha256(rawfile)!=predeclared['observations_sha256']:raise ValueError('Observation input changed')
    html=source.read_text();match=re.search(r'<script id="data" type="application/json">(.*?)</script>',html,re.S)
    if match is None:raise ValueError('Unknown replay data template')
    data=json.loads(match.group(1));frames={f['timestamp_ns']:f for f in data['frames']}
    by_frame=defaultdict(list)
    for o in original['observations']:by_frame[o['frame_index']].append(o)
    reviewed=[]
    for item in ann['intervals'][0]['frames']:
        f=frames.get(item['timestamp_ns'])
        if not f or not f.get('image'):raise ValueError('Reviewed image not present in replay')
        if sha256(recording/f['image'])!=ann['image_sha256'][str(f['frame_index'])]:
            raise ValueError('Replay image differs from reviewed image')
        crossing=cross_person_anchors(by_frame[f['frame_index']],item['people'])
        if not crossing:raise ValueError('Expected reviewed crossing no longer detected')
        reviewed.append(f['frame_index'])
    if len(reviewed)!=len(set(reviewed)) or len(reviewed)!=10:raise ValueError('Unexpected reviewed image count')
    image_marker='<p id="imageClock"></p>'
    render_marker="const fi=D.frames[nearest(D.frames,time)].frame_index;"
    if html.count(image_marker)!=1 or html.count(render_marker)!=1:raise ValueError('Unknown replay structure')
    html=html.replace(image_marker,image_marker+'<p id="reviewNotice" class="notice" role="status"></p>',1)
    js="""const reviewedImages=new Set(REVIEWED);
const isReviewedOverlap=reviewedImages.has(images[i].frame_index);
$('reviewNotice').textContent=isReviewedOverlap
  ? 'この表示画像は目視確認済み。SDK骨格の関節が前後2人の可視領域にまたがります。人物ごとの位置は判別不能です。'
  : 'この表示画像は混在の目視確認対象外です。混在がないことを意味しません。';
""".replace('REVIEWED',json.dumps(reviewed))
    html=html.replace(render_marker,js+render_marker,1)
    a.output.write_text(html,encoding='utf-8')
    a.manifest.parent.mkdir(parents=True,exist_ok=True)
    metadata=dict(source_replay=str(source.resolve()),source_sha256=sha256(source),
        annotations_sha256=sha256(annotations),observations_sha256=sha256(rawfile),
        evaluation_sha256=sha256(Path('corridor_tracking/evaluation.py')),
        reviewed_frame_indices=reviewed,output=str(a.output.resolve()),output_sha256=sha256(a.output),
        script_sha256=sha256(Path(__file__)),
        scope='Review applies only to the displayed saved images, not all intervening video frames.')
    a.manifest.write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(a.output)


if __name__=='__main__':main()
