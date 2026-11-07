#!/usr/bin/env python3
"""Build the Goal A quality report from saved comparisons, without altering tracking outputs."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--artifacts-root',type=Path,default=Path('results/tracking_v2'))
    a=p.parse_args();root=a.run;records=read(root/'summary.json')
    destinations=['quality_report.md','reviewed_interval_metrics.csv','ablation_summary.json','adoption.json']
    if any((root/f).exists() for f in destinations):
        p.error('Report exists; do not overwrite a previous assessment')
    totals={k:sum(r['metrics'][k] for r in records['records']) for k in ['frames','raw_observations','baseline_points','candidate_points','baseline_tracks','candidate_tracks']}
    sources=sum((Counter(r['metrics']['sources']) for r in records['records']),Counter())
    removed=Counter();added=0
    for r in records['records']:
        d=read(root/r['recording']/'observations.json');tracking=read(root/r['recording']/'tracking.json')
        baseline={o['obs_id'] for o in d['observations'] if o['legacy_valid']}
        supported={o['obs_id'] for o in tracking['observations'] if o['xyz'] is not None and o['position_source'] in ['sdk_estimate','partial_observation_estimate']}
        added+=len(supported-baseline)
        by_id={o['obs_id']:o for o in tracking['observations']}
        removed.update(by_id[k]['position_source'] for k in baseline-supported)
    annotated=[r for r in records['records'] if r['visual_evaluation'] and r['visual_evaluation']['scores']['baseline']['person_checkpoints']]
    intervals=[x for r in annotated for x in r['visual_evaluation']['reviewed_intervals']]
    with (root/'reviewed_interval_metrics.csv').open('w',newline='') as f:
        fields=[k for k in intervals[0] if k!='samples'] if intervals else ['recording']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for x in intervals:
            w.writerow({k:json.dumps(x[k]) if isinstance(x[k],(list,dict)) else x[k] for k in fields})
    ablations={}
    for name in ['no_appearance','pelvis_only','no_pixel_prediction','no_branch_review']:
        path=a.artifacts_root/f'ablation_final_v2_{name}_20261104/summary.json'
        value=read(path)
        ablations[name]=dict(path=str(path),records=[dict(recording=r['recording'],metrics=r['metrics'],
                            scores=r['visual_evaluation']['scores'],reviewed_intervals=r['visual_evaluation']['reviewed_intervals']) for r in value['records']],
                            note='Same tracking implementation; ignore old tentative pre-overtake fields in these diagnostic runs')
    (root/'ablation_summary.json').write_text(json.dumps(ablations,ensure_ascii=False,indent=2)+'\n')
    adoption=dict(software_scope='Goal A P0-P5',default_tracking_changed=False,automatic_association='not_adopted',
                  partial_observations='not_adopted_for_pre_overtake_rear_person',
                  reasons=['Record 048 fragmentation and reviewed support loss remain',
                           'No confirmed earlier acquisition of the rear person before overtaking',
                           'Final results are not an untouched independent test'],
                  absolute_position_accuracy='not_evaluated',sdk_hardware='not_tested',
                  calibration_measurements='not_available',resolution_comparison='not_available',
                  completed_recordings=len(records['records']),failures=records['failures'],totals=totals,
                  sources=dict(sources),added_observation_ids=added,removed_baseline_observation_ids=dict(removed))
    (root/'adoption.json').write_text(json.dumps(adoption,ensure_ascii=False,indent=2)+'\n')
    md=['Goal A 比較・採否レポート（2026-11-04）','',
        'P0〜P5の実装・旧データでの比較・SDK再書き出し準備を実施した。新追跡候補は既定採用しない。',
        f'処理成功 {len(records["records"])} / 48、失敗 {len(records["failures"])}。旧位置 {totals["baseline_points"]:,}件、候補 {totals["candidate_points"]:,}件。生成ID数の総和は {totals["baseline_tracks"]} → {totals["candidate_tracks"]}。これらは診断値で、人物の真の人数・ID精度ではない。',
        f'新たに位置が付いた原観測IDは{added}件、旧位置から除外されたIDは{sum(removed.values())}件。部分観測推定は{sources["partial_observation_estimate"]}件で、補間・予測は位置数に含めていない。除外の内訳: '+json.dumps(dict(removed),ensure_ascii=False)+'。','',
        '1. 画像による人物対応の確認','',
        '38時点・61人物の疎な確認点と、7短区間・82保存画像を目視した。注釈は元画像から作り、衣服で録画内の人物を区別した。被験者番号は未確認。箱は近似的な可視領域であり、身体座標の厳密な正解ではない。',
        '最初の調整用は001/003/025、評価用は002/044/048。後に一括処理の不具合を005/021/026/035/040で調査した。評価側の結果を見た後も実装修正を行い、短区間注釈も追加している。最終結果を未見の独立評価とは呼ばない。','',
        '| 録画 | 確認点の位置一致 旧→候補 | ID変化下限 旧→候補 | 分断下限 旧→候補 | 人物間ID再利用下限 旧→候補 |',
        '|---|---:|---:|---:|---:|']
    for r in annotated:
        s=r['visual_evaluation']['scores'];b,c=s['baseline'],s['candidate']
        md.append('| '+r['recording']+' | '+' | '.join(f'{b[k]} → {c[k]}' for k in ['matched_positions','identity_changes_lower_bound','fragmented_identities_lower_bound','cross_person_id_reuse_lower_bound'])+' |')
    md += ['',
        '003は、SDK 1が橙色の人物から紫色の人物へ移る例と、旧・新IDの重複出力を含む。画像上の運動予測と一対一対応で確認点の取り違え・分断が減った。6.800秒付近の境界は混ざった骨格の疑いがあり、約0.133秒を対応保留にした。短区間では旧人物間ID再利用を除けたが、保留により紫色人物の位置取得割合は100%から約88%へ下がる。',
        '044も確認点で人物間ID再利用が減ったが、往路・復路を含む全体には分断が残る。048は2.7秒付近でSDK骨格の2D/3Dが大きく崩れ、複数の解析IDへ分かれる。短区間の取得割合と後続のID継続が悪化するため、自動採用条件を満たさない。','',
        '2. 確認済み短区間の取得率と欠測','',
        '保存画像の各時刻に対応する時間幅で重み付けし、区間端は最初・最後の確認画像時刻に限定した。画像間の真の連続可視性や、SDK関節が直接測られたかは保証しない。以下は観測に裏付けられた推定の代理指標。補間、予測、平滑化を除外した。','',
        '| 区間 / 人物 | 取得割合 旧→候補 | 最大欠測秒 旧→候補 | 候補の対応保留秒 |','|---|---:|---:|---:|']
    by_key={(x['interval_id'],x['person'],x['mode']):x for x in intervals}
    for key in sorted({(x['interval_id'],x['person']) for x in intervals}):
        b,c=[by_key[(*key,mode)] for mode in ['baseline','candidate']]
        md.append(f'| {key[0]} / {key[1]} | {b["support_fraction"]:.1%} → {c["support_fraction"]:.1%} | {b["max_missing_s"]:.3f} → {c["max_missing_s"]:.3f} | {c["ambiguous_s"]:.3f} |')
    md += ['',
        '追い越し前の後方人物の早期取得は改善確認できていない。001の対応する旧SDK 3の開始は約4.267秒で、候補も同じ。初期の部分遮蔽区間で取得できない時刻を、後から定速延長して埋めていない。',
        '以前に置いた追い越し時刻の粗い候補区間は、足の接地順等を十分に確定できていないため、正式な追い越し前取得時間・lead timeはnull（未評価）にした。過去の試行フォルダーの候補時刻に基づく参考値は採用判断に使用しない。将来の注釈でovertaking_status=confirmed_visual_bracketを明示した場合だけ、この指標を計算する。',
        '追加部分点の代表画像は visual_review_20261104/added_partial_review.jpg。001の16.201〜16.667秒、002の16.032〜17.099秒、003・039の終盤など、骨盤が画面外に出た後の上半身が主な根拠である。これは追い越し前の取得開始の改善とは異なる。3D位置が正確かは測量値がなく未評価。','',
        '3. 要素別比較と手動アンカー','',
        '| 003の比較 | 確認点での分断下限 | 人物間ID再利用下限 | 確認できた効果 |','|---|---:|---:|---|']
    notes={'no_appearance':'色特徴を失うと重複照合・接続が弱くなる',
           'pelvis_only':'部分推定の終盤追加点がなくなる。確認点IDは同じ',
           'no_pixel_prediction':'同一SDK ID内の人物交代を見逃す',
           'no_branch_review':'疎な確認点では同じだが、連続確認区間の境界で再利用が残る'}
    for name,value in ablations.items():
        r=next(r for r in value['records'] if r['recording']=='recording_003');c=r['scores']['candidate']
        md.append(f'| {name} | {c["fragmented_identities_lower_bound"]} | {c["cross_person_id_reuse_lower_bound"]} | {notes[name]} |')
    md += ['',
        '手動アンカーの実証は ../anchor_review_final_003_20261104/。初期候補（色特徴の強制拒否あり）で残る分断を、画像で確認した点から同じmanual:person_keyへ結び、自動結果と別JSON・別評価・切替再生にした。確認点の分断下限1→0。これは手動支援の結果で、最終自動候補の成績へ加算しない。アンカーの全軌跡への伝播も独立した正解ではない。','',
        '4. 試験・再現性・未検証範囲','',
        'CPU試験38件が通過（../pytest_final_20261104.txt）。一対一割当の厳密解、追い越し・ID変更/再利用、欠測・完全遮蔽、前景深度、部分観測、原観測保全、異常深度からの復帰、SDK分岐の保留、アンカー矛盾、旧新形式、別パス頭部、SDK失敗/EOF/画像時刻、既知点校正を検証した。SDKアダプターのモック試験を実機試験とは呼ばない。',
        '旧リプレイの回帰: ../legacy_regression_20261104/regression_report.json。録画001の243点の時刻とSDK IDが一致し、座標差は旧CSVの小数4桁丸め範囲（最大約0.000050m）。全48件の旧受付件数と原CSVハッシュもverification.jsonで凍結基準と照合する。',
        'ブラウザー: ローカルChromeで旧／候補／手動、時刻移動、派生点表示を実行。合成31フレームの全フレーム人物データと間引き画像でも、0.033秒の人物と0.000秒の画像が別時刻で表示されることを確認。画像を外部へ送信していない。',
        'SDK正本は zed_sdk_package/tracking_v2/、配布済みの新規フォルダーは /data/experiment_data/kaiseki1103/zed_sdk_package/tracking_v2_20261104_01/。全フレーム保存、頭部別パス、正常EOF/失敗の区別、時刻・新規性・設定・共分散・任意マスク、出力検証、PowerShell一括実行を実装した。旧SDK共有ファイルは変更していない。',
        'Ubuntuではlibnvidia-encode.so.1不足とGPUドライバー接続失敗でSDKを起動できない。Windowsでの短い実機試験とPowerShell実行確認、全SVO再書き出しはGoal B側。新しい測量値、実距離誤差、1080p、配置変更、頭部検出の実測効果も未検証。',
        '校正CLIと入力テンプレートは完成し、合成点で剛体変換・外れ値・独立点・欠測率を検証した。未測量の補正値を既存録画へ適用していない。','',
        '5. 採否と再実行','',
        '既存の既定動作を維持する。最終候補は明示的な--tracking-configでのみ選び、未採用として保存する。003/044の確認範囲のID改善、終盤の部分観測推定は確認できたが、048の悪化、全区間の正解不足、追い越し前の取得開始改善未確認が残る。絶対位置精度や完全遮蔽の解決を達成したとは判断しない。','',
        '```bash',
        'python3 process_group001_batch.py --first 1 --last 48 --input-tag 20261103 \\',
        '  --analysis-tag NEW_RUN --tracking-config configs/tracking_candidate_final_20261104.json \\',
        '  --annotations results/tracking_v2/visual_review_20261104/annotations_final.json',
        'python3 verify_tracking_run.py results/tracking_v2/NEW_RUN \\',
        '  --baseline results/tracking_v2/baseline_20261103/baseline.json \\',
        '  --report results/tracking_v2/NEW_RUN/verification.json',
        'python3 report_tracking_goal_a.py --run results/tracking_v2/NEW_RUN',
        '```','',
        '入力と出力、コード版は各録画のmanifest.json、実行引数と校正/設定/注釈ハッシュはrun_config.jsonに保存。旧結果と過去の候補を上書きせず、新しい出力名で再実行する。運用説明は docs/tracking_v2_usage.md、校正・撮影条件は docs/tracking_calibration_capture.md、Windows手順は zed_sdk_package/tracking_v2/README.md。']
    (root/'quality_report.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(root/'quality_report.md')


if __name__=='__main__':
    main()
