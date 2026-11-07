# 次回用：速度計測と区間サイズの選択

実行中の解析には適用しない。今の処理が終了してから以下を実行する。`benchmark-all` は、初期設定ではグループ2の `recording_001` を全フレーム使い、69フレーム／90フレーム／69フレームの順に３回独立して解析する。区間ごとにSVO全体を読むこと、NEURAL深度、CPU人物検出、ハッシュ検証は維持する。初回と再測定を挟むことで、キャッシュや一時的な負荷による差を小さくするが、完全には除けない。

90フレーム版を全体処理に使う条件は次のすべてを満たすこと。

- 基準２回と候補１回が成功する。
- フレーム・時刻・検出数・ID・状態が両方の基準と一致し、対応する全位置の距離差が１cm以下。比較可能な位置は10個以上。
- 候補の総時間が、２回の基準のそれぞれより５％以上短い。

条件を満たさない場合や候補が実行失敗した場合は従来の69フレームで続ける。基準が失敗した場合は一括処理を開始しない。比較は同じ１録画上での安全確認であり、全録画で認識精度や短縮率を保証するものではない。人物検出のGPU化、SVOの読み直しやハッシュの削減はこの版では行っていない。

各録画の `analysis/<録画名>/timing.json` と、SSDの `benchmarks/<日時>/benchmark_report.json` に計測結果を残す。端末にはSVOハッシュ、SDK初期化、フレーム取得・画像保存、点群圧縮、書き出し検証、深度照合、人物解析の時間を表示する。SDK子プロセス全体の時間にはその内部処理が含まれるため、全数値を単純に合計しない。フレーム取得時間にはSDK処理と画像保存が混在し、人物解析時間にはデータ読込やモデル初期化も含む。

テストは３回分の録画全体を処理するため、時間とSSD容量が必要。例として、元の１回が８分なら約24分が目安だが、実際の時間は変わる。各回の処理開始時には、元のパイプラインと同じ容量チェックを行い、必要量と５ GiBの余裕がなければ停止する。テストの画像・点群・再生・座標・ログはすべてSSDの `benchmarks` 以下に残し、共有フォルダへコピーしない。自動削除もしない。

## Windows での実行

現在の処理が完了してからPowerShellで実行する。計測後、選ばれた区間サイズで一括処理を開始する。すでに共有済みの録画は照合のうえ再利用し、上書きしない。

```powershell
$LocalRoot = 'G:\kaiseki1005'
$BundleShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_ssd_portable_benchmark_20261105_01'
$CoordShare = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_003_coordinates_20261105_01'

powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_local_depth.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" `
  -SharedRoot "$CoordShare" -Mode benchmark-all
```

グループ３など別の録画を測る場合は、末尾に `-BenchmarkGroup 3 -BenchmarkRecording recording_001` を指定する。一括実行対象は引き続きグループ２・３の一覧全体。Windows SDKとPowerShellでの実行は未検証。計測結果を確認する際は、端末に出た `[Benchmark] Detailed timing report:` のパスを参照する。候補失敗時は `benchmarks/<日時>/candidate_90` のログも保持する。
