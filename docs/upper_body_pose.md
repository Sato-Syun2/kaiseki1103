# 上半身の向きの試作

既存の人物枠と暫定 ID を使い、MMPose の 2D 関節と ZED 深度から、肩・腰・上半身・頭の向きを別結果に保存する。既存の位置計算、ID、原本は変更しない。条件・被験者・主観評価は推定せず、指定した `trial_id` とグループ・録画番号を CSV に残す。別の条件表に明示的なキーで結合する。グループ 6・7・9 の条件は `experiment_metadata/recording_exceptions_20261106.md` を確認し、番号から推測しない。

## 再利用と入力

- 既存の人物解析 `merged` の検出枠、元座標 `positions.json`、同じ元座標から派生した 10 m・急変保留版の座標を使用する。元座標と 10 m版は、それぞれ `positions.json` と `manifest.json` を持つディレクトリを指定する。人物枠の順番と元座標を検証したうえで、10 m版の選択と保留を再実行し、10 m版と一致するときだけ位置を対応付ける。
- ローカルの ZED SDK 深度出力ディレクトリ `depth` をフレーム順に複数指定する。`camera.json`、`frames.csv`、`zed_depth_points.npz`、元の RGB 画像、完了 manifest が必要。全録画の全フレームを重複なく指定する。各ファイル・画像のハッシュ、SVO ハッシュ、setup、校正、フレーム番号、時刻、人物解析で記録された元画像のハッシュを照合する。深度ファイルはクリップ単位で読み込む。
- 容量削減済みで深度がない場合は Windows ZED SDK PC の `zed_sdk_package/tracking_v2/export_depth_clip.py --local-only` で元 SVO から新しいローカル出力先に再書き出しする。分割範囲とパラメータは既存の実行記録を参照する。再計算された深度は以前の結果と同一とは限らない。再生成された RGB ファイルが既存人物解析の画像ハッシュと一致しなければ本プログラムは停止する。画像のハッシュ照合を省略して別録画や異なる映像を結合しない。
- 画像、深度、姿勢出力、再生は SSD 等のローカルディスクに置く。生成した HTML は元深度出力の画像を相対パスで参照し画像を複製しないため、同じドライブを使い、元画像との相対配置を保つ。人物画像や点群を共有フォルダや公開 Git にコピーしない。既存結果を上書きしない。

## モデルと環境

第一候補は [MMPose RTMPose-m COCO 256×192](https://github.com/open-mmlab/mmpose/blob/main/configs/body_2d_keypoint/rtmpose/coco/rtmpose_coco.yml) の設定と対応重み。別モデルも `--model-config` と `--model-checkpoint` で指定できるが、データセットメタ情報に COCO 名の nose、左右 eye、ear、shoulder、hip が必要。既存人物枠ごとに [MMPose 1.x の `inference_topdown`](https://mmpose.readthedocs.io/en/latest/api.html) を使うため、別の人物検出器は不要。モデルの設定と重みのファイルハッシュ、MMPose バージョンと処理条件を保存する。モデル設定が参照する外部 base 設定は単独の設定ファイルハッシュには含まれないので、MMPose 一式も記録・保持する。

[MMPose 公式のインストール手順](https://mmpose.readthedocs.io/en/latest/installation.html)に従い、PyTorch・CUDA・MMCV・MMEngine の対応を確認した**別の解析環境**を用意する。既存の ZED SDK Python 環境は無断で更新しない。プロジェクトの依存（NumPy、OpenCV）も必要。Windows または Linux の解析環境で実行できるが、Windows SDK および MMPose 実機では未検証。

例（実際のパスを置き換える。複数クリップの場合は `--depth` を時系列順に追加）：

```powershell
python -m corridor_tracking.upper_body_pose `
  --positions G:\kaiseki1005\coordinates\RECORDING_TAG `
  --trusted G:\kaiseki1005\trusted10_coordinates\RECORDING_TAG `
  --person-run G:\kaiseki1005\analysis\RECORDING_TAG\merged `
  --calibration G:\kaiseki1005\calibrations\RECORDING_TAG.json `
  --depth G:\kaiseki1005\depth_clips\CLIP_000\depth `
  --depth G:\kaiseki1005\depth_clips\CLIP_001\depth `
  --model-config C:\mmpose\configs\body_2d_keypoint\rtmpose\coco\rtmpose-m_8xb256-420e_coco-256x192.py `
  --model-checkpoint C:\models\rtmpose-m.pth `
  --trial-id EXPERIMENT_TRIAL_KEY --device cuda:0 `
  --output G:\kaiseki1005\upper_body\NEW_RECORDING_TAG
```

パスは例であり実在することを保証しない。CPU は `--device cpu`。`--keypoint-threshold`、`--radius`、`--min-points`、`--max-spread` は調整可能だが既定値を含め実測検証されていない。試行 ID は条件・主観評価表と結び付く実際の安定キーを指定する。推定器が起動しない、照合が失敗する、全区間が不足する場合は処理を停止する。

## 推定値と制限

矩形ごとに鼻・左右目・左右耳・左右肩・左右腰を推定。各関節の近傍に投影した深度点を集め、点数不足、深度の 10–90 パーセンタイル幅の超過、低信頼度、画面外を理由付きで欠測にする。中央値深度を関節画素に投影し、既存の録画別校正で廊下座標に変換する。これは可視表面近傍の候補で、解剖学的関節位置ではない。前後の人や壁が局所領域に混ざっても深度幅だけでは判別できず、点数・閾値は精度保証ではない。

左右関節の水平ベクトルを `right - left` とし、前方を `廊下 Z_up × 左右ベクトル`、yaw を `atan2(Y, X)` の度数（−180〜180°、廊下 X 正方向が 0°、Y 正方向が 90°）とする。肩・腰は別々に保存し、両方存在し差が 60°以下なら円平均を上半身 yaw とする。頭は左右耳の軸から得た粗い近似で、顔の細かな向きや首の回転の直接測定ではない。反対向き・遮蔽・小さい画像・左右の取り違え・着衣や隣接人物の深度で 180°の誤りや欠測が起こり得る。肩や腰の回転を比較する場合は各 yaw を使い、未検証の値を実測として扱わない。

`confidence` は使った関節の MMPose 2D スコアの最小値であり、yaw の確率や精度ではない。各関節のスコア、深度点数・幅、欠測理由を保存する。暫定 ID 不明の検出も姿勢行を保持するが、速度・個人の欠測区間は作れない。対象枠の無い人物は推定できない。位置が範囲外または欠測でも姿勢は保持し、上面の座標や矢印には使用しない。速度は 10 m版の同じ暫定 ID の隣接フレーム間の XY 距離／時間で、欠測や 0.15 秒超の空きはつながない。ID 入れ替わりや深度表面の変化による速度誤差が残る。

## 出力・確認

- `pose.csv`: 検出単位の yaw、スコア、理由、位置、速度と全関節の JSON。検出がないフレームも `no_person_detection` 行として保存。空欄は 0 ではなく欠測。`trial_id`, `group`, `recording` で外部表に結合できる。ID は被験者番号ではない。
- `gaps.csv`: 暫定 ID の最初から最後の検出間で、肩・腰・上半身・頭・速度ごとに連続した欠測フレーム、時刻と理由を記録。未検出、ID不明を同じ人物の観測と決め付けない。区間外の未観測はその ID の欠測として計上しない。
- `pose.json`: フレーム、詳細な関節・深度品質、モデルと照合のハッシュ。`manifest.json`: 出力のハッシュ。`pose_replay.html`: 元 RGB に骨格を重ね、上面の軌跡と部位を選択できる矢印、同一時刻の yaw・速度グラフを表示。時刻スライダー・再生・ID 選択が使える。誤推定メモを検出ごとに記録し、CSV をダウンロードできる。メモはダウンロードするまでブラウザー内のみ。

実験条件や主観評価との対応、角度の符号、顔・背中・横向き、遮蔽や複数人物の交差、10 m 境界、欠測と追跡 ID を実映像と独立した基準で確認する。合成試験のみでは実測精度を判断できない。

## Ubuntu CPU での RTMPose ONNX 実行

保存済みの画像・ZED 深度点群が照合できる場合、Ubuntu の CPU で姿勢推定を行える。SDK は不要で、元の SVO を再処理しない。GPU や SDK が必要な深度の新規書き出しは、Windows の別 PC で既存の手順に従う。

`--backend rtmlib-onnx --device cpu` を指定すると、[OpenMMLab が配布する RTMPose-m Body7 ONNX](https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip) を rtmlib と ONNX Runtime で実行できる。これは上記の MMPose Python API 向け COCO モデルとは別の重みである。`--model-config configs/rtmpose_body7_onnx.json` に入力サイズと COCO 17 関節の並びを明示し、`--model-checkpoint` に展開した `end2end.onnx` を指定する。モデルや並びを変更する場合は対応する設定を別に用意する。解析環境は既存の SDK や深度解析環境とは分け、rtmlib、onnxruntime、互換性のある SciPy を用意する。SciPy は深度点の近傍検索を高速化し、利用できない場合は同じ近傍条件を NumPy で計算する。`--threads` は CPU 推論のスレッド数を指定する。

`--depth-region exclusive-mask` は、すでに検証された人物セグメンテーション結果のマスクを用い、その人物のマスク内で他のマスクと重ならない点だけを各関節の深度候補にする。マスク境界から背景が入る問題を減らす試行であり、マスク自体の漏れ、人体の遮蔽、異なる人の重なりや、耳が縮小済みマスクの外に出る場合は欠測や誤推定が残る。マスク適用前後の近傍点数と欠測理由を JSON に残す。`all` が従来条件で、結果は別出力に保存し比較する。欠測率の減少は精度向上の証明ではない。

## 角度の急変を別結果で保留する

`python -m corridor_tracking.upper_body_yaw_quality --source 姿勢出力 --output 新規出力` は、同じ暫定 ID の隣接フレームについて、時間差0.15秒以下、円周上の角度差45度以上、角速度900度/秒以上を同時に満たす肩・腰・上半身・頭の値を、前後両方とも欠測にする。肩・腰の保留から計算された上半身値も保留する。前後どちらが誤りかを自動確定せず、補間もしない。ID不明、フレームが途切れた区間、欠測をまたぐ変化は判定できない。閾値は `--min-delta-deg`、`--min-speed-deg-s`、`--max-interval-s` で変更でき、実測で妥当性を検証したものではない。速い実際の動きも保留され得る。

元の姿勢出力は変更せず、別出力の `yaw_events.csv` と JSON に元角度・時刻・閾値・理由を残す。CSV の該当角度は空欄、`gaps.csv` に保留区間を残す。GUIでは選択時刻の詳細とイベントCSVから確認できる。位置・速度は変更しない。
