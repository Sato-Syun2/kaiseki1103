# グループ2録画001：深度候補のID再割当て

共有の座標結果には、ID未確定179観測のうち、廊下座標がある候補が107観測、座標がない候補が72観測あった。元データは変更しない。録画進捗と計画内の `plan_sha256` が一致し、録画001は試行1・E03（2人の追い越し）だった。計画上の役割を人物IDの正解として扱わない。

後半の既存ID 3を基点に、直前の候補を時系列で逆方向にたどった。連続時刻とXY移動、既存ID 1との分離、候補競合、基点の表面高さと進行方向を条件として、**63観測をID 3への未確認候補**にした。すべて既存の座標であり、位置の補間や修正はない。116観測は未確定のままで、うち44観測に座標があり72観測には座標がない。ID 2とID 3の統合、被験者番号の確定は行っていない。

候補63観測のうち、同一フレームのSDK画像が保存されていた20観測（フレーム141、144、153、156、159、162、165、168、173、176、182、185、188、191、194、197、200、203、206、209）では、投影点が後方から追い越す赤い服の人物付近にあることを確認した。既存ID 3の基点後フレーム212でも同じ人物付近に投影された。これは開発に使った録画の画像上の確認であり、残る43観測や奥行きの正確さ、他の録画に対する精度の検証ではない。

フレーム120・129付近には床や脚付近に投影される低い代表点、フレーム114には別の人物の頭付近に投影される候補もある。深度候補があるだけで同一人物と決めると混入するため、表面高さや位置関係が合わないものは保留した。再割当て条件は開発用のしきい値で、画像から得た3D正解もない。元画像を見ながら修正・確定する作業と、他録画の独立評価が必要。

- [仮割当て後の上面再生](../results/tracking_v2/group002_001_depth_reassociation_20261105_01/index.html)：白縁・破線は仮割当て。
- [同時刻の画像と候補の照合](../results/tracking_v2/group002_001_depth_reassociation_20261105_01/review.html)：元画像は既存のBODY出力を参照。
- [各仮割当てと判定条件](../results/tracking_v2/group002_001_depth_reassociation_20261105_01/assignments.json)

## Windows SSDで画像と同時再生

Windowsの一括解析が動作中でも、別のPowerShellで以下を実行できる。候補は座標と照合記録の2ファイルだけを別の共有先に置き、元の座標共有先は変更しない。SSD内の元画像・人物候補・元座標のハッシュとフレーム時刻を照合し、候補だけを重ねた別のHTMLを作る。進行中の一覧ファイルは書き換えない。Windows実機でのこのビューアーは未検証。

```powershell
$LocalRoot = 'G:\kaiseki1005'
$SourceBundle = Join-Path $LocalRoot 'depth_ssd_portable_20261105_01'
$ViewerShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_identity_viewer_20261105_01'
$CandidateShare = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_identity_candidates_20261105_01\g002_recording_001_20261105_01'

powershell -NoProfile -ExecutionPolicy Bypass -File "$ViewerShare\corridor_tracking\bootstrap_identity_viewer.ps1" `
  -ViewerShare "$ViewerShare" -LocalRoot "$LocalRoot" -SourceBundle "$SourceBundle" `
  -CandidateShare "$CandidateShare" -Group 2 -Recording 'recording_001'
```

完了後に `G:\kaiseki1005\analysis\g002_recording_001_20261105_01\merged\portable_candidate_replay.html` を開く。同じSSDをUbuntuで開く場合も、同じ `kaiseki1005/analysis/.../merged/portable_candidate_replay.html` をブラウザーで開く。画像をコピーせずSSD内の既存画像を参照する。`candidate`・白縁・破線は未確認の仮割当てを表す。
