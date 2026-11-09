"""Build timestamp-aligned local-image review pages for three short-anchor pilots."""
import argparse
import csv
import hashlib
import html
import json
import os
from pathlib import Path

from corridor_tracking.audit_depth_tracking import digest, packet, read
from corridor_tracking.portable_depth_replay import validate_candidate
from corridor_tracking.prepare_group004_005_bundle import scope_calibration
from corridor_tracking.reassign_depth_identity import pixel_from_corridor, review_page
from zed_sdk_package.tracking_v2.validate_export import validate_export

ROOT=Path('/data/experiment_data/kaiseki1103/exchange')
PILOTS=[(2,'recording_005',[176,229,274,321]),(2,'recording_018',[179,285,377]),(4,'recording_030',[194,281,356])]


def run(output,summary_path):
    if output.exists():raise FileExistsError(output)
    summary=read(summary_path); records=[]
    with (ROOT/'depth_group002_003_inventory_20261105_01.csv').open(newline='',encoding='utf-8-sig') as f:
        inventory=list(csv.DictReader(f))
    base_path=Path('results/tracking_v2/group004_005_coordinate_audit_20261106_01/base_calibration.json')
    output.mkdir(parents=True)
    for group,recording,manual_frames in PILOTS:
        matches=[r for r in summary['records'] if r['group']==group and r['recording']==recording and r['status']=='candidate']
        if len(matches)!=1:raise ValueError(f'candidate missing or ambiguous: {group}/{recording}')
        item=matches[0];candidate_dir=Path(item['candidate_path']).parent
        candidate=read(candidate_dir/'positions.json');assignment=read(candidate_dir/'assignments.json')
        source=ROOT/'depth_group002_005_trusted10_20261106_01/originals'/item['tag']; original,_=packet(source)
        if validate_candidate(original,candidate,digest(source/'positions.json'))!=item['proposed_count']:
            raise ValueError('candidate and original mismatch')
        if group in (2,3):
            row=next(r for r in inventory if r['group']==str(group) and r['recording']==recording)
            body=Path(row['body_dir']);cal_path=Path(row['calibration']);cal=read(cal_path)
            if digest(cal_path)!=original['metadata']['calibration_sha256']:raise ValueError('calibration hash mismatch')
        else:
            body=ROOT/'group004_20261105_body_01'/recording/'body';cal=read(base_path)
        validate_export(body)
        camera=read(body/'camera.json')
        if camera['source_svo_sha256']!=original['metadata']['source_svo_sha256']:
            raise ValueError('review images and SVO source differ')
        if group==4:
            scoped=scope_calibration(cal,camera,digest(base_path))
            if scoped is None:hashes={digest(base_path)}
            else:
                text=json.dumps(scoped,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
                hashes={hashlib.sha256(x.encode()).hexdigest() for x in (text,text.replace('\n','\r\n'))}
                cal=scoped
            if original['metadata']['calibration_sha256'] not in hashes:raise ValueError('scoped calibration differs')
        with (body/'frames.csv').open(newline='',encoding='utf-8-sig') as f:body_frames=list(csv.DictReader(f))
        changes=assignment['assignments'];d=assignment['diagnostics'];target=d['target_id'];ref=d['reference_id']
        dest=output/f'g{group:03d}_{recording}';dest.mkdir()
        page,count=review_page(candidate['frames'],body_frames,body,camera,cal,dest,
            max(0,changes[0]['frame_index']-5),min(len(candidate['frames'])-1,d['anchor_frame']+5),target_id=target,reference_id=ref)
        replay=html.escape(os.path.relpath(candidate_dir/'index.html',dest),quote=True)
        page=page.replace('<a href="index.html">上面再生へ</a>',f'<a href="{replay}">上面再生へ</a>')
        page=page.replace('<a href="report_ja.md">条件と制約</a>','<a href="../index.html">確認対象一覧</a>')
        (dest/'review.html').write_text(page,encoding='utf-8')
        image_rows={int(r['frame_index']):r for r in body_frames};by_frame={a['frame_index']:a for a in changes}
        selected=[]
        for n in manual_frames:
            a=by_frame[n];img=image_rows[n]
            if not img['image_file'] or str(a['timestamp_ns'])!=img['image_timestamp_ns']:
                raise ValueError('selected review image missing or timestamp mismatch')
            image=body/img['image_file']
            selected.append({'frame_index':n,'elapsed_s':a['elapsed_s'],
                             'image_sha256':digest(image),'projected_pixel':pixel_from_corridor(a['surface_corridor_m'],camera,cal),
                             'image_file':str(image)})
        records.append({'group':group,'recording':recording,'target_id':target,'reference_id':ref,
                        'candidate_count':len(changes),'anchor_frame':d['anchor_frame'],'review_images':count,
                        'source_positions_sha256':digest(source/'positions.json'),
                        'candidate_positions_sha256':digest(candidate_dir/'positions.json'),
                        'body_manifest_sha256':digest(body/'manifest.json'),
                        'selected_frames':selected,'page':str(dest/'review.html')})
    info={'status':'sampled_visual_review_not_accuracy_validation','records':records,
          'notes':['Sample frames only; no frame-complete identity or ground-truth annotation.',
                   'Projection onto a person in 2D does not prove depth position accuracy.',
                   'At strongly overlapped early frames the person association may be uncertain.']}
    (output/'review_manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    rows=[]
    for r in records:
        link=html.escape(Path(r['page']).relative_to(output).as_posix(),quote=True)
        rows.append(f'<li>G{r["group"]:03d} {html.escape(r["recording"])}: ID {r["target_id"]} 候補 {r["candidate_count"]}観測 — <a href="{link}">元画像と照合</a>（{r["review_images"]}画像）</li>')
    page=('<!doctype html><html lang="ja"><meta charset="utf-8"><title>短い基点のID候補</title><h1>短い基点のID候補：画像照合</h1>'
          '<p>一部画像と投影点を照合した確認用ページです。全区間の人物IDや深度位置を検証したものではありません。紫の点は未確認の候補です。</p><ul>'+''.join(rows)+'</ul>'
          '<p><a href="review_manifest.json">選択フレームと入力ハッシュ</a></p></html>')
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({'pilots':len(records),'recordings':[r['recording'] for r in records]},ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--summary',type=Path,default=Path('results/tracking_v2/identity_short_anchor_v2_live_20261107_01/summary.json'))
    a=p.parse_args();run(a.output,a.summary)


if __name__=='__main__':main()
