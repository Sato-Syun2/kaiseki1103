# グループ２・録画004／005：２人目のID候補

## 確認したこと

共有済みの人物座標を調べたところ、004にはID未確定で座標がある観測が287件、005には201件あった。これは検出観測の数であり、人数ではない。重複検出や人物以外の深度が混ざり得る。元座標のハッシュ、録画・校正・フレーム時刻、録画計画と試行進捗を確認。004は試行4・E06、005は試行5・E05で、どちらも計画上は２人の追い越し。計画だけで誰のIDか、実際の経路は確定しない。

SDK画像に既存座標を投影して見ると、後ろ側の人物についてID未確定ながら点が付く場面がある。後半では004のID6、005のID8が対象人物付近にあることを画像で確認した。これらを基点とし、時間を逆にたどりながら、未確定で座標のある候補の連続性と既存ID1からの分離、候補間の競合、方向、隣接時刻の高さと移動量をチェックした。元IDがある観測、全ての座標・時刻は変えず、欠測位置も作っていない。計算条件と各候補の理由は各フォルダの `assignments.json` に記録。

| 録画 | 既存の基点 | 新しい仮割当て | 候補の時刻範囲 | 残るID未確定（うち座標あり） |
|---|---:|---:|---|---:|
| 004 | ID6、frame 321 | 196観測 | 約3.51〜11.44秒 | 190（91） |
| 005 | ID8、frame 324 | 132観測 | 約6.15〜11.17秒 | 170（69） |

候補は範囲内の全フレームを埋めるものではなく、条件を満たした既存観測だけ。過去の単一高さの方法では004の基点ID6から8件しかつながらず、005のID8は基点不足で処理できなかった。新方式は短い基点も利用し、直前の観測との高さの変化を確認する。ただし件数の増加は正解率の向上を意味しない。

既存画像から、最終候補の004は12フレーム、005は11フレームを選んで確認した。候補は多くの場面で対象人物付近に投影されるが、遠距離・重なり・脚付近では正否を断定できない。全候補と3D座標の正解を検証したものではなく、しきい値も開発用。ID6とID8は録画内の仮IDで、被験者番号ではない。候補以外の古いIDを統合する処理や、ほかの録画への自動適用は行っていない。

- [004：候補の上面再生](../results/tracking_v2/group002_004_identity_temporal_20261105_01/index.html) / [004：同じ時刻の画像で確認](../results/tracking_v2/group002_004_identity_temporal_20261105_01/review.html)
- [005：候補の上面再生](../results/tracking_v2/group002_005_identity_temporal_20261105_01/index.html) / [005：同じ時刻の画像で確認](../results/tracking_v2/group002_005_identity_temporal_20261105_01/review.html)

## WindowsのSSDで映像と候補を同時再生

元の一括解析を動かしたまま、別のPowerShellで実行できる。候補の共有先には位置と照合記録のみを置き、動画・点群はコピーしない。SSDの元画像・深度候補・座標を照合し、元の再生HTMLとは別の候補HTMLを作る。進行中の再生一覧は書き換えない。

```powershell
$LocalRoot = 'G:\kaiseki1005'
$SourceBundle = Join-Path $LocalRoot 'depth_ssd_portable_20261105_01'
$ViewerShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_identity_viewer_20261105_01'
$Candidates = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_identity_candidates_20261105_01'

foreach ($Number in @('004', '005')) {
  $CandidateShare = Join-Path $Candidates "g002_recording_${Number}_temporal_20261105_01"
  powershell -NoProfile -ExecutionPolicy Bypass -File "$ViewerShare\corridor_tracking\bootstrap_identity_viewer.ps1" `
    -ViewerShare "$ViewerShare" -LocalRoot "$LocalRoot" -SourceBundle "$SourceBundle" `
    -CandidateShare "$CandidateShare" -Group 2 -Recording "recording_$Number"
  if ($LASTEXITCODE -ne 0) { throw "Candidate replay failed for recording_$Number; preserve existing files." }
}
```

完了したら次のHTMLを開く。`candidate` と白縁・破線は未確認の仮割当て。

- `G:\kaiseki1005\analysis\g002_recording_004_20261105_01\merged\portable_candidate_replay.html`
- `G:\kaiseki1005\analysis\g002_recording_005_20261105_01\merged\portable_candidate_replay.html`

既存候補の同名HTMLがある場合は上書きせず停止する。Windows側での今回の候補再生は未検証。
