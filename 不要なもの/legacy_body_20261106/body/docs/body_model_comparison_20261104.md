# MEDIUM GEN_2: グループ2・3の代表録画を比較

グループ1の既存48録画の診断ではMEDIUM GEN_2で大きな位置ジャンプの割合が低かったが、位置数も少ない。正解との比較ではないため、グループ2・3でも同じSVO・設定で別パスを取得して評価する。現時点では、この新しいパッケージはSDK模擬試験済みであり、Windows実機では未検証。

WindowsのZED SDK環境のPowerShellで以下を実行する。元SVOと既存ACCURATE出力は変更しない。最初にツールをローカルに複製し、それぞれローカルに出力・検証後、共有先に同期する。3録画を順番に処理する。エラー時は途中出力を消さず、エラーを連絡する。

```powershell
$SharedPackage = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_model_compare_20261104_01'
$LocalRoot = Join-Path $env:USERPROFILE 'kaiseki1103_exchange'
$LocalPackage = Join-Path $LocalRoot 'model_compare_sdk_20261104_01'
$RunTag = 'medium_gen2_20261104_01'
$SharedRun = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\medium_gen2_20261104_01'
$Jobs = @(
    @{ Group='group002'; Recording='recording_001'; Svo='F:\experiment_data\20261104_group002\recording_001\recording_001.svo2'; Setup='group002_hallway_20261104_candidate' },
    @{ Group='group003'; Recording='recording_001'; Svo='F:\experiment_data\20261104_group003\recording_001\recording_001.svo2'; Setup='group003_hallway_20261104_candidate' },
    @{ Group='group003'; Recording='recording_002'; Svo='F:\experiment_data\20261104_group003\recording_002\recording_002.svo2'; Setup='group003_hallway_20261104_candidate' }
)
if (Test-Path $LocalPackage) { throw "ローカル作業先が存在します: $LocalPackage" }
if (Test-Path (Join-Path $LocalRoot $RunTag)) { throw 'ローカル出力先が存在します。上書きしません。' }
if (Test-Path $SharedRun) { throw '共有出力先が存在します。上書きしません。' }
foreach ($j in $Jobs) { if (-not (Test-Path $j.Svo)) { throw "SVOが見つかりません: $($j.Svo)" } }
New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null
Copy-Item -Recurse -LiteralPath $SharedPackage -Destination $LocalPackage
foreach ($j in $Jobs) {
    $Relative = Join-Path $j.Group (Join-Path $j.Recording 'body')
    $LocalOutput = Join-Path (Join-Path $LocalRoot $RunTag) $Relative
    $SharedOutput = Join-Path $SharedRun $Relative
    python "$LocalPackage\export_tracking.py" $j.Svo --output $LocalOutput `
        --setup-id $j.Setup --mode body --body-model MEDIUM
    if ($LASTEXITCODE -ne 0) { throw "書き出し失敗: $Relative。途中出力を残してください。" }
    python "$LocalPackage\validate_export.py" $LocalOutput
    if ($LASTEXITCODE -ne 0) { throw "検証失敗: $Relative。ローカル出力を残してください。" }
    python "$LocalPackage\sync_exchange.py" --local-dir $LocalOutput --shared-dir $SharedOutput
    if ($LASTEXITCODE -ne 0) { throw "共有同期失敗: $Relative。ローカル出力を残してください。" }
    Write-Host "完了: $SharedOutput"
}
```

完了したら3つの `完了:` 表示を知らせる。Ubuntu側でSVOハッシュ・カメラ設定・全フレームの時刻を照合し、対応するACCURATEと、同じ画像で骨格の混在・2D位置・ID連続性と欠測を比較する。SDK番号の一致は人物の正解ではない。未使用録画の検証前に全録画の設定を切り替えない。
