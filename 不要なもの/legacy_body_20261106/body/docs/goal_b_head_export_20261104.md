# Goal B: グループ3 録画001の頭部検出出力

すでに取得済みのBODY_34と同じSVOについて、頭部検出を別パスで取得します。まず録画001の全区間で確認します。SDKを実行できるWindows PCで、Fドライブと共有フォルダーが接続された状態でPowerShellに貼り付けてください。PythonはこれまでSDK書き出しに使った環境を使用します。元のSVOや既存のBODY出力は変更しません。

```powershell
$SharedPackage = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10'
$LocalRoot = Join-Path $env:USERPROFILE 'kaiseki1103_exchange'
$LocalPackage = Join-Path $LocalRoot 'goal_b_sdk_tools_20261104_01'
$LocalOutput = Join-Path $LocalRoot 'group003_heads_20261104_01\recording_001\heads'
$SharedOutput = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\group003_heads_20261104_01\recording_001\heads'
$Svo = 'F:\experiment_data\20261104_group003\recording_001\recording_001.svo2'

if (-not (Test-Path $Svo)) { throw "SVOが見つかりません: $Svo" }
if (Test-Path $LocalPackage) { throw "ローカルのSDK作業先が存在します: $LocalPackage" }
if (Test-Path $LocalOutput) { throw "ローカル出力が存在します: $LocalOutput" }
if (Test-Path $SharedOutput) { throw "共有出力が存在します: $SharedOutput" }
New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null
Copy-Item -Recurse -LiteralPath $SharedPackage -Destination $LocalPackage

python "$LocalPackage\export_tracking.py" $Svo --output $LocalOutput `
  --setup-id group003_hallway_20261104_candidate --mode heads
if ($LASTEXITCODE -ne 0) { throw '頭部出力が失敗しました。途中出力を残し、エラーを連絡してください。' }
python "$LocalPackage\validate_export.py" $LocalOutput
if ($LASTEXITCODE -ne 0) { throw '頭部出力の検証が失敗しました。ローカル出力を残してください。' }
python "$LocalPackage\sync_exchange.py" --local-dir $LocalOutput --shared-dir $SharedOutput
if ($LASTEXITCODE -ne 0) { throw '共有へのコピーに失敗しました。ローカル出力は保存されています。' }
Write-Host "完了: $SharedOutput"
```

処理にはモデルの初回最適化とSVO全体の読み込みが含まれ、時間がかかります。頭部モデルに対応しないSDKでは失敗するため、そのエラーを記録してください。共有コピーが失敗した場合、ローカル出力が残るので、接続を復旧して最後の `sync_exchange.py` コマンドだけ再実行できます。出力先がすでに存在する場合は上書きしません。

返却後は元SVOのSHA-256、カメラ設定、設置ID、全フレーム時刻を既存BODY出力と照合し、同一録画と確認できた場合だけ統合します。頭部検出の出力点を自動的に人物の正解や3D位置の実測とみなしません。

## 追加候補: グループ2 録画001

グループ2の録画001では、約1.2〜3.8秒の確認画像で後方の赤いベストの人物の頭が見える一方、同じ時点のBODY出力には1人分しかありません。頭部検出の効果を調べる上で特に重要な例です。上の録画001が終わった後、余裕があれば同じPowerShellセッションでこちらも実行してください。

```powershell
$LocalOutput = Join-Path $LocalRoot 'group002_heads_20261104_01\recording_001\heads'
$SharedOutput = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\group002_heads_20261104_01\recording_001\heads'
$Svo = 'F:\experiment_data\20261104_group002\recording_001\recording_001.svo2'
if (-not (Test-Path $Svo)) { throw "SVOが見つかりません: $Svo" }
if (Test-Path $LocalOutput) { throw "ローカル出力が存在します: $LocalOutput" }
if (Test-Path $SharedOutput) { throw "共有出力が存在します: $SharedOutput" }
python "$LocalPackage\export_tracking.py" $Svo --output $LocalOutput `
  --setup-id group002_hallway_20261104_candidate --mode heads
if ($LASTEXITCODE -ne 0) { throw '頭部出力が失敗しました。途中出力を残してください。' }
python "$LocalPackage\validate_export.py" $LocalOutput
if ($LASTEXITCODE -ne 0) { throw '頭部出力の検証が失敗しました。ローカル出力を残してください。' }
python "$LocalPackage\sync_exchange.py" --local-dir $LocalOutput --shared-dir $SharedOutput
if ($LASTEXITCODE -ne 0) { throw '共有へのコピーに失敗しました。ローカル出力は保存されています。' }
Write-Host "完了: $SharedOutput"
```
