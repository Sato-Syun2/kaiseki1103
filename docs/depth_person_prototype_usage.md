# 骨格を使わない人物深度の試作

2026-11-05の第1段階。左画像の人物領域と同一フレームのZED深度点だけで、可視表面の代表点候補を作る。骨格データ・SDK人物IDは入力しない。代表点は身体中心や骨盤、足元ではない。後続の暫定ID追跡と連続深度の書き出しは[第2段階の手順](depth_person_continuous_20261105.md)を参照する。骨格の対応付け・再生と絶対位置精度の評価はまだ実装していない。

## 録画018での試行

[17フレーム比較ページ](../results/tracking_v2/depth_person_018_comparison_20261105_03/index.html)は、左から手動の仮枠、自動検出枠、自動人物マスクを同時刻で表示する。色の点は選択した深度点、赤は選択しなかった点、十字は代表点候補。各表示は間引いた点で、集計は全点を使う。表の枠IoUは仮枠との一対一の機械的な対応にすぎず、人物ID・検出精度の正解ではない。

手動の仮枠は画像を見て選んだ2つの概略矩形を全フレームで固定しており、フレームごとに精密に注釈した人物領域ではない。モデルはCOCO学習済みYOLOv8n-seg、入力1280、検出閾値0.15、CPU。17画像すべてに2領域を出力した。手動枠・検出枠・マスクの34領域のうち、深度帯が曖昧として保留されたのはそれぞれ1・5・6領域。検出数や保留数は真の取得率・正答率ではない。前景と背景が同じ深度帯に入れば、採用候補でも背景が混ざり得る。

選択条件はマスク端1pxを削り、複数領域に属する深度点を除いた上で、幅0.8mの最も点が多い深度帯を選ぶ。同じ幅の別の深度帯が主帯の50%以上かつ20点以上ある場合は、両方の理由を保存して位置を保留する。20点未満も保留。これらは試験的なしきい値で、未見データでの性能は未検証。1人の体表が複数深度帯にまたがるだけでも保留し得る。

入力は既存17サンプルのSVOハッシュ・各画像と深度ファイルのハッシュ・フレーム番号・時刻を照合済み。深度はBODYと別SDKパスであり、SDKが骨格推定時に使った内部値と一致する保証はない。廊下座標は既存の暫定校正による候補で、測量済みの絶対座標ではない。

詳細は各出力の `results.json` と `manifest.json`、[手動枠](../results/tracking_v2/depth_person_018_manual_20261105_03/index.html)、[自動枠](../results/tracking_v2/depth_person_018_box_20261105_03/index.html)、[自動マスク](../results/tracking_v2/depth_person_018_mask_20261105_03/index.html)。元の17フレームと既存の骨格再生は変更していない。

## 実行

入力は `export_zed_depth.py` が保存した深度ディレクトリ。新しい出力ディレクトリを指定し、プロジェクトルートから実行する。SVOハッシュ、画像・点群のハッシュ、対応するフレーム番号・時刻、校正のカメラ設定が合わない場合は拒否する。保存されていない深度信頼度画像は使用しない。出力には人物画像とマスク・位置情報が含まれるため `results/tracking_v2/` に置き、Git管理しない。

```bash
DEPTH=/data/experiment_data/kaiseki1103/exchange/rec018_diagnosis_20261105_01/depth
CAL=results/tracking_v2/group003_20261104_analysis_01/scoped_calibrations/recording_018.json
REGIONS=results/tracking_v2/depth_person_018_manual_regions_20261105_01.json

python3 depth_person_prototype.py --depth "$DEPTH" --method manual --regions "$REGIONS" \
  --calibration "$CAL" --output results/tracking_v2/NEW_DEPTH_MANUAL

YOLO_CONFIG_DIR=/tmp/kaiseki_yolo_config .venv-depth/bin/python depth_person_prototype.py \
  --depth "$DEPTH" --method mask --model models/yolov8n-seg.pt \
  --calibration "$CAL" --output results/tracking_v2/NEW_DEPTH_MASK

YOLO_CONFIG_DIR=/tmp/kaiseki_yolo_config .venv-depth/bin/python depth_person_prototype.py \
  --depth "$DEPTH" --method box --model models/yolov8n-seg.pt \
  --calibration "$CAL" --output results/tracking_v2/NEW_DEPTH_BOX

python3 -m corridor_tracking.depth_person_comparison \
  --manual results/tracking_v2/NEW_DEPTH_MANUAL --box results/tracking_v2/NEW_DEPTH_BOX \
  --mask results/tracking_v2/NEW_DEPTH_MASK --output results/tracking_v2/NEW_DEPTH_COMPARISON
```

`--calibration` を省くとカメラ座標のみ出力する。`--window-m`、`--ambiguity-ratio`、`--min-points`、`--erode-px` は試験設定で、変更後は別出力で評価する。入力モデルのパスは実在するローカルファイルに限定し、解析時の重み自動ダウンロードはしない。上記重みは [Ultralytics公式配布](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-seg.pt)、SHA-256 `a7cd8f929e1903d78a12a48efecab430209f18dc46cb96c3599a5980c63c423c`。配布・利用条件は対象モデルとUltralyticsのライセンスを確認する。

今回の自動推論は既存のPython 3.12、Ultralytics 8.4.89、PyTorch 2.12.1、NumPy 2.5.1を使った。システムMatplotlibとの互換エラーを避けるため、Ubuntuに `python3 -m venv --system-site-packages .venv-depth` を作成し、その環境に `matplotlib>=3.9,<4` を追加した。Windows SDK環境は変更していない。CPU推論で動作したが、このPCではGPUドライバーに接続できず、GPU実行や処理速度の評価は未実施。

手動領域JSONは、SVOハッシュと各フレームの画像ハッシュを持つ。各フレームを一度ずつ記載し、人物なしも `regions: []` とする。矩形は左上を含み右下を含まない `bbox_xyxy: [x0,y0,x1,y1]`、または `polygon_xy: [[x,y],...]` を使う。領域名はそのフレーム内で一意にし、可視性・未確認を人手で別途記録する。保存した `masks/` は侵食後の領域マスクであり、観測の正解ラベルではない。

次は画像ごとに人物領域を注釈して誤検出・背景混入・保留を確認し、[連続画像・深度の書き出し](depth_person_continuous_20261105.md)を行う。現在の17フレームから連続軌跡やID維持率を結論しない。
