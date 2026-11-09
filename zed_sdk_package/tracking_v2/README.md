歩行者追跡 SDK export v2（2026-11-04）

## グループ７〜９のSSD内BODY書き出し（2026-11-09）

`run_body_group007_009_local.ps1` は対応する新しい配布物からSDKコードをハッシュ照合してSSDに複製し、`export_body_local_batch.py` でSVO全フレームのBODY_34を出力・検証する。既存の深度結果は変更せず、画像・骨格・ログは `G:\kaiseki1005\sdk_body_group007_009_20261109_01` に保存し共有しない。`recording_NNN` の物理名を維持し、７の `test_001`・`test_002` は従来の仮名901・902で保存する。元録画や校正はコピーしない。既存深度結果のSVOハッシュがある録画は書き出し後に照合し、不一致は保留する。

対象ごとの進捗と完了済み録画の平均時間からの概算残り時間を表示。中断後は同じコマンドで再開し、完了済みは再検証して再利用、未完了の試行は別名で再実行する。重複SVOは自動選択せず、空フォルダーは表示して飛ばす。ソースフォルダー内に別のSVOを追加する場合、実際の試行番号との対応を自動確定しない。Windows SDK実機での新ランナー検証は未実施。

## SDK設定別の骨格安定性比較

`export_stability_comparison.py` は同一SVOをMEDIUM GEN_2、予測時間0秒、検出信頼度50の3条件で書き出す。それぞれ既存ACCURATE GEN_2の条件から一つだけ変更する。BODY_34の追跡ではSDKが骨格フィッティングを自動的に有効化するため、`--no-body-fitting` は実行前に拒否する。以前の `stability_20261104_01` では無効を要求したがSDKログに自動有効化の警告があり、camera.jsonのfalseは要求値であって実際の無効化を示さない。条件ごとに別出力、全フレーム、独立したログとSDK出力検証を行う。入力・出力の指定例とUbuntuでの比較手順は `docs/sdk_stability_comparison_20261104.md` を参照。

`export_zed_depth.py --frame-indices ... --match-body-depth-settings` は指定した0始まりのSVOフレームを保存し、BODY書き出しと同じ深度範囲とSDKランタイム既定値を設定する。深度とBODYは別パスなので結果の完全一致を保証しない。全SVOを読み、正常EOFと予定フレーム数、指定フレーム、ハッシュを記録する。`camera.json` の `processing_timing_seconds` はSVOハッシュ、SDK初期化、全フレーム取得・画像保存、点群圧縮の経過秒を記録する。区間ランナーの `batch_summary.json` の `timing_seconds` は外側のハッシュ、子プロセス全体、出力検証の経過秒を記録し、子プロセス時間には内側の処理が含まれる。変更後のWindows実機確認は未実施。

`export_zed_depth.py` と `export_depth_clip.py` の `--point-archive-mode` は `compressed`（既定）または `stored`。どちらも同じNPZ配列形式と値を保存し、`stored` はZIP圧縮を省いてSSD容量を多く使う。`camera.json` と区間サマリーに方式を記録する。実際の短縮効果と空き容量は実機で検証する。

`export_depth_clip.py` は、この既存書き出しを使い、開始フレームと件数で指定した連続区間をローカルへ保存・検証してから共有へミラーする。子ツールを先にローカルへコピーし、入力ハッシュ・設定・ログを残す。深度の信頼度画像は出力しない。出力はSVO全体の深度ではなく、指定区間だけの深度である。フレーム数を増やすと既存書き出し処理のメモリ消費が大きくなるため、短区間から始める。新しいラッパーはUbuntu上の模擬試験のみで、Windows SDK実機では未検証。

`export_body18_comparison.py` は指定SVOをBODY_18のフィッティング無効・有効の別パスで書き出す。`export_tracking.py --mode body18` はBODY_18専用のschema_version 2を保存し、既定のBODY_34とは `detection_kind` と `body_format` で区別する。`validate_export.py` は18関節と時刻・ハッシュを検証する。従来の廊下追跡リーダーはBODY_34専用で、BODY_18を拒否する。BODY_18の0番は鼻であり、骨盤ではない。フィッティング値はSDKへ渡した要求値であり、実際のSDKログを併せて確認する。新機能のWindows SDK実機確認は未実施。

このコードの追加・変更時は同じフォルダーの `AGENTS.md` にあるSDK実装ルールと出力契約を守る。

正本はプロジェクトの `zed_sdk_package/tracking_v2/`。旧共有版 `export_zed_replay.py` は上書きしない。`prepare_tracking_sdk.py` で新しい配布フォルダーを作り、`package_manifest.json` のハッシュを確認してWindowsへ渡す。

## 保存場所とパス

録画原本、SDK用プログラム、交換データ、Ubuntu解析結果は次の場所に分けて保存する。録画原本は読み取り専用で扱い、SDK出力や解析コードを録画フォルダーへ置かない。

| 用途 | Ubuntu上のパス | Windows SDK PCでの場所 |
|---|---|---|
| SDKプログラムの正本 | `/home/hp-ubuntu/kaiseki1103/zed_sdk_package/tracking_v2/` | — |
| 今回のSDK配布物 | `/data/experiment_data/kaiseki1103/zed_sdk_package/tracking_v2_20261104_test005_10/` | `\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10\` |
| test_002 SVO（優先順） | `/data/experiment_data/recordings/20261104_test/test_002/` | `F:\experiment_data\20261104_test\test_002\test_002.svo2` を優先し、なければ `\\tsclient\_data_experiment_data\recordings\20261104_test\test_002\test_002.svo2` |
| test_005 SVO（優先入力） | `/data/experiment_data/recordings/20261104_test/test_005/` | `F:\experiment_data\20261104_test\test_005\test_005.svo2` |
| SDK出力の一次保存先 | — | `%USERPROFILE%\kaiseki1103_exchange\<tag>\`（`--local-root` で変更可） |
| 共有交換先（接続時のミラー） | `/data/experiment_data/kaiseki1103/exchange/<tag>/` | `\\tsclient\_data_experiment_data\kaiseki1103\exchange\<tag>\` |
| Ubuntu解析コードと校正・レポート | `/home/hp-ubuntu/kaiseki1103/` とその `results/20261104_test/` | — |

`experiment_recorder` は録画専用です。解析プログラムや校正・結果をそこへ保存しません。配布先・交換先が既に存在するときは、既存データを消さずに新しい名前を指定します。

## 2026-11-04 test_002 / test_005 のSDK書き出し

`export_test_20261104.py` と `export_svo_directory.py` はZED SDK搭載Windows PCで実行します。入力SVOは外付けSSD等のローカルディスクから読み、出力・ログ・summaryはまず `%USERPROFILE%\kaiseki1103_exchange\<tag>\` に保存します。起動時にSDK子プログラムもローカルへステージするので、処理中に共有接続が切れてもSDK書き出しを続けられます。全処理の終了後に共有 `exchange` へコピーを試し、接続がなければローカルデータを保持します。既に動作確認済みのZED SDK対応Python環境を使います。SDK実行はUbuntu上では行いません。

```powershell
Set-Location "\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10"
python .\export_test_20261104.py
```

上記のPythonランナーはPowerShellの実行ポリシーに依存しない。ZED SDKの `pyzed`、NumPy、OpenCVを読み込めるPythonを使う。既定ではtest_005を `F:\experiment_data\20261104_test\test_005\test_005.svo2` から読み、test_002は同じSSD上のコピーを優先して、なければ共有録画フォルダーから読みます。個別の入力は `--test-002-svo` と `--test-005-svo`、ローカル保存先は `--local-root`、共有ミラー先は `--exchange-root` で指定できます。実際の物理設置状態が確認できるまでは test_002 と test_005 に別々の候補 `setup_id` を付ける。2録画でカメラを動かしていないと現場記録で確認できた場合だけ、両方へ同じ設置IDを指定する。

共有切断中も処理を続ける場合は上記のPythonランナーを使ってください。旧PowerShellラッパーは指定先へ直接書く方式で、ローカル一次保存と再ミラーに対応していません。

`--operations` を指定すると必要な書き出しだけ再実行できます。例えば、test_002深度は既にあり、test_005深度とtest_002 BODY_34だけが必要な場合は次のように実行します。外付けSSDが接続され、test_005のローカルSVOが存在する状態で実行してください。

```powershell
python .\export_test_20261104.py `
  --exchange-root "\\tsclient\_data_experiment_data\kaiseki1103\exchange\test_20261104_candidate_03" `
  --operations test_005_depth test_002_body
```

出力はローカル保存先に次の構成で作られます。SVO/SVO2は出力先へ複製しません。ミラーに成功すると、同じ構成が共有交換先にも作られます。

```text
%USERPROFILE%/kaiseki1103_exchange/test_20261104_candidate/
  input_inventory.csv
  batch_summary.csv
  test_002/
    body/                 # BODY_34全フレーム追跡、camera.json、manifest.json、画像など
    depth_export/         # 0.5秒間隔の深度点、同期画像、校正用カメラ情報
    body.log, body.validation.log, depth_export.log
  test_005/
    depth_export/         # ポール設置・移動記録の深度と同期画像
    depth_export.log
```

一つの書き出しが失敗しても他の書き出しは続き、最終的な成否は `batch_summary.csv` と録画別ログに記録されます。summary CSVは処理終了時に一度だけ書き、共有フォルダー上での途中上書きを避けます。失敗後はその出力フォルダーを再利用せず、`--exchange-root` に新しいタグ名を指定して再実行します。設置IDや出力先を変更したら、後段の解析にも同じ値を引き継ぎます。

## group002 フォルダー全体のBODY_34書き出し

外付けSSD内のすべての `.svo` / `.svo2` を再帰検索し、ファイル名順にBODY_34を書き出して検証するPythonコマンドです。PowerShellスクリプトの実行ポリシーには依存しません。`source_relative_path` を `input_inventory.csv` に記録するため、連番と元ファイルの対応を確認できます。途中の番号から再開するときは `--start-index` を使います。入力全体を同じ規則で並べたうえで指定番号以降を処理し、元の `recording_NNN` 番号を保ちます。

```powershell
Set-Location "\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10"
python .\export_svo_directory.py `
  --input-root "F:\experiment_data\20261104_group002" `
  --exchange-root "\\tsclient\_data_experiment_data\kaiseki1103\exchange\group002_20261104_candidate_01" `
  --setup-id group002_hallway_20261104_candidate
```

前回の書き出しが共有切断で停止し、`recording_001`〜`recording_016` が既に出力済みの場合は、同じ入力・設置IDで次のように `recording_017` から続けます。共有先は既存バッチを上書きしない新しい名前にし、Windows内ローカル保存先にも同名の新しいバッチが作られます。

```powershell
Set-Location "\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10"
python .\export_svo_directory.py `
  --input-root "F:\experiment_data\20261104_group002" `
  --start-index 17 `
  --local-root "$env:USERPROFILE\kaiseki1103_exchange" `
  --exchange-root "\\tsclient\_data_experiment_data\kaiseki1103\exchange\group002_20261104_candidate_02" `
  --setup-id group002_hallway_20261104_candidate
```

この続行バッチには `recording_017`〜`recording_055` だけが入ります。前回分は `group002_20261104_candidate_01`、続行分は `group002_20261104_candidate_02` に分かれて残ります。`--start-index` を誤ると同じ番号を再処理するため、開始番号は直前に正常検証された番号の次にしてください。

## group003 実験録画のBODY_34書き出し

グループ3には実験録画54件と `calibration_*` フォルダーが含まれます。校正録画を除外して実験録画だけ書き出すには、親フォルダーを `recording_*` に絞ります。

```powershell
Set-Location "\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10"
python .\export_svo_directory.py `
  --input-root "F:\experiment_data\20261104_group003" `
  --include-parent-pattern "recording_*" `
  --local-root "$env:USERPROFILE\kaiseki1103_exchange" `
  --exchange-root "\\tsclient\_data_experiment_data\kaiseki1103\exchange\group003_20261104_candidate_01" `
  --setup-id group003_hallway_20261104_candidate
```

`--include-parent-pattern` を付けると `calibration_001` と `calibration_002` は対象外になり、実験録画は `recording_001`〜`recording_054` として出力されます。

## group002 / group003 空間校正録画のZED深度書き出し

LiDAR校正候補と照合するため、各校正SVOから疎なZED深度点とレビュー画像を書き出します。次の一括ランナーは出力・ログをWindows内に保存し、終了後に共有へミラーします。

```powershell
Set-Location "\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_test005_10"
python .\export_depth_batch.py `
  --local-root "$env:USERPROFILE\kaiseki1103_exchange" `
  --exchange-root "\\tsclient\_data_experiment_data\kaiseki1103\exchange\group002_group003_calibration_20261104_candidate_01" `
  --job group002_calibration_001 "F:\experiment_data\20261104_group002\calibration_001\calibration_001.svo2" group002_hallway_20261104_candidate `
  --job group003_calibration_001 "F:\experiment_data\20261104_group003\calibration_001\calibration_001.svo2" group003_hallway_20261104_candidate `
  --job group003_calibration_002 "F:\experiment_data\20261104_group003\calibration_002\calibration_002.svo2" group003_hallway_20261104_candidate
```

Windowsの一次出力は `%USERPROFILE%\kaiseki1103_exchange\group002_group003_calibration_20261104_candidate_01` にできます。グループ2と3のsetup IDは分け、グループ3の2つの校正録画は同一設置の反復として同じIDを付けています。校正録画間にカメラを動かした場合は、別IDに分けてください。共有接続が切れてミラーできなかった場合は、このローカルバッチを保管し、再接続後に `sync_exchange.py` で新しい共有先へミラーします。

同じ `setup_id` は全録画でカメラ位置・設置が同じ場合に限って使います。途中でカメラを移動した録画が含まれる場合は、設置ごとに入力フォルダーを分け、各バッチで別の `setup_id` を指定します。実行後はローカル保存先の `batch_summary.csv` で `validated_full_svo` を確認してください。共有接続が有効なら、完了後に同じバッチが指定した `exchange-root` へミラーされます。廊下座標への変換と閲覧用再生ページはUbuntu側で校正後に作成します。

共有接続が切れていてミラーできなかった場合は、ローカルデータが残っています。共有接続を戻してからSDKパッケージの `sync_exchange.py` でコピーを再試行します。

```powershell
$SyncTool = "$env:USERPROFILE\kaiseki1103_exchange\.sdk_tools\tracking_v2_20261104_test005_08\sync_exchange.py"
python $SyncTool `
  --local-dir "$env:USERPROFILE\kaiseki1103_exchange\group002_20261104_candidate_01" `
  --shared-dir "\\tsclient\_data_experiment_data\kaiseki1103\exchange\group002_20261104_candidate_01"
```

ミラー先に同名フォルダーが既にある場合は上書きせず停止します。必要な場合は新しい共有先名を指定してください。

Ubuntuで交換データを確認した後、校正・歩行解析・再生HTMLを `/home/hp-ubuntu/kaiseki1103/results/20261104_test/` 以下へ保存する。解析コードは `/home/hp-ubuntu/kaiseki1103/` に置き、`exchange` にはSDK書き出しデータだけを置く。

test_002 の書き出しが戻った後のUbuntu処理例。BODY追跡は過去の手法であり、旧コードを参照する場合のみ `PYTHONPATH` に保管先を追加する。LiDAR候補のパスも明示する。

```bash
python3 zed_sdk_package/tracking_v2/validate_export.py \
  /data/experiment_data/kaiseki1103/exchange/test_20261104_candidate/test_002/body
python3 analyze_zed_corridor.py \
  /data/experiment_data/kaiseki1103/exchange/test_20261104_candidate/test_002/depth_export \
  --lidar-candidate results/20261104_test/test_002/lidar_corridor_candidate/lidar_corridor_candidate.json \
  --output-dir results/20261104_test/test_002/zed_depth_calibration_candidate
PYTHONPATH='不要なもの/legacy_body_20261106:.' python3 -m body.process_tracking_v2 \
  --source /data/experiment_data/kaiseki1103/exchange/test_20261104_candidate/test_002/body \
  --recording test_002 \
  --calibration results/20261104_test/test_002/zed_depth_calibration_candidate/zed_corridor_candidate.json \
  --config 不要なもの/legacy_body_20261106/body/configs/tracking_candidate_final_20261104.json \
  --output results/20261104_test/test_002/tracking_v2_candidate
```

校正JSONには `setup_id` とカメラ個体・解像度・深度モード・内部パラメータを `applies_to` として記録し、追跡時に一致を確認する。この深度平面校正はカメラ相対の廊下座標候補。test_005のポール位置と対応が取れた観測が得られた場合は独立した距離検証に使い、結果を見てから採用する。

本版はUbuntuでのシリアライズ・失敗処理・出力検証試験済み。ZED実機の成功は未確認。現在のUbuntuは `libnvidia-encode.so.1` 不足とGPUドライバー接続失敗によりSDKを起動できない。Windows側の短い試験を先に実行する。SDK 5.5以降、対応GPU、SDKに対応するPython/pyzed、numpy、opencv-pythonを使う。既に旧版を動かせたPython環境を優先し、SDKの指定と異なるnumpy版へ無条件に更新しない。

PowerShellの例。パスは実際のドライブへ置き換える。実行中の録画設定は変更しない。

```powershell
Set-Location "D:\kaiseki1103\tracking_v2_20261104"
$Python = "python"
& $Python -c "import pyzed.sl as sl; import cv2; import numpy; print(sl.Camera.get_sdk_version())"
& $Python .\export_tracking.py "D:\recordings\recording_001.svo2" `
  --output "D:\exchange\smoke_20261104\body" --max-frames 90 `
  --setup-id hallway_original_20261102 --mode body
& $Python .\validate_export.py "D:\exchange\smoke_20261104\body" --allow-limited
& $Python .\export_tracking.py "D:\recordings\recording_001.svo2" `
  --output "D:\exchange\smoke_20261104\heads" --max-frames 90 `
  --setup-id hallway_original_20261102 --mode heads
& $Python .\validate_export.py "D:\exchange\smoke_20261104\heads" --allow-limited
```

90フレーム試験は `requested_frame_limit` と記録され、通常の検証・解析は全SVOとして受け付けない。頭部モデルの初回最適化には時間がかかり得る。`PERSON_HEAD_BOX_ACCURATE` が存在しないSDKでは失敗として終了し、他モデルへ黙って変更しない。

続いて `inventory_template.csv` をコピーして、48行の `recording_001`〜`recording_048`、実在するSVOの絶対パス、設置IDを記入する。設置IDは実際のカメラ固定状態を表し、再設置後は新しくする。例の `hallway_original_20261102` は現場で設置状態を確認して付与するIDであり、スクリプトが同一設置を証明するものではない。

```powershell
.\export_batch.ps1 -InventoryCsv .\inventory_actual.csv `
  -OutputRoot "D:\exchange\tracking_v2" -Tag "full_20261104_01" `
  -Python $Python -First 1 -Last 48 -Heads
```

`-Heads` を省略すると骨格だけ。既存のタグ・出力ディレクトリは拒否する。失敗後はログを確認し、新しいタグで該当録画だけ `-First N -Last N` として再試験する。途中出力の再開や既存画像の使い回しは行わない。PowerShellの実行ポリシーでスクリプトを使えない環境は、同じ引数でPythonコマンドを個別に実行する。

返却するフォルダー:

- `input_inventory.csv`、`batch_summary.csv`、各録画の実行・検証ログ。
- 各 `body/`: `camera.json`, `manifest.json`, `frames.csv`, `bodies.csv`, `assets.csv`, `images/`。
- 各 `heads/`: 同形式で `bodies.csv` の代わりに `heads.csv`。SDK IDは骨格のIDと別物。
- `--segmentation` を選択した場合は `masks/` も返す。マスクは検出ボックス内の座標で、ボックスを伴って使う。既定は無効で、欠損理由を各行に残す。
- 配布時の `package_manifest.json`。

検証器は正常EOF、予定／取得／保存フレーム数、フレーム順序、画像と検出時刻、検出数、ファイルと画像のハッシュ、画像解像度を検査する。`is_new=false` は記録するが、解析では現在の観測として数えない。SDKの `is_new` は結果コンテナの新規性であり、各関節が直接観測されたことを保証しない。`prediction_timeout_s=0.2` とbody fitting有効を比較基準として明示した。予測タイムアウト0やminimum-keypointsの変更は別出力にして効果を比較する。

画像はSDKのBGRAからJPEG用BGRへ変換する。旧版のRGBA変換は赤青を交換していたため、旧JPEGと新JPEGの色特徴を同一分布とみなさない。旧画像は変更しない。

各SVOのハッシュを最初に計算するため、進捗フレームが出るまで時間がかかる。CSVは逐次保存する。画像間隔は実時刻の独立したクロックで決め、骨格・頭部処理と保存は全grabフレームに対して行う。頭部と骨格は別パスで同じSVOを処理し、SVOハッシュ・設置・内部パラメータ・時刻の一致を確認して統合する。

Ubuntuへ返却後:

```bash
python3 zed_sdk_package/tracking_v2/validate_export.py /path/to/recording_001/body
python3 zed_sdk_package/tracking_v2/validate_export.py /path/to/recording_001/heads
PYTHONPATH='不要なもの/legacy_body_20261106:.' python3 -m body.process_tracking_v2 --source /path/to/recording_001/body \
  --heads /path/to/recording_001/heads --recording recording_001 \
  --config 不要なもの/legacy_body_20261106/body/configs/tracking_candidate_final_20261104.json \
  --output results/tracking_v2/sdk_trial_NEW
```

今回の `exchange/test_20261104_candidate/test_002/body` を使うときは、上記の `/path/to/recording_001/body` を実際の交換パスへ置き換える。test_005 のポール観測との対応付け、カメラ深度とLiDARの座標合わせを確認してから候補校正を確定し、歩行軌跡と再生HTMLを `results/20261104_test/` に出力する。

この段階では追跡候補・暫定校正の比較であり、自動採用ではない。新しい設置・解像度には対応する校正を `--calibration` で指定する。旧校正の適用可否も現場の設置記録で確認する。

API根拠: [骨格API](https://docs.stereolabs.com/docs/development/zed-sdk/modules/body-tracking/using-the-api)、[物体検出API](https://docs.stereolabs.com/docs/development/zed-sdk/modules/object-detection/using-the-api)、[SDK 5.5変更点](https://docs.stereolabs.com/docs/development/zed-sdk/release-notes/5-x/5-5)。ローカルの `pyzed/sl.pyi` でも型・パラメータを確認した。

## BODY GEN_2 のモデル比較

`export_tracking.py` の `--body-model ACCURATE`（既定）と `--body-model MEDIUM` は、同じSVOの全フレームを書き出す比較用の設定です。いずれも BODY_34 / GEN_2 で、他の書き出し条件は変えません。選択値は `manifest.json` の settings と `camera.json` に記録されます。`--body-model` は頭部モードには影響しません。別モデル同士のSDK IDを同一人物の正解とみなさず、SVOハッシュ、撮影設定、フレーム時刻、目視注釈を照合して比較してください。この機能はローカルSDK模擬試験済みであり、Windows実機での動作確認は別途必要です。
# Inventory-driven contiguous depth export

`export_svo_timeline.py` reads a complete local SVO with the SDK and records only camera metadata, source hash, frame indices, and image timestamps in a new local JSON file. It does not run BODY detection or save images/depth. It rejects incomplete, non-monotonic or misindexed input and refuses an existing output. The timeline is a separate SDK pass and can be used to check depth clips; it does not prove identical depth estimates. The new exporter has simulated tests but has not yet been validated on the Windows SDK PC.

`export_depth_clip.py --local-only` validates the clip in the configured local root without copying any raw depth or images to a share. This mode is used when only derived coordinate results should be shared. Existing `--shared-dir` behavior is unchanged.

`export_depth_inventory.ps1` exports one recording from a verified CSV inventory in contiguous clips of at most 90 frames. It checks the expected SVO hash for every clip, writes locally, validates and mirrors each completed clip through `export_depth_clip.py`, and refuses existing destinations. Use a fresh run ID after a failed attempt; retained local and shared outputs must not be deleted by the script. The driver has not yet been validated on the Windows SDK PC. Available shared and local disk space must be checked before running; it does not check free space on the shared filesystem.

