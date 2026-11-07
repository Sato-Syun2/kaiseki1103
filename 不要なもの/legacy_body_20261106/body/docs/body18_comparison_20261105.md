# グループ3録画018：BODY_18の比較

録画018の同一SVOを、BODY_18・ACCURATE GEN_2で、骨格フィッティング無効／有効の2パスでSDK処理する。元のBODY_34は既存の出力を使う。どちらのBODY_18条件も個別のフルSVO出力・SDKログ・検証結果を保存する。入力SVOと既存出力は変更しない。

BODY_18では0番は鼻、右股関節は8番であり、BODY_34の0番（骨盤）と互換ではない。比較プログラムは右股関節をBODY_18は8番、BODY_34は22番として別々に読み、骨盤位置を捏造しない。SDK IDは条件ごとに独立しており、同じ番号でも同一人物とは限らない。BODY_18とBODY_34の同名関節は厳密に同一の解剖学的位置とは限らない。公式定義: https://docs.stereolabs.com/docs/development/zed-sdk/modules/body-tracking

## 1. Windows SDK PCで出力

SDK 5.5.1と前回成功したPython環境のPowerShellで実行する。`F:`のSVOパスが異なる場合は `$Svo` を変更。ローカル出力と共有先が存在すると停止するため、やり直す場合はタグと共有先の名前を両方変更する。

```powershell
$Package = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261105_body18_01'
$Svo = 'F:\experiment_data\20261104_group003\recording_018\recording_018.svo2'
$SharedRun = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\body18_group003_018_20261105_01'

python "$Package\export_body18_comparison.py" `
  --svo "$Svo" `
  --setup-id group003_hallway_20261104_candidate `
  --tag body18_group003_018_20261105_01 `
  --shared-dir "$SharedRun"
```

成功すると次のように表示される。

```text
Processing fitting_off ...
  export=0, validation=0
Processing fitting_on ...
  export=0, validation=0
Shared output: ...body18_group003_018_20261105_01
```

各出力は `fitting_off/body/` と `fitting_on/body/`、各ログは同じ親の `export.log`・`validation.log`。書き出し時に18関節であるか、全フレーム番号・時刻・出力ハッシュを検査する。SDKログに警告がないかも分析時に読む。camera.jsonのフィッティング値は**SDKに渡した要求値**であり、SDK内部で設定が適用されたことを保証しない。

いずれかが失敗した場合はローカル結果とログを保持し、共有には自動同期しない。`%USERPROFILE%\kaiseki1103_exchange\body18_group003_018_20261105_01\` の `batch_summary.csv` と各ログを確認する。共有への同期だけ失敗した場合は、新しい共有先を指定してローカルから同期できる。

```powershell
python "$Package\sync_exchange.py" `
  --local-dir "$env:USERPROFILE\kaiseki1103_exchange\body18_group003_018_20261105_01" `
  --shared-dir "$SharedRun"
```

BODY_18の新コードはコマンド形式と構文を確認したが、このWindows SDK実機では未実行。特にフィッティング有効の場合にSDKが返す実際の関節数や警告は、今回の出力・ログで確認する。18関節以外の場合はエラーとして保留する。

## 2. Ubuntuで比較

共有同期後、プロジェクトから以下を実行する。解析先は新規ディレクトリとする。BODY_34とBODY_18の同一SVOハッシュ・SDK設定・フレーム番号・画像時刻を照合する。前回の深度書き出しから同じ17フレームの画像を使用する。

```bash
BASE=/data/experiment_data/kaiseki1103/exchange/group003_20261104_candidate_01/recording_018/body
RUN=/data/experiment_data/kaiseki1103/exchange/body18_group003_018_20261105_01
DEPTH=/data/experiment_data/kaiseki1103/exchange/rec018_diagnosis_20261105_01/depth
CAL=results/tracking_v2/group003_20261104_analysis_01/scoped_calibrations/recording_018.json
python3 -m body.compare_body18_34 \
  --body34 "$BASE" \
  --body18-off "$RUN/fitting_off/body" \
  --body18-on "$RUN/fitting_on/body" \
  --image-export "$DEPTH" \
  --calibration "$CAL" \
  --crop 1170 80 1370 820 \
  --output results/tracking_v2/group003_018_body18_comparison_20261105_01
```

`index.html` には3条件を同じ画像に重ねた図、暫定の廊下座標に変換した3D骨格と、全フレームを対象にした右股関節の位置数、大きな飛び、画像外・カメラ後方の位置を載せる。画像は問題の冒頭を含む指定17時刻のみで全録画を代表しない。CSVには各形式の全関節と右股関節のカメラ座標・暫定校正による廊下座標を保存する。全関節CSVは未確定な点や異常値も含む。座標はSDK推定値であり独立実測ではない。SDKの関節信頼度20以上・追跡状態OK等は単純な集計条件で、人物の正解や直接観測を保証しない。飛びが少ない場合でも、人物の見失い・ID変更・関節欠測が増えていないか、同じ画像で確認する。
