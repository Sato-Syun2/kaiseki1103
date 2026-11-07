# 深度点群の保存方式：速度と容量の比較

## 実測に基づく候補

Windowsのグループ２・001、69フレーム区切りのテストは494.0秒と492.4秒。90フレーム区切りは469.8秒で、５％短縮という採用基準には両方で届かなかったため69フレームが選択された。最初の69フレーム版ではSDK取得・画像保存159.1秒、人物解析156.4秒、点群アーカイブ作成87.0秒だった。各項目のうち人物解析には深度ファイルの読込等も含み、取得時間にも複数の処理が含まれる。

候補は点群NPZのZIP圧縮を省く `stored` 方式。圧縮以外は同一の配列形式・値・ハッシュ検証・人物検出を使う。Ubuntuでグループ３・018の既存NPZから15フレームを取り出して一時ファイルに書き、圧縮あり2.750秒・67,585,636バイト、圧縮なし0.133秒・98,593,350バイトだった。両方の全配列が元データと一致した。一時ファイルは削除済み。この測定はUbuntu上の小試験であり、Windows全体の短縮率ではない。

## 次回用パッケージ

`depth_ssd_portable_storage_20261105_01` は実行中の環境と別。`benchmark-storage-all` は同じ録画を69フレーム区切りのまま、圧縮あり／圧縮なし／圧縮ありの順で３回解析する。比較するのは総時間、全フレームの検出・ID、最大１cmの位置差とSSD保存量。圧縮なしが両基準より５％以上速く、両結果の照合に成功した場合だけ後続の一括処理に採用する。候補失敗・速度不足・結果不一致時は従来方式に戻し、基準が失敗した場合は一括処理を始めない。

点群・画像等とレポートはSSDの `storage_benchmarks` に残し、共有フォルダには送らない。ベンチマークには３録画分のSSD容量と処理時間が必要で、自動削除しない。圧縮なしの各録画開始時は、stride 2 の全点を保存した場合の配列サイズ、画像等の余裕、５ GiBの残容量で事前確認するが、出力サイズや他プログラムによる空き容量の変化を完全には予測できない。保存容量は圧縮ありより増える。

WindowsのSDK・PowerShellでの実機確認は未実施。実行中のバッチには適用しない。現在の処理が完了して、必要な場合に次を実行する。グループ２・018は前回再試行した保存名を指定することで、完了済みの再試行結果を読み直せる。

```powershell
$LocalRoot = 'G:\kaiseki1005'
$BundleShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_ssd_portable_storage_20261105_01'
$CoordShare = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_003_coordinates_20261105_01'

powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_local_depth.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" -SharedRoot "$CoordShare" `
  -Mode benchmark-storage-all -RetryGroup 2 -RetryRecording recording_018 `
  -RetryRunId 20261105_01_retry01
```
