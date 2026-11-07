# グループ4：SDK骨格の確認

カメラを下げたため、グループ4を独立の設置 `group004_hallway_lower_20261105` として扱う。前のグループの廊下座標変換や床高は流用しない。はじめにSDKのカメラ座標と画像上の骨格を確認する。SDKの高い信頼度・ID・位置数は、骨格や人物対応の正解を保証しない。

Ubuntuで参照できる録画進捗には `recording_001`〜`recording_037` の完了記録があるが、これはSVOファイルの存在確認や基本試行の全数確認ではない。SVO本体はWindows PCの `F:\experiment_data\20261105_group004` にある。次の処理では、実際に見つかった `recording_*` フォルダー直下のSVO/SVO2だけを書き出す。

## Windows SDK PCでBODYを書き出す

SDK 5.5.1で以前成功したPython環境のPowerShellを使う。下のコマンドは対象SVOを列挙した後、BODY_34、ACCURATE GEN_2、NEURAL深度で全SVOフレームの骨格を保存し、画像は約0.1秒間隔で保存する。全録画の処理には時間と容量が必要。`calibration_*` は含めない。複数試行中にカメラを動かしていた場合、別設置として入力を分ける必要がある。

```powershell
$Package = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261105_depthclip_01'
$InputRoot = 'F:\experiment_data\20261105_group004'
$SharedRun = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\group004_20261105_body_01'

if (-not (Test-Path -LiteralPath $InputRoot -PathType Container)) { throw "録画フォルダがありません: $InputRoot" }
if (Test-Path -LiteralPath $SharedRun) { throw '共有先が存在します。別の名前を指定してください。' }
$Svos = @(Get-ChildItem -LiteralPath $InputRoot -Recurse -File | Where-Object {
  $_.Extension -in '.svo', '.svo2' -and $_.Directory.Name -like 'recording_*'
})
if ($Svos.Count -eq 0) { throw 'recording_* 直下にSVOがありません。保存構造を確認してください。' }
Write-Host "対象SVO数: $($Svos.Count)"
$Svos | Select-Object -ExpandProperty FullName

python "$Package\export_svo_directory.py" `
  --input-root "$InputRoot" `
  --exchange-root "$SharedRun" `
  --setup-id group004_hallway_lower_20261105 `
  --include-parent-pattern 'recording_*'
if ($LASTEXITCODE -ne 0) { throw '一部の書き出し、検証または共有に失敗しました。ローカル出力とログを残してください。' }
```

出力はまず `%USERPROFILE%\kaiseki1103_exchange\group004_20261105_body_01\` に保存し、最後に共有へ複製する。各録画に `body.log` と `body.validation.log` を残し、`batch_summary.csv` に個別の成功・失敗を記録する。失敗した録画がある場合も共有コピーが行われることがあるため、コピー完了だけで全録画成功とは判断せず、終了コードと一覧を確認する。ローカル出力・共有先が既にある場合は上書きできない。再実行には新しい共有先名を指定する。

出力の `recording_001` 等は、見つかったSVOを並べた**出力用の連番**。元録画の番号と一致するとは限らない。`input_inventory.csv` の `source_relative_path` と撮影記録を照合してから実験条件を対応付ける。SVOは変更・削除しない。既存のディレクトリ一括書き出しを使い、新しいSDK実行はこのWindows PCで実施する。

## Ubuntu側で確認

共有結果の受領後に実行する。`--setup-id` はWindowsで指定した値と一致させる。

```bash
python3 -m body.sdk_body_review \
  --input-root /data/experiment_data/kaiseki1103/exchange/group004_20261105_body_01 \
  --setup-id group004_hallway_lower_20261105 \
  --output results/tracking_v2/group004_sdk_review_20261105_01
```

正常に検証された各BODY出力について、同じ画像時刻の元画像とSDKの主要な骨格線を左右に並べる。全画像と、SDKの関節位置に基づく拡大画像を表示する。SDKの関節が間違っていると拡大画像に人物が入らないこともあるため、全画像も併せて確認する。全フレームの骨盤の大きな飛び、カメラ奥行きZが0以下の位置、画像外の骨盤、SDK位置数と保存画像数を診断する。指標は正解に基づく誤り率ではない。SDK IDの変更や人物の見失いでも数値が変わるため、検出できていない人物を含め画像で確認する。保存画像は約0.1秒ごとで、候補に最も近い画像が候補フレームそのものとは限らない。

撮影された各人物の可視性と対応関節を人手で注釈し、特に遠方、前後の重なり、追い越し、画面端について、欠測・他人との混在・不自然な関節・飛びを別々に数える。画像上の一致は3D位置の精度を証明しない。新しいカメラ位置で絶対位置精度を評価するには、同設置の校正と独立した基準が必要。

## 2026-11-05：受領した37録画の確認

SDK出力37件は全件フルSVOで検証済み。入力一覧でも出力番号と元のSVO番号は001〜037で一致した。Ubuntu側でも出力・画像のハッシュを検証し、全14,933フレームのSDK結果を再集計した。[録画ごとの確認ページ](../../results/tracking_v2/group004_sdk_review_20261105_01/index.html)

[37録画のSDK骨格再生](../../results/tracking_v2/group004_sdk_replay_20261105_01/index.html)では、各録画について保存された画像と同時刻のSDK骨格を再生できる。画像は約0.1秒間隔で、間のフレームの画像は表示しない。深度から推定した人物位置の再生ではない。

全37件ともSDK 5.5.1、ZED 2i同一シリアル、1920×1080・30fpsの記録、NEURAL、BODY_34、ACCURATE GEN_2、フィッティング有効、信頼度35、予測0.2秒、平滑化0の設定だった。これは記録された設定の一致であり、撮影条件や実際の人物配置が同一という意味ではない。

| 全フレームの診断 | グループ4 | グループ3参考 |
|---|---:|---:|
| 録画数 | 37 | 54 |
| SDKの骨盤位置観測数 | 24,332 | 31,284 |
| 比較可能な隣接位置の組 | 23,235 | 29,308 |
| 大きな飛びの候補 | 1,867（8.04%） | 2,923（9.97%） |
| 飛び候補を含む録画 | 36/37 | 51/54 |

両群とも `tracking_state=OK`、骨盤3D有限、骨盤信頼度20以上を採用し、同一SDK IDの隣接フレームで0.05秒以下、3D移動0.75m超かつ6m/s超の組を数えた。カメラ座標の診断値であって真の誤り率ではない。欠測・人物の見失い・ID変更によって分母や件数が変わる。グループ3と4は異なる録画・人物・撮影条件で、同じ条件の対応区間による独立比較ではない。上表だけでカメラ高さによる改善を結論できない。[グループ3の再集計](../../results/tracking_v2/group003_sdk_fullrate_reference_20261105_01.json)

グループ4では、上記24,332のSDK骨盤位置観測のうち、カメラ前方を正とするZが0以下の点が140件、12録画にあった。`OK` と高い関節信頼度を満たしても、カメラ前方の人物位置として解釈できない例が含まれる。位置・IDは実測正解ではない。

### 画像で確認した例

- **録画006**：同じ画像時刻の[0.100・0.201・0.301秒の比較画像](../../results/tracking_v2/group004_sdk_review_20261105_01/recording_006/images/diagnostic_triptych_003_006_009.jpg)では、遠方の人物が見える一方、0.201秒のSDK骨格が手前の支柱・床付近に移っている。元SDK ID 0の骨盤はフレーム5→6→7で、カメラ座標Zが11.13→2.59→8.84m、画像yが236→713→248px。隣接する3D移動は約9.87mと7.31m。3フレームともSDK状態はOK、骨盤信頼度は99.9以上だった。この例は座標変換より前のSDK出力に存在し、原因は未特定。
- **録画001**：[2.910秒の画像](../../results/tracking_v2/group004_sdk_review_20261105_01/recording_001/images/frame_000085.jpg)には遠方に人物が見えるが、その同じフレームでSDKのBODY検出数は0だった。これは該当画像での欠測例であり、録画全体の取得率ではない。

この結果から、新しい設置でもSDK骨格の大きな飛びと欠測は残っている。単独に見える人物の例でも発生しているため、2人の重なりだけで説明できない。ただし原因が検出・追跡・フィッティング・深度のどこにあるか、またカメラ高さの効果は未確定。可視人物の注釈と測量上の基準なしに、骨格や歩行位置の正答率・絶対誤差は数値化しない。
