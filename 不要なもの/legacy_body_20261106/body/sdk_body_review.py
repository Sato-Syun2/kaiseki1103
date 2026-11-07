#!/usr/bin/env python3
"""Review SDK BODY_34 in camera coordinates without reusing a corridor calibration."""
import argparse
import csv
import html
import json
from pathlib import Path

import cv2
import numpy as np

from body.compare_sdk_stability import digest, image_crop, load, measure, point, render, sample_frames


def chosen_images(saved, events, limit):
    """Include regular samples and images nearest to flagged full-rate events."""
    if not saved:
        return []
    regular = [saved[round(i*(len(saved)-1)/min(5, len(saved)-1))] for i in range(min(6, len(saved)))] if len(saved)>1 else saved[:]
    event_images = [min(saved, key=lambda frame: abs(frame-int(event['frame']))) for event in events]
    return list(dict.fromkeys(regular+event_images))[:limit]


def frame_counts(data):
    total=negative=outside=0
    w,h=data['camera']['width'],data['camera']['height']
    for detections in data['bodies'].values():
        for body in detections:
            total+=1
            joints=body['joints'];pixels=body['pixels']
            if joints and point(joints[0],3) and joints[0][2] <= 0:negative+=1
            if pixels and point(pixels[0],2) and not (0 <= pixels[0][0] < w and 0 <= pixels[0][1] < h):outside+=1
    return dict(sdk_body_observations=total,pelvis_z_nonpositive=negative,pelvis_2d_outside_image=outside)


def raw_image(data, frame, width=640, height=360, crop=None):
    row=data['byframe'][frame]; source=cv2.imread(str(data['folder']/row['image_file']))
    if source is None:raise ValueError(f'Cannot read image frame {frame}')
    if crop:
        x0,y0,x1,y1=crop
        source=source[y0:y1,x0:x1]
    scale=min(width/source.shape[1],height/source.shape[0])
    resized=cv2.resize(source,(max(1,round(source.shape[1]*scale)),max(1,round(source.shape[0]*scale))))
    canvas=np.full((height,width,3),35,np.uint8); x=(width-resized.shape[1])//2;y=(height-resized.shape[0])//2
    canvas[y:y+resized.shape[0],x:x+resized.shape[1]]=resized
    cv2.rectangle(canvas,(0,0),(width,32),(25,25,25),-1)
    cv2.putText(canvas,f'Original image | frame {frame} | {float(row["elapsed_s"]):.3f}s',(6,23),cv2.FONT_HERSHEY_SIMPLEX,.53,(255,255,255),1,cv2.LINE_AA)
    return canvas


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--setup-id',required=True)
    p.add_argument('--recording',action='append',help='optional recording folder name, repeatable')
    p.add_argument('--images-per-recording',type=int,default=12)
    a=p.parse_args()
    if a.output.exists():p.error('Output already exists')
    if not a.setup_id.strip() or a.images_per_recording<1:p.error('Valid setup ID and positive image count required')
    found=sorted(a.input_root.glob('recording_*/body'))
    if a.recording:
        wanted=set(a.recording)
        found=[q for q in found if q.parent.name in wanted]
        if {q.parent.name for q in found}!=wanted:p.error('One or more requested recordings are missing')
    if not found:p.error('No BODY exports found')
    inventory={}
    ipath=a.input_root/'input_inventory.csv'
    if ipath.is_file():
        with ipath.open(newline='',encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if row['recording'] in inventory:raise ValueError('Duplicate recording in input inventory')
                inventory[row['recording']]=row['source_relative_path']
    a.output.mkdir(parents=True,exist_ok=False)
    summary=[];failures=[];seen=set()
    fields=['frames','frames_with_position','position_observations','sdk_ids','adjacent_pairs','pelvis_jumps','one_sample_spikes','angle_observations','angles_below_20','adjacent_joint_angle_pairs','angle_changes_over_90']
    for folder in found:
        name=folder.parent.name
        try:
            data=load(folder);camera=data['camera']
            if camera.get('setup_id')!=a.setup_id:raise ValueError('BODY setup ID differs from expected camera setup')
            source_hash=camera.get('source_svo_sha256')
            if not source_hash or source_hash in seen:raise ValueError('Missing or duplicate source SVO hash')
            seen.add(source_hash)
            saved=sample_frames(data)
            if not saved:raise ValueError('No review images in BODY export')
            full=measure(data,[int(f['frame_index']) for f in data['frames']],max_dt=.05)
            sampled=measure(data,saved)
            info={'recording':name,'source_relative_path':inventory.get(name),'source_svo_sha256':source_hash,
                  'camera':{k:camera.get(k) for k in ('setup_id','serial_number','width','height','fps','depth_mode','intrinsics_left')},
                  'body_hashes':data['hashes'],'saved_image_count':len(saved),
                  'full_rate':{k:full[k] for k in fields},'saved_image_rate':{k:sampled[k] for k in fields},
                  **frame_counts(data)}
            dest=a.output/name;(dest/'images').mkdir(parents=True)
            cards=[]
            for frame in chosen_images(saved,full['events'],a.images_per_recording):
                original=raw_image(data,frame);overlay=render(data,frame,'SDK BODY_34 | same image time')
                crop=image_crop({'baseline':data},frame,camera['width'],camera['height'])
                zoom_original=raw_image(data,frame,crop=crop)
                zoom_overlay=render(data,frame,'SDK-based crop | same image time',crop=crop)
                canvas=np.concatenate([np.concatenate([original,overlay],axis=1),
                                       np.concatenate([zoom_original,zoom_overlay],axis=1)],axis=0)
                out=dest/'images'/f'frame_{frame:06d}.jpg'
                if not cv2.imwrite(str(out),canvas):raise OSError('Cannot save review image')
                row=data['byframe'][frame]
                cards.append(f'<section><h2>frame {frame} / {float(row["elapsed_s"]):.3f}秒</h2><img loading="lazy" src="images/{out.name}"></section>')
            info['selected_image_frames']=chosen_images(saved,full['events'],a.images_per_recording)
            info['full_rate_events']=full['events']
            (dest/'summary.json').write_text(json.dumps(info,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            page='<!doctype html><meta charset="utf-8"><title>SDK骨格確認</title><style>body{font:16px sans-serif;margin:24px}img{max-width:100%}section{border-top:1px solid #aaa}</style>'
            page+=f'<h1>{html.escape(name)} SDK BODY_34</h1><p>左は元画像、右は同じ画像時刻のSDK骨格。画像は約0.1秒間隔で、全フレームではありません。SDK ID・関節の信頼度は正解を保証しません。カメラ座標を使用し、他設置の廊下校正は使っていません。</p>'
            page+='<p>上段は全画像、下段はSDKの関節位置に基づく拡大表示です。SDKの誤位置によっては拡大枠に人物が入らないため全画像も確認してください。保存画像は等間隔の例と全フレームでの診断候補に最も近い画像を最大指定枚数選びます。候補のフレームそのものの画像とは限りません。上半身・下半身の混在や欠測も確認してください。</p>'
            page+='<pre>'+html.escape(json.dumps({k:v for k,v in info.items() if k!='full_rate_events'},ensure_ascii=False,indent=2))+'</pre>'+''.join(cards)+'<p><a href="summary.json">指標と全診断候補</a></p>'
            (dest/'index.html').write_text(page,encoding='utf-8')
            summary.append(info)
            print(f'{name}: {full["frames"]} frames, {full["pelvis_jumps"]} jump candidates, {len(saved)} saved images',flush=True)
        except Exception as exc:
            failures.append({'recording':name,'error':str(exc)})
            print(f'{name}: FAILED {exc}',flush=True)
    metadata={'status':'complete' if not failures else 'incomplete','setup_id':a.setup_id,
              'scope':'SDK diagnostic, not measured accuracy or verified person identity; camera coordinates only',
              'script_sha256':digest(Path(__file__)),'comparison_code_sha256':digest(Path(__file__).with_name('compare_sdk_stability.py')),
              'inventory_sha256':digest(ipath) if ipath.is_file() else None,
              'records':summary,'failures':failures}
    (a.output/'summary.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    rows=''.join('<tr><td><a href="'+html.escape(i['recording'])+'/index.html">'+html.escape(i['recording'])+'</a></td><td>'+html.escape(str(i.get('source_relative_path') or '未記録'))+'</td><td>'+str(i['full_rate']['frames'])+'</td><td>'+str(i['full_rate']['position_observations'])+'</td><td>'+str(i['full_rate']['adjacent_pairs'])+'</td><td>'+str(i['full_rate']['pelvis_jumps'])+'</td><td>'+str(i['pelvis_z_nonpositive'])+'</td><td>'+str(i['saved_image_count'])+'</td></tr>' for i in summary)
    page='<!doctype html><meta charset="utf-8"><title>SDK骨格の確認</title><style>body{font:15px sans-serif;margin:24px}table{border-collapse:collapse}th,td{border:1px solid #aaa;padding:6px}</style><h1>SDK骨格の確認（カメラ座標）</h1><p>自動値は精度や検出率ではありません。人物の見失いによって候補数が減る場合があります。各録画の元画像とSDK骨格を確認してください。旧設置の廊下校正は使っていません。</p><p>飛びの候補は同一SDK IDの隣接全フレームで骨盤移動0.75m超かつ6m/s超。正解による誤り判定ではなく、ID変更・欠測の影響を受けます。Z≤0はカメラ後方・原点の骨盤観測数です。</p><table><tr><th>出力番号</th><th>入力SVOの相対パス</th><th>全フレーム</th><th>骨盤位置数</th><th>比較可能な隣接組</th><th>飛び候補</th><th>Z≤0</th><th>保存画像</th></tr>'+rows+'</table><p>失敗 '+str(len(failures))+'件。<a href="summary.json">入力条件・全指標・エラー</a></p>'
    (a.output/'index.html').write_text(page,encoding='utf-8')
    print('report:',a.output/'index.html')
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
