"""Compare old and short-anchor candidate screening without altering source data."""
import argparse
import collections
from datetime import datetime
import json
from pathlib import Path

from corridor_tracking.audit_depth_tracking import digest, packet, read
from corridor_tracking.propose_trusted10_identities import evaluate as old_evaluate
from corridor_tracking.propose_trusted10_identities_live import candidate_root
from corridor_tracking.short_anchor_identity_v2 import evaluate as new_evaluate


def category(options):
    return 'none' if not options else 'unique' if len(options)==1 else 'ambiguous'


def describe(options):
    return [{'target':x[0],'reference':x[1],'observations':len(x[3])} for x in options]


def run(audit_path,output):
    if output.exists():raise FileExistsError(output)
    audit=read(audit_path);records=[];failures=[]
    for row in audit['records']:
        if row['condition_category']=='単独歩行':continue
        try:
            src=candidate_root(row['group'])/row['tag']; data,manifest=packet(src)
            if digest(src/'positions.json')!=row['filtered_positions_sha256'] or digest(src/'manifest.json')!=row['filtered_manifest_sha256']:
                raise ValueError('source differs from audit snapshot')
            old,_=old_evaluate(data['frames']);new,_=new_evaluate(data['frames'])
            records.append({'group':row['group'],'recording':row['recording'],'tag':row['tag'],
                            'condition_category':row['condition_category'],'condition_basis':row['condition_basis'],
                            'source_positions_sha256':digest(src/'positions.json'),
                            'old_status':category(old),'new_status':category(new),
                            'old_pairs':describe(old),'new_pairs':describe(new)})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            failures.append({'tag':row['tag'],'reason':str(exc)})
    counts=collections.Counter((r['old_status'],r['new_status']) for r in records)
    gains=[r for r in records if r['old_status']=='none' and r['new_status']=='unique']
    withheld=[r for r in records if r['old_status']=='unique' and r['new_status']!='unique']
    changed=[r for r in records if r['old_status']==r['new_status']=='unique' and r['old_pairs']!=r['new_pairs']]
    output.mkdir(parents=True)
    payload={'at':datetime.now().astimezone().isoformat(timespec='seconds'),'audit_sha256':digest(audit_path),
             'records':records,'failures':failures,'transitions':{f'{a}->{b}':n for (a,b),n in counts.items()},
             'gain_count':len(gains),'withheld_old_unique_count':len(withheld),'changed_unique_count':len(changed),
             'scope':'candidate availability, not measured identity accuracy; no images or source recordings modified'}
    (output/'benchmark.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 短い基点を使ったID候補の比較','','10 m版で基点IDの位置が５〜９フレームの場合も、既存の時系列検査に渡す。参照IDは10フレーム以上のまま。速度・高さ・競合の既存条件は変更しない。','',
           f"対象 {len(records)} 録画、照合エラー {len(failures)}。旧方式で候補なし→新方式で一組の候補 {len(gains)} 録画、旧一組→新方式で保留 {len(withheld)} 録画、一組の内容が変わった録画 {len(changed)}。",'',
           '| グループ | 録画 | 仮ID | 参照ID | 追加候補観測 |','|---|---|---:|---:|---:|']
    for r in gains:
        pair=r['new_pairs'][0];lines.append(f"| {r['group']} | {r['recording']} | {pair['target']} | {pair['reference']} | {pair['observations']} |")
    lines+=['','候補の数は正答数でも改善率でもない。新方式も基点と候補を自動選択しており、映像による全区間の検証はしていない。グループ６などの条件不明録画は人数や条件を推定せず、ID対応は仮説として扱う。',
            'この資料は実行時点のスナップショット。詳細・ソースハッシュは `benchmark.json` を参照。']
    (output/'report_ja.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'records':len(records),'failures':failures,'transitions':payload['transitions'],
                      'gains':len(gains),'withheld':len(withheld),'changed':len(changed)},ensure_ascii=False),flush=True)
    return 1 if failures else 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',type=Path,default=Path('results/tracking_v2/trusted10_quality_live_20261107_01/audit.json'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();return run(a.audit,a.output)


if __name__=='__main__':raise SystemExit(main())
