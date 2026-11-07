# 次回用：深度解析の進捗と終了予想

実行中の `depth_ssd_portable_20261105_01` は変更しない。進捗表示版は新しい `depth_ssd_portable_progress_20261105_02` として準備した。現在の処理が終了してから使用する。

各録画の開始・終了時に全体の録画数を表示する。処理中の録画は、完了した区間数、現在の処理、経過時間、この録画の残り時間、全体の残り時間と予想終了時刻を表示する。SDK内部の処理で他の表示が止まるときも、約15秒ごとに進捗を出す。SDKや人物検出の従来ログも表示する。

```text
[Progress] 7/109 recordings complete; starting group 2 recording_008.
[進捗] G002 recording_008 | 全体完了 7/109 録画 | この録画 1/6 区間 | 人物検出と深度解析 2/6 | 経過 00:04:20 | この録画の残り: 約 00:17:50 | 全体の残り: 約 30:05:10 / 完了予想 11/07 01:10（目安）
```

予想時間は、実際に完了した区間と新規に完了した録画の処理時間から計算する。最初は `算定中`。記録時間・人物数・深度や保存先の速度により大きく変動し、区間の途中では処理済みフレーム数を推測しない。完了済み録画の確認にかかる時間は全体予想に正確には反映されない。表示時刻はWindows PCの時計とタイムゾーンに従う。

次回の実行例。旧処理がすべて完了していれば、検証済みの同名結果は上書きせず再利用する。この一覧にはグループ2・3の109録画が記載されている。未完了の途中ファイルがある場合は自動的に再利用せず停止するため、エラーとデータを残して状況を確認する。

```powershell
$LocalRoot = 'G:\kaiseki1005'
$BundleShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_ssd_portable_progress_20261105_02'
$CoordShare = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_003_coordinates_20261105_01'

powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_local_depth.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" `
  -SharedRoot "$CoordShare" -Mode all
```

深度・画像・解析結果・再生は引き続きSSD上で扱い、共有するのは人物座標と照合記録のみ。UbuntuではSSD内の `kaiseki1005/depth_replay_index.html` をブラウザーで開く。Windows実機での新しい進捗表示は未検証。
