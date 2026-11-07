"""Local, standalone comparison pages; observations and images have separate clocks."""
import html
import json
import os
from pathlib import Path
import shutil

from .evaluation import baseline_points


def write_replay(output,data,result,calibration,recording,anchored=None):
    images = output/'images'; images.mkdir()
    frame_payload = []
    for f in data['frames']:
        row = {k:f[k] for k in ['frame_index','timestamp_ns','t']}
        row['image'] = None
        if f['image_path']:
            target = images/f'{f["frame_index"]:07d}.jpg'
            try:
                os.link(f['image_path'],target)
            except OSError:
                shutil.copyfile(f['image_path'],target)
            row['image'] = 'images/'+target.name
        frame_payload.append(row)
    raw = [{k:o[k] for k in ['obs_id','frame_index','t','sdk_id','pixels','joints','joint_confidence','state','kind']} for o in data['observations']]
    payload = dict(recording=recording,frames=frame_payload,raw=raw,baseline=baseline_points(data),
                   candidate=result['observations'],derived=result['derived'],duration_s=data['duration_s'],
                   anchored=anchored['observations'] if anchored else None,
                   anchored_derived=anchored['derived'] if anchored else None,
                   width=data['camera']['width'],height=data['camera']['height'],config=result['config'],
                   calibration_provisional=calibration.get('provisional',True))
    template = Path(__file__).with_name('replay_template.html').read_text()
    (output/'index.html').write_text(template.replace('__DATA__',json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')),encoding='utf-8')


def write_overview(output,summaries,failures):
    rows=[]
    md=['歩行者追跡 v2 比較結果','',
        '既存処理を保存したまま、新しい対応付け・部分観測処理を候補として評価した結果です。',
        'SDK由来の骨格にはフィッティングや予測が含まれ得ます。下記の位置数は現在の出力に裏付けられた推定の件数であり、独立した実測点数ではありません。',
        '全録画のID正解、連続した可視区間、絶対距離の正解は未整備です。疎な画像確認の評価は連続精度の下限・部分評価として扱います。',
        '', '| 録画 | 旧位置数 | 候補位置数 | 旧ID数 | 候補ID数 |', '|---|---:|---:|---:|---:|']
    for s in summaries:
        n,m=s['recording'],s['metrics']
        values=[m[k] for k in ['baseline_points','candidate_points','baseline_tracks','candidate_tracks']]
        rows.append(f'<tr><td><a href="{html.escape(n)}/index.html">{html.escape(n)}</a></td>'+''.join(f'<td>{v}</td>' for v in values)+'</tr>')
        md.append('| '+n+' | '+' | '.join(map(str,values))+' |')
    md += ['',f'処理成功: {len(summaries)}、失敗: {len(failures)}。','',
           '自動採用: 未採用。疎な画像確認と合成試験だけで全区間の改善を保証しません。',
           '部分観測・補間・運動予測はtracking.jsonおよびtrajectories.csvで別区分です。',
           'SDK実機の再書き出し、新しい測量点による絶対精度、1080p比較はGoal Bで検証します。',
           '', '画像確認区間の評価（調整用001/003/025、評価用002/044/048）:', '']
    for s in summaries:
        e=s['visual_evaluation']
        if e and e['scores']['baseline']['person_checkpoints']:
            md.append(f'{s["recording"]}: '+json.dumps(e['scores'],ensure_ascii=False))
    for fail in failures:
        md.append(f'失敗 {fail["recording"]}: {fail["error"]}')
    (output/'report.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>追跡比較</title><style>body{font:16px sans-serif;margin:30px;max-width:1100px}td,th{padding:8px;border:1px solid #ccd}table{border-collapse:collapse}p{line-height:1.7}</style><h1>歩行者追跡 v2 比較</h1><p>旧結果と改善候補を同じ時刻で比較します。補間・予測は別表示です。位置数・ID数の変化だけでは精度向上を意味しません。候補は自動採用していません。</p><p><a href="report.md">集計レポート</a> / <a href="summary.csv">集計CSV</a></p><table><tr><th>録画</th><th>旧位置数</th><th>候補位置数</th><th>旧ID数</th><th>候補ID数</th></tr>'+''.join(rows)+'</table>',encoding='utf-8')
