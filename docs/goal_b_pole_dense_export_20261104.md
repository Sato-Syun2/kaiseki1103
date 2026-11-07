# Goal B: 既存ポール録画の高密度深度書き出し

`test_005` のSVOを再利用し、保存する深度点の画像上の間隔を8画素から2画素にします。新しい撮影は不要です。深度推定自体の解像度や精度を上げる設定ではなく、**既に計算される深度画像から保存する画素を増やす**操作です。細い支柱が暗い場合や背景と混ざる場合は、高密度にしても距離を確定できないことがあります。

ZED SDKが動作するWindows PCで、外付けSSDのFドライブと共有フォルダーが接続された状態でPowerShellに貼り付けてください。Pythonは以前のSDK書き出しで使用した環境です。元SVOと既存の結果は変更しません。新しい一次保存先と共有先に書き出します。

```powershell
Set-Location '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10'
python .\export_depth_batch.py `
  --local-root "$env:USERPROFILE\kaiseki1103_exchange" `
  --exchange-root '\\tsclient\_data_experiment_data\kaiseki1103\exchange\test005_dense_20261104_01' `
  --job test_005_dense 'F:\experiment_data\20261104_test\test_005\test_005.svo2' test_hallway_20261104_test005_candidate `
  --every-seconds 1 `
  --pixel-stride 2 `
  --depth-mode NEURAL
```

前回は0.5秒ごと・8画素間隔、今回は1秒ごと・2画素間隔なので、条件上の画素サンプル数は概ね8倍です。有効点や圧縮率により保存量は変わります。全フレーム分の高密度データをメモリに保持してから保存するため、空きメモリ・空き容量に余裕がある状態で実行してください。失敗や共有接続切断が起きた場合、ローカル結果を消さず、エラー内容を知らせてください。共有ミラーのみ失敗した場合は、共有接続を戻した後、同じパッケージの `sync_exchange.py` を使って新しい共有先に再送できます。

成功時は `batch_summary.csv` の対象ジョブが `validated_depth_export` となり、Ubuntu側に次が作成されます。

```text
/data/experiment_data/kaiseki1103/exchange/test005_dense_20261104_01/test_005_dense/depth_export/
  camera.json
  manifest.json
  frames.csv
  zed_depth_points.npz
  images/
```

返却後はSVOハッシュ・カメラ設定・画像と深度のサンプル番号・時刻を照合し、支柱の画像位置を深度値を見る前に確認します。9・11・13・15mも支柱上の点として識別できる場合に限り、距離の参考評価に進みます。既知距離は廊下端からポール中心までの公称値で、カメラ光学中心や支柱表面との差は別に扱います。この追加書き出しだけで独立した3D校正検証が完了するわけではありません。
