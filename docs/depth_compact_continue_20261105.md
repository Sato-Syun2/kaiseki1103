# 省容量で途中から解析を続ける

現在の処理をCtrl+Cで止め、元のターミナルにPowerShellのプロンプトが戻ってから実行する。旧プロセスが残っている場合は検出して開始しない。既存の完了済み録画と途中ファイルは変更しない。座標共有済みの録画は照合と再生確認を行って再利用し、停止した録画は未使用の名前で最初から解析する。018の `20261105_01_retry01` も認識する。

新しい録画は通常どおりSVOを読み、69フレーム区切り・NEURAL深度・圧縮NPZで解析する。区間の点群と元画像は、録画全体の結果が完成するまではSSDに必要。その後、SVOのSHA-256、共有した座標、元の区間と結合結果の画像・マスク・フレーム、動画付き再生を再度検証し、すべて一致したときに**その新しい録画で作った**点群NPZ、区間の元画像と重複したpart画像・マスクのみ削除する。結合後の確認画像とマスク、人物座標、校正、時刻、SDKログ、画像・点群の元ハッシュ、再生HTMLは残す。古い結果とベンチマークは整理しない。元のSVOは常に読み取り専用。

点群を再検証したくなったら、元のSVOからSDKで新たに再解析できる。ただし深度点が以前と完全に同一になる保証はない。画像付き再生は保存された確認画像を使うため、再生時にSVO・SDKは不要。整理したSDK区間・partフォルダの元のmanifestは作成時の記録であり、そこに列挙された重いファイルは存在しなくなる。録画フォルダの `storage_retention.json` に削除予定・削除済みの相対パス、サイズ、元のハッシュ、元SVO・最終結果・再生のハッシュを残す。

途中でエラー・中断した場合は元SVOと結果を残す。削除前の照合に失敗すると削除しない。削除途中で停止した場合、`storage_retention.json` は `prepared` のままになり、最終結果と未削除ファイルを保持して次回は自動的に停止するため、表示されたエラーを確認する。すでに共有済みでも省容量整理が未完了の録画を無断で再処理・再削除しない。

```powershell
$LocalRoot = 'G:\kaiseki1005'
$BundleShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_ssd_compact_continue_20261105_01'
$CoordShare = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_003_coordinates_20261105_01'

powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_compact_batch.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" -SharedRoot "$CoordShare"
```

1録画の処理中は点群を一時的に保管し、終了後に整理するため、最初からゼロ容量ではない。空き容量が不足する場合は停止する。共有先には従来どおり座標と照合記録だけを送る。新方式はUbuntu上の模擬試験と既存の90フレームの実データを使った確認済みだが、Windows SDK上の連続実行は未検証。実データ試験の元SVO照合はUbuntuに元SVOがないため模擬し、SVO検証自体は別のテストで確認した。
