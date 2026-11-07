歩行者追跡 v2 の実行・出力形式（2026-11-04）

Goal Aの成果物は、既存のSDK IDをそのまま使う処理と、新しい対応付け候補を比較するための実装です。既定の旧処理は維持しています。最終比較は `results/tracking_v2/goal_a_20261104_02/`、詳しい判定は同フォルダーの `quality_report.md` を参照してください。人物画像・注釈・軌跡を含む実行フォルダーはGit除外です。

1. 実行

CPU解析はPython 3.12、numpy 2.5.1、OpenCV 5.0.0、Pillow 10.2.0、pytest 7.4.4で検証しました。環境を作る場合の依存関係は `requirements-tracking.txt`。SciPyは不要です。Windows SDK環境へこの依存ファイルを無条件に適用せず、SDKが要求するnumpy/pyzedとの互換性を優先してください。

```bash
cd /home/hp-ubuntu/kaiseki1103
python3 -m pytest -q tests body/tests
python3 -m body.process_group001_batch --first 1 --last 48 \
  --input-tag 20261103 --analysis-tag MY_NEW_RUN \
  --tracking-config body/configs/tracking_candidate_final_20261104.json \
  --annotations results/tracking_v2/visual_review_20261104/annotations_final.json
python3 -m body.verify_tracking_run results/tracking_v2/MY_NEW_RUN \
  --baseline results/tracking_v2/baseline_20261103/baseline.json \
  --report results/tracking_v2/MY_NEW_RUN/verification.json
```

入力タグと解析タグを分離しました。v2は出力先が存在すれば拒否するため、設定変更が既存HTMLの存在によってスキップされません。以前の出力を消さず、新しい解析タグを付けてください。`--tracking-config` を付けない既存コマンドの動作は変更していません。

単一録画は次のいずれでも処理できます。

```bash
python3 -m body.process_tracking_v2 \
  --source /data/experiment_data/kaiseki1103/exchange/recording_003/model_comparison_20261103/ACCURATE_GEN2 \
  --recording recording_003 --config body/configs/tracking_candidate_final_20261104.json \
  --output results/tracking_v2/MY_SINGLE_RUN

python3 -m body.build_group001_replay /path/to/ACCURATE_GEN2 \
  --calibration results/recording_001/zed_depth_review/zed_corridor_candidate.json \
  --tracking-config body/configs/tracking_candidate_final_20261104.json \
  --analysis-output results/tracking_v2/MY_REPLAY --recording-label recording_003
```

`process_zed_model_comparison.py` にも `--tracking-config` を渡せます。v2モードはACCURATE_GEN2の原結果と候補を比較し、旧5モデル比較のランキングをID精度として利用しません。`--output-dir` は新規ディレクトリとし、既存引数の `--calibration` と `--lidar-candidate` を渡します。

新SDK出力では `python3 -m body.process_tracking_v2 --source BODY_FOLDER --heads HEAD_FOLDER` とします。両パスのSVOハッシュ・時刻・カメラ設定が一致しない場合は拒否します。検証器で部分的なsmoke出力を全録画として認識させないため、解析には正常EOFまで完了した出力を使います。

2. 保存形式

| ファイル | 内容 |
|---|---|
| observations.json | 原CSV行のコピー、原ファイル参照、2D/3D関節、実時刻、画像参照、品質フラグ、入力ハッシュ |
| tracking.json | 自動解析ID、元SDK ID、位置、利用部位、対応の候補・採否理由、原観測へのobs_id参照 |
| trajectories.csv | 同内容を表形式へ展開。補間・予測にはobs_idがなく、出所が別区分 |
| metrics.json | 位置数、ID数、出所、各生成軌跡内の欠測。全録画の人物正解率ではない |
| visual_evaluation.json | 画像確認点、全保存画像を確認した短区間の比較。注釈がある場合のみ |
| manifest.json | 入力・画像・校正・設定・出力・コードのハッシュ、環境版、処理時間、候補扱いの明示 |
| index.html | 旧処理／候補を切り替える同期再生。人物時刻と画像時刻を別表示 |

ns時刻はJSONでも文字列のまま保持します。差分だけを秒へ変換します。フレームが保存されていて画像がない新形式でも、人物時刻を丸めません。画像にはその画像時刻の骨格を重ね、解析時刻との差を表示します。人物データのない区間に現在位置の点を残し続けません。

`sdk_id` はSDKの番号、`track_id` は録画内の解析ID、`subject_id` は確認済み被験者番号です。被験者番号を検出順から割り当てません。今回の目視ラベル orange/purple も録画内の衣服による区別であり、被験者番号ではありません。

| position_source | 解釈 |
|---|---|
| sdk_estimate | 現在のSDK出力に裏付けられた骨盤推定。直接測定とは保証しない |
| partial_observation_estimate | 現在の胸・肩・腰・頭と、同一軌跡の部位間オフセットからの推定 |
| two_d_only | 画像上の観測は残るが、位置の根拠が不足 |
| rejected_position | 画像でIDを継続しても、異常な3D位置は採用しない |
| unresolved_identity | SDK IDが分岐する直前など、人物対応が決められない点 |
| no_current_support | SEARCHING、古い検出、領域外等 |
| duplicate_observation / supplemental_head | 重複候補、骨格に対応する補助頭部。別人物として数えない |
| interpolated / predicted / smoothed | 派生位置。観測に基づく取得率に含めない |

`sigma_m` は距離・部位差に基づくヒューリスティックで、校正済み誤差確率ではありません。SDKの高信頼度やOKも正しい人物・直接観測を保証しません。マスクのない旧出力から前景深度の混入を完全に判別することはできません。

3. ID対応と設定

実時間差を使うカルマン予測、一対一割当、2Dの動き、可視部位、衣服の色分布を使用します。SDK IDは弱い補助手掛かりです。2秒の候補保持と、0.2秒の位置予測・補間を分けています。保持中に3Dが失われても画像によるID対応を続けられ、3D位置ゲートは最後の3D更新時刻から計算します。

同時に出た旧・新SDK IDの重複候補を除外し、SDK IDが別人物へ分岐した直前の不自然な画像位置は保留します。最終候補では簡易色特徴だけの強制拒否を無効化し、対応コストの補助に使います。設定・候補・比較用の一要素無効化設定を `body/configs/` に保存しました。平滑化の既定値は0で、完全遮蔽への遡及的な軌跡生成は行いません。

4. 手動アンカー

アンカーは自動出力を上書きせず `tracking_anchored.json` と別評価を作ります。`--anchors anchors.json` は単一録画で使用します。例の数値・IDは入力データに合わせて置き換えます。

```json
[
  {"obs_id":"body:197:64","person_key":"orange","subject_id":null,
   "reason":"元画像で確認した人物。被験者番号は未確認"},
  {"obs_id":"body:285:136","person_key":"orange","subject_id":null,
   "reason":"分断後の同一人物を画像で確認"}
]
```

既定では指定点の自動軌跡全体を同じ `manual:person_key` へ対応付けます。これは確認点からの伝播仮説で、軌跡全体の独立した正解ラベルにはなりません。必要なら `start_s` / `end_s` で確認区間を限定してください。同じ自動軌跡が人物交代している場合も、重ならない区間を異なるperson_keyへ分けられます。`scope: "observation"` は一点だけを指定し、未確定のIDを付けても3D位置を捏造しません。同時刻の別観測を一人へ統合する指定や矛盾した区間指定は拒否します。

今回の実証は `results/tracking_v2/anchor_review_final_003_20261104/`。簡易色特徴による拒否が有効な初期候補の分断をアンカーで接続し、自動と手動を別々に示しています。最終自動候補の結果とは混合しません。

5. SDKと校正

Windows再書き出しは [SDK実行手順](../../zed_sdk_package/tracking_v2/README.md)、追加校正・撮影比較は [校正と撮影の手順](../../docs/tracking_calibration_capture.md) を使います。公開・外部送信・Git pushは行っていません。SDK実機と新規撮影による精度判定はGoal Bに残しています。
