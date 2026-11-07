# グループ3録画018：SDK再処理と指定フレーム深度出力

目的は、同一SVO・同じBODY設定で異常が再現するか確認し、異常前後のZED深度を確認すること。BODYと深度は別のSDK実行なので、深度出力がBODY処理時と完全に同じ値である保証はない。深度出力の深度範囲・NEURALモードとSDKランタイムの既定値はBODY用設定に合わせる。BODYでは固定カメラのpositional trackingとbody trackingを有効にするが、深度専用パスでは有効化しない。Ubuntu側で入力SVOのSHA-256・フレーム番号・時刻・カメラ設定を照合してから比較する。

Windows SDK PCで、ZED SDK 5.5.1・前回動いたPython環境のPowerShellを使う。`F:`のSVOパスは実際の場所に合わせる。既存の出力があれば停止するため、再実行時はタグと共有先を新しい名前に変える。プログラムと結果はWindowsのローカル領域に複製・保存してから共有に同期する。以下の一括コマンドをそのまま実行する。

```powershell
$SharedPackage = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261105_rec018_01'
$Svo = 'F:\experiment_data\20261104_group003\recording_018\recording_018.svo2'
$Setup = 'group003_hallway_20261104_candidate'
$LocalRoot = Join-Path $env:USERPROFILE 'kaiseki1103_exchange'
$ToolsParent = Join-Path $LocalRoot '.sdk_tools'
$LocalTools = Join-Path $ToolsParent 'rec018_20261105_01'
$LocalRun = Join-Path $LocalRoot 'rec018_diagnosis_20261105_01'
$SharedRun = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\rec018_diagnosis_20261105_01'

if (-not (Test-Path -LiteralPath $Svo -PathType Leaf)) { throw "SVOが見つかりません: $Svo" }
if (-not (Test-Path -LiteralPath $SharedPackage -PathType Container)) { throw "SDKパッケージが見つかりません: $SharedPackage" }
if ((Test-Path -LiteralPath $LocalTools) -or (Test-Path -LiteralPath $LocalRun) -or (Test-Path -LiteralPath $SharedRun)) { throw '出力先が既に存在します。上書きせず新しいタグを指定してください。' }
New-Item -ItemType Directory -Force -Path $ToolsParent | Out-Null
Copy-Item -Recurse -LiteralPath $SharedPackage -Destination $LocalTools
New-Item -ItemType Directory -Path $LocalRun | Out-Null
$Body = Join-Path $LocalRun 'body'
$Depth = Join-Path $LocalRun 'depth'

python "$LocalTools\export_tracking.py" "$Svo" --output "$Body" --setup-id "$Setup" --mode body
if ($LASTEXITCODE -ne 0) { throw 'BODY書き出しに失敗。ローカル途中出力を保管してください。' }
python "$LocalTools\validate_export.py" "$Body"
if ($LASTEXITCODE -ne 0) { throw 'BODY出力の検証に失敗。ローカル出力を保管してください。' }

python "$LocalTools\export_zed_depth.py" "$Svo" --output "$Depth" `
  --setup-id "$Setup" --depth-mode NEURAL --match-body-depth-settings `
  --pixel-stride 2 --frame-indices 3 4 5 6 7 8 9 12 15 18 19 21 24 27 30 45 60
if ($LASTEXITCODE -ne 0) { throw '深度書き出しに失敗。ローカル途中出力を保管してください。' }
python -c "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from export_depth_batch import validate_depth_export; print(validate_depth_export(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]))" "$LocalTools" "$Depth" "$Svo" "$Setup"
if ($LASTEXITCODE -ne 0) { throw '深度出力の検証に失敗。ローカル出力を保管してください。' }

python "$LocalTools\sync_exchange.py" --local-dir "$LocalRun" --shared-dir "$SharedRun"
if ($LASTEXITCODE -ne 0) { throw "共有への同期に失敗。ローカル出力は $LocalRun にあります。" }
Write-Host "完了: $SharedRun"
```

通常は0.1〜2秒の17フレームが対象。実際にはフレーム番号と時刻を出力ファイルで確認する。各指定フレームの2画素おきの有効な深度点と左画像を保存する。2画素間隔は保存時の間引きであり、SDKの深度推定の精度を上げるものではない。出力は数百MBになり得る。SDK書き出しプログラムの指定フレーム出力はUbuntuで構文・CLIを確認したが、Windows実機では今回が初実行。

処理が完了したらUbuntu側で `exchange/rec018_diagnosis_20261105_01/` のbodyとdepthを既存BODYに照合する。SVOハッシュ・全フレーム番号・時刻の一致、SDK設定とdepth設定、フレーム3〜9等の人物領域と背景の深度、3D骨盤・2D骨盤の再現を確認する。1パスの結果だけでSDK内部の原因を断定せず、BODYの既存データ・追加データ・画像を保持する。
