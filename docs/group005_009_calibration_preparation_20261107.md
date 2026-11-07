# グループ５〜９の校正準備

グループ４・５の既存の深度処理はグループ４の暫定校正を使っている。５の校正を別途作って比較し、既存結果の扱いを判断する。グループ６〜９はグループごとの校正から作り、カメラ配置の同一性を自動的に仮定しない。グループ６は `calibration_002` のみを校正に使い、`calibration_001` は実験者申告による基本試行１の候補として表示する。

配布パッケージの `run_later_group_calibrations.ps1` は、SSD上にツールをコピー・ハッシュ照合してから実行する。引数なしはSVOと校正候補のファイル一覧だけを表示し、SDKやSVOの内容を処理しない。 `-Prepare` を指定すると指定グループごとに最初の30フレームをNEURAL深度でSSDに出力し、床・壁を推定する。候補の品質・設置条件を確認するまでは暫定であり、一括解析には自動投入しない。SVOと画像・深度は共有しない。途中で失敗した場合もファイルを保持し、出力済みの名前を再利用しない。

PowerShell実行例:

```powershell
$Tools = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_group005_009_calibration_20261107_02'
powershell -ExecutionPolicy Bypass -File "$Tools\run_later_group_calibrations.ps1"
# 現在のSDK解析の終了後、校正を実行する場合:
powershell -ExecutionPolicy Bypass -File "$Tools\run_later_group_calibrations.ps1" -Prepare
```

録画の親フォルダが既定値 `F:\experiment_data` と異なる場合は `-RecordingsRoot` を指定する。フォルダは親の直下の `*_group005`〜`*_group009` を検出し、同じグループの候補が複数あれば勝手に選ばない。追加試行は `1106test` と `20261106_test` 等の日付付き `*_test` の下の `test1`・`test2`、`test_001`・`test_002` 等を探す。試行との対応は名前からの推測にすぎず未検証。親フォルダ外のファイルは検出されない。複数候補、欠落、試行と録画ファイル名の食い違いは人が確認する。

校正出力名は `g005_calibration_depth_20261107_01` など。部分的に失敗した際は既存の出力を消さず、必要なグループを `-Groups 6` のように選び、未使用の `-RunId` を指定する。実際のWindows SDKでは未実行。正常終了後も、グループ５〜９の録画一括解析や10 m版を生成するツールではない。
