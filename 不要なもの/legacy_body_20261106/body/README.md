# BODY 由来解析の旧案内

コマンドはプロジェクトルートから実行する。深度解析を主に使用し、BODYを使う必要がある場合だけこのフォルダーを参照する。過去の成果・選択は深度手法の採用判断を意味しない。

# Group 001 corridor tracking analysis

Ubuntu側で完結する解析コード、校正値、可視化、レポートはこのプロジェクト (`/home/hp-ubuntu/kaiseki1103`) に置きます。ZED SDKを使うWindows PCとの共有フォルダー `/data/experiment_data/kaiseki1103` には、SDK実行パッケージと、PC間で受け渡す生データだけを置きます。

追跡精度の改善に向けた [修正計画](../body/docs/tracking_improvement_plan_20261103.md) と [Goalで実装するためのプロンプト](../body/docs/tracking_goal_prompts_20261103.md) を用意しています。既存データで進める実装・評価と、再書き出し・追加撮影後の検証を分けて記載しています。

追跡v2の実装・既存48録画の比較は [実行方法](../body/docs/tracking_v2_usage.md)、[比較結果](../results/tracking_v2/goal_a_20261104_02/quality_report.md)、[録画別リプレイ](../results/tracking_v2/goal_a_20261104_02/index.html) にまとめました。候補は一部の録画でID対応が改善した一方、録画048では分断が増えており、既定設定には採用していません。Windows SDK再書き出しは [実行手順](../zed_sdk_package/tracking_v2/README.md)、新しい測量・撮影は [校正手順](../docs/tracking_calibration_capture.md) を参照してください。SDK実機と新しい録画での検証は未実施です。

不採用の試行と過去の特定録画用の単発プログラムは `不要なもの/` に保管しています。概要や再現方法は、過去の試行や結果を検証するときに限り同フォルダーの `README.md` を参照してください。人物データを含む保存結果はGit管理対象外です。

骨格から独立して歩行位置を推定する今後の検証は、[深度と人物領域を用いる計画](../docs/depth_person_tracking_plan_20261105.md)を参照してください。

既存17フレームを用いた第1段階の試作と実行方法は、[人物深度の試作](../docs/depth_person_prototype_usage.md)にあります。

人物の暫定ID追跡と、Windows SDK PCでの連続深度出力は[第2段階の手順](../docs/depth_person_continuous_20261105.md)を参照してください。

カメラ位置を下げたグループ4のSDK出力と骨格確認は[グループ4の手順](../body/docs/group004_sdk_review_20261105.md)を参照してください。

```text
kaiseki1103/                         # Ubuntuプロジェクト
  analyze_lidar.py                  # MCAP / LiDAR解析
  analyze_zed_corridor.py           # 深度点から廊下座標系を推定
  body/build_group001_replay.py      # 骨格を廊下座標へ変換し同期再生を生成
  body/process_zed_model_comparison.py # 1モデルまたは複数モデルの受信データを処理
  body/process_group001_batch.py    # group001の複数録画をまとめて処理
  body/group001_replay_template.html
  experiment_metadata/                # group/trial schedule snapshot for result labeling
  results/                          # 校正、比較結果、軌跡、HTML

/data/experiment_data/kaiseki1103/  # Windows PCとの共有
  zed_sdk_package/                  # pyzedを使うWindows用スクリプト
  exchange/                         # SVOから書き出した生データと比較値
```

## Git管理

解析コード、廊下校正値、実験条件の参照データを管理します。録画ファイル、深度点群、人物画像、人物ごとの骨格・軌跡CSV/JSON、同期再生HTMLは `.gitignore` で除外しています。人物を含む生成結果はこのPCの `results/` に残ります。

## 今回の解析結果

廊下校正とセンサー関係の候補は `results/recording_001/` 以下です。LiDARだけで推定した recording_001 / 025 / 048 の廊下幅は約2.36〜2.37 mです。ZED深度から推定した床高とLiDARの床高は約1.3 cm差で一致しました。ZED可視側壁を `Y=+2.185 m`、カメラ側壁を暫定的に `Y=-0.186 m` とし、カメラ位置を `X=0` とする座標系を使います。

今回のモデル比較・同期再生ページ:

- `results/recording_001/model_comparison_20261103/index.html`
- `results/recording_001/model_comparison_20261103/selected/index.html`

選択結果はACCURATE_GEN2です。信頼骨格242件で5モデル中最多でした。軌跡CSVは同フォルダーおよび各モデルのサブフォルダーにあります。校正はLiDARとZEDが同じ廊下境界を観測したと仮定する暫定値です。

録画001〜048の全録画比較の集計は [`results/group001_model_comparison_summary_20261103.md`](../results/group001_model_comparison_summary_20261103.md)、録画別の数値は [`results/group001_model_comparison_summary_20261103.csv`](../results/group001_model_comparison_summary_20261103.csv) にあります。次回group001を解析するときは `ACCURATE_GEN2` 1種類を推奨します。

全録画の再生リンク一覧は、ローカル生成HTML `results/group001_model_comparison_overview_20261103.html` です。各録画の比較ページから5モデルの再生ページと採用モデルの再生ページを開けます。

2026-11-04のtest_002歩行・test_005ポール録画のLiDAR校正候補と進捗は [解析ページ](../results/20261104_test/index.html) を参照してください。group002は55件のBODY_34書き出しが全件検証済みです。group002/group003のLiDAR候補とWindows側のZED校正深度書き出し、group003全54件のBODY_34書き出し手順は `zed_sdk_package/tracking_v2/README.md` にあります。SDK用プログラムの正本は `zed_sdk_package/tracking_v2/`、Windows配布物は `/data/experiment_data/kaiseki1103/zed_sdk_package/tracking_v2_20261104_test005_10/` です。Windows SDK出力はPC内へ保存し、共有接続があれば完了後にexchangeへミラーします。

group002/group003の交換データ確認、LiDAR校正候補、次のWindows書き出し手順は [2026-11-04 group002・group003 進捗](../results/20261104_group002_group003_status.md) を参照してください。

校正候補の断面図とグループ3データ受領状況は [図つき確認ページ](../results/20261104_group002_group003/index.html) で見られます。

録画番号と実験条件を対応付ける場合は [`experiment_metadata/run_order_20261103.json`](../experiment_metadata/run_order_20261103.json) を参照します。これは録画用プロジェクトからコピーした条件表スナップショットで、解析コードは録画プロジェクト内のスクリプトに依存しません。

## 解析手順

### 1. LiDAR校正

ROS 2 JazzyがあるUbuntu環境で実行します。

```bash
source /opt/ros/jazzy/setup.bash
python3 analyze_lidar.py \
  /data/experiment_data/recordings/20261102_group001/recording_001/lidar \
  --output-dir results/recording_001
```

同様に recording_025、recording_048 の `lidar` フォルダーを指定すると各録画のLiDAR候補が出ます。

### 2. ZED SDK PCから深度データを受け取る

Windowsでのコマンドは共有フォルダー内の `zed_sdk_package/README.md` に記載しています。`exchange/recording_001/depth_export` に出力し、完了後にUbuntu側で次を実行します。

```bash
python3 analyze_zed_corridor.py \
  /data/experiment_data/kaiseki1103/exchange/recording_001/depth_export \
  --lidar-candidate results/recording_001/lidar_corridor_candidate.json \
  --output-dir results/recording_001/zed_depth_review
```

これで廊下軸、床、ZEDから見える壁、断面図をUbuntu側に作成します。

### 3. BODYモデル比較結果から同期リプレイを作る

Windows側で5モデルの書き出しを行い、`exchange/recording_001/model_comparison_20261103` が揃ったらUbuntuで実行します。

この受信データから作成済みのページは `results/recording_001/model_comparison_20261103/` にあります。再生成する場合は、出力先に未使用のフォルダー名を指定してください。

```bash
python3 -m body.process_zed_model_comparison \
  /data/experiment_data/kaiseki1103/exchange/recording_001/model_comparison_20261103 \
  --output-dir results/recording_001/model_comparison_20261103_from_exchange \
  --calibration results/recording_001/zed_depth_review/zed_corridor_candidate.json \
  --lidar-candidate results/recording_001/lidar_corridor_candidate.json \
  --time-alignment results/recording_001/lidar_time_alignment_candidate.json
```

Ubuntu側で各モデルの骨格をカメラ基準の廊下X/Y/Zへ変換し、モデル比較ページと録画・骨格・軌跡の同期リプレイを生成します。Windows側はSVOからSDK依存のデータを書き出し、Ubuntu側はそれを受け取って解析・可視化します。

5モデル比較を行わず1種類に絞る場合は、Windows側コマンドに `--profile ACCURATE_GEN2` を追加します。単一プロファイルの結果も同じ処理コマンドで再生ページ化できます。

### 4. group001の録画002〜048をまとめて解析

ZED SDK PCでは、共有フォルダーの `zed_sdk_package/README.md` にあるPowerShellループを実行します。5モデルの書き出し完了後、Ubuntu側で次のコマンドを実行すると、録画ごとの比較ページと採用モデルの同期リプレイを `results/recording_NNN/model_comparison_20261103/` に作成します。

```bash
python3 -m body.process_group001_batch --first 2 --last 48 --tag 20261103
```

録画001で推定した廊下校正とLiDAR廊下幅をgroup001全体に共通適用します。録画002〜048のLiDARは個別の人物追跡には使わず、ZED BODYの3D骨格から歩行軌跡を作ります。出力済みページはスキップし、共有データがまだ届いていない録画や不完全な出力は最後に番号を報告します。

## 座標系

- 原点: ZEDカメラ光学中心を床へ投影した位置 (`X=0, Y=0, Z=0`)
- `X`: 廊下奥向きを正とする長手方向
- `Y`: カメラ側の推定壁からZED可視壁へ向かう方向を正
- `Z`: 鉛直上向き

3D再生では画像と左右が一致するよう、ZED可視壁側を画面左、カメラ側の壁を画面右に配置しています。
