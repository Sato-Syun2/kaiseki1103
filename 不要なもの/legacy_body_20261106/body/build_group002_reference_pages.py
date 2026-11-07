#!/usr/bin/env python3
"""Create additional comparison pages with SDK IDs selected initially."""
import argparse
import html
import json
from pathlib import Path
from corridor_tracking.data import sha256
from body.process_tracking_v2 import write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    p.add_argument('--group',choices=['2','3'],default='2')
    a=p.parse_args();root=a.run
    summary=json.loads((root/'summary.json').read_text())
    target=root/'sdk_reference_gap_aware_overview.html'
    if target.exists() or (root/'reference_gap_aware_manifest.json').exists():
        p.error('Reference pages already exist; do not overwrite')
    old='<option value="candidate">改善候補</option><option value="baseline">旧処理</option>'
    new='<option value="candidate">改善候補（未採用）</option><option value="baseline" selected>SDK ID（同一30fps）</option>'
    pages={};rows=[]
    for record in summary['records']:
        name=record['recording'];folder=root/name;source=folder/'index.html';dest=folder/'sdk_reference_gap_aware.html'
        if dest.exists():raise FileExistsError(dest)
        original=source.read_text(encoding='utf-8')
        if old not in original:raise ValueError('Unknown replay template: '+str(source))
        revised=original.replace(old,new,1)
        revised=revised.replace('座標校正は別途検証が必要です。','暫定校正です。SDK IDも人物の正解を保証しません。',1)
        expected="($('mode').value==='baseline'||adjacent)"
        if expected in revised:
            # Older generated pages allowed SDK tracks to bridge missing frames.
            revised=revised.replace(expected,'adjacent',1)
        elif "&&p.t>prev.t&&adjacent)" not in revised:
            raise ValueError('Unknown gap handling: '+str(source))
        dest.write_text(revised,encoding='utf-8');pages[str(dest.relative_to(root))]=sha256(dest)
        m=record['metrics']
        rows.append(f'<tr><td><a href="{html.escape(name)}/sdk_reference_gap_aware.html">{html.escape(name)}</a></td>'+ 
                    ''.join(f'<td>{m[k]}</td>' for k in ['baseline_points','candidate_points','baseline_tracks','candidate_tracks'])+'</tr>')
    group=html.escape(a.group);count=len(summary['records'])
    extra='<a href="pole_review_03/pole_regions.jpg">ポールの確認画像</a>' if a.group=='2' else 'ポールを用いた独立距離検証は未実施'
    target.write_text(f'<!doctype html><html lang="ja"><meta charset="utf-8"><title>グループ{group} 歩行軌跡</title>'
        '<style>body{font:16px system-ui,sans-serif;color:#173649;background:#f1f6f8;max-width:1100px;margin:30px auto;padding:0 16px}'
        'section{background:white;border-radius:10px;padding:20px;margin:16px 0}table{border-collapse:collapse;width:100%}'
        'td,th{padding:9px;border-bottom:1px solid #dae2e8;text-align:left}p{line-height:1.7}a{color:#145b91}</style>'
        f'<h1>グループ{group} 歩行軌跡：{count}録画</h1><section><p>各録画を選ぶとSDKの元IDで初期表示し、追跡候補にも切り替えられます。'
        '双方とも同じ30fpsデータです。候補にはID分断が多く、未採用です。SDK IDも人物の正解ではありません。'
        '座標は床・壁による暫定校正で、ポールによる距離精度は未検証です。</p>'
        '<p><a href="analysis_report.md">分析レポート</a> / <a href="summary.csv">一覧CSV</a> / '
        +extra+'</p></section><section><table>'
        '<tr><th>録画・再生</th><th>SDK位置数</th><th>候補位置数</th><th>SDK ID数</th><th>候補ID数</th></tr>'
        +''.join(rows)+'</table></section></html>',encoding='utf-8')
    pages[target.name]=sha256(target)
    write_json(root/'reference_gap_aware_manifest.json',dict(source_tracking_run=str(root.resolve()),
        script_sha256=sha256(Path(__file__)),pages_sha256=pages,
        default_mode='SDK original ID (not ground truth)',candidate_status='not_adopted'))
    print(target)


if __name__=='__main__':main()
