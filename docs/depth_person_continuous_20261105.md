# 深度による連続追跡：実行手順と現状

画像の人物領域と深度の表面代表点を対応付ける試作を追加した。SDK骨格・SDK人物IDは追跡に使わない。IDは画像枠と利用できる深度位置の一対一対応で付け、競合や深度の急変で判断できない場合は未確定にする。深度なしでも画像上のID候補を保持するが、3D位置を補間・予測して埋めない。しきい値は未検証であり、再生は実際の人物IDを保証しない。

[17フレームでの試験再生](../results/tracking_v2/depth_person_018_tracking_20261105_01/index.html)はフレーム3〜9の7フレームだけ連続し、その後は間引きである。再生時間は保存時刻に従い、図の線はフレーム番号が隣接し、かつ同じIDの深度候補がある場合だけ結ぶ。画像上の枠は暫定ID、点群の色は各時刻の検出結果であり、色の番号を人物IDとみなさない。フレーム45と60では前の保存画像から0.5秒超が空くため、既定設定では新しいIDになる。これを実際の人物交代と判断しない。

17画像の34検出のうち28件は深度代表点候補があり、6件は深度不確定。追跡結果は観測34件で、画像だけを使うID候補も含む。結果は表面の推定点であり、骨盤・歩行中心・地面の接地点ではない。手動正解や独立した位置測量はなく、この試験でID精度や歩行位置の正確さは評価できない。

## Windows SDK PCで連続90フレームを書き出す

連続区間での評価には追加出力が必要。以下は、録画018の0〜89フレームについて、各フレームの左画像と2画素間隔のZED深度を保存する。SVO全297フレームは読み切るが、保存する深度・画像は指定した90フレームだけ。これは全録画の深度出力ではない。深度信頼度画像は含まれない。既存の `NEURAL` 深度書き出しを使用し、BODYのSDK設定に深度範囲とランタイム既定値を合わせる。深度とBODYは別パス。

SDK 5.5.1で以前成功したPython環境のPowerShellを使う。SVOが `F:` にない場合だけ `$Svo` を実際のローカルディスクまたは接続SSDのパスに変更する。同じタグや共有先が存在する場合は上書きせず停止するため、再実行時はタグと共有先名を両方変更する。

```powershell
$Package = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261105_depthclip_01'
$Svo = 'F:\experiment_data\20261104_group003\recording_018\recording_018.svo2'
$SharedRun = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\group003_018_depth90_20261105_01'

python "$Package\export_depth_clip.py" `
  --svo "$Svo" `
  --setup-id group003_hallway_20261104_candidate `
  --tag group003_018_depth90_20261105_01 `
  --shared-dir "$SharedRun" `
  --first-frame 0 --frame-count 90 --pixel-stride 2 `
  --expected-svo-sha256 73f2c8a64e4fe873a0b93019f1f63b89aeca6574a355eedde4eac0545585626c
if ($LASTEXITCODE -ne 0) { throw '深度出力・検証・共有のいずれかが失敗しました。表示されたローカル出力とログを残してください。' }
```

成功時は `Export status: validated` と `shared copy complete` が表示される。プログラムは入力SVOのハッシュを確認し、SDK子ツールを `%USERPROFILE%\kaiseki1103_exchange\.sdk_tools\tracking_v2_20261105_depthclip_01` にコピーする。その後、`%USERPROFILE%\kaiseki1103_exchange\group003_018_depth90_20261105_01\` に一次出力・`export.log`・`validation.log`・`batch_summary.json` を作り、検証に成功した場合だけ共有先に複製する。入力SVOは変更しない。共有へのコピーが失敗した場合もローカル結果は保持される。

90フレーム分の深度点をまとめてメモリに保持する既存方式なので、空きメモリとローカルディスク容量に余裕が必要。17フレームで圧縮約74 MiBだったが、90フレームの保存量・ピークメモリや処理時間は未実測。失敗したときはログと途中結果を残し、新しいタグでフレーム数を減らして調査する。

このラッパーはUbuntuで失敗時の保全・ローカル優先の模擬試験を行い、配布ファイルのハッシュを確認した。**WindowsのZED SDK実機では未実行**。完了表示だけで中身の正確さを保証しない。

## Ubuntu側：受領後の照合と再生

共有同期後、プロジェクトルートで次を実行する。最初のコマンドは出力ハッシュ、元SVO、カメラ設定、BODYと深度の同一フレーム番号・画像時刻を確認し、0〜89が連続していることを検査する。BODYは照合のみに使い、人物領域や位置・IDの推定には渡さない。

```bash
DEPTH=/data/experiment_data/kaiseki1103/exchange/group003_018_depth90_20261105_01/depth
BODY=/data/experiment_data/kaiseki1103/exchange/group003_20261104_candidate_01/recording_018/body
CAL=results/tracking_v2/group003_20261104_analysis_01/scoped_calibrations/recording_018.json

python3 -m corridor_tracking.depth_alignment --depth "$DEPTH" --body "$BODY" \
  --first-frame 0 --frame-count 90 --output results/tracking_v2/NEW_DEPTH_ALIGNMENT.json

YOLO_CONFIG_DIR=/tmp/kaiseki_yolo_config .venv-depth/bin/python depth_person_prototype.py \
  --depth "$DEPTH" --method mask --model models/yolov8n-seg.pt --calibration "$CAL" \
  --output results/tracking_v2/NEW_DEPTH_FRAMES

python3 -m corridor_tracking.depth_tracking --input results/tracking_v2/NEW_DEPTH_FRAMES \
  --output results/tracking_v2/NEW_DEPTH_TRACKING
```

一連の出力名は既存のものと重ならない名前に変更する。新しい深度出力の受領・照合結果を見てから、実際の90フレームで生成したページを確認する。自動マスク、使用した点、深度の保留理由と暫定IDを、手動で可視人物を注釈した画像と比較する。SDKの骨格由来位置との比較も、各フレームの同一人物を確認して別途行う。表面代表点と骨盤は異なるため、単純な差を位置誤差と呼ばない。

さらに未確認の単独歩行、重なり、追い越し区間を選び、同様に連続出力と独立注釈を準備する。今回の0〜89フレームは開発用で、未見評価ではない。

## 2026-11-05受領後の確認

Windows SDK PCから90フレームを受領し、入力SVOハッシュ、画像・深度ファイルのハッシュ、BODYと0〜89のフレーム番号・画像時刻の一致を確認した。[照合結果](../results/tracking_v2/group003_018_depth90_alignment_20261105_01.json)と[連続画像の試作再生](../results/tracking_v2/group003_018_depth90_tracking_20261105_01/index.html)。

自動マスクは各フレーム2領域を出力した。180領域のうち151は深度代表点候補があり、29は深度が曖昧として保留された。画像による対応を含めると2つの暫定IDがそれぞれ90フレームに付いたが、これは人手で確認したID精度や検出率ではない。深度が保留された29領域に3D位置は与えていない。暫定的な校正による表面候補であり、実際の身体中心との位置誤差は未評価。

録画全体を再生するための残り207フレームの分割出力と結合手順は[録画全体の深度再生](depth_full_recording_20261105.md)を参照する。
