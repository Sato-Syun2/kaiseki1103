# 過去の試行・単発プログラム（必要なときだけ参照）

このフォルダーは、不採用の試行と、過去の特定データだけに使った単発プログラムの保管場所。試行結果は限定されたデータによるもので、他の条件でも効果がないと断定するものではない。単発プログラムの保管は、分析結果が無効という意味ではない。生データは移動・削除していない。ここに保管した出力には人物情報が含まれる場合があり、`results/` はGit管理対象外。

| 試行 | 結果と採否 | 保管物 |
|---|---|---|
| 同一SDK IDの未対応観測を0.2秒保留 | グループ2・3の109録画でID生成は減ったが、位置数が減り保留が増加。グループ3録画001の後方人物の取得時間代理も59.1%→54.5%。不採用。| `programs/evaluate_goal_b_hold*.py`、`results/goal_b_hold_*` |
| 画素位置の履歴から速度の中央値を推定 | 合成試験では揺れを減らしたが、同じ後方人物の取得時間代理が59.1%→50.0%。不採用。 | `programs/evaluate_goal_b_pixel_velocity.py`、`results/goal_b_pixel_velocity*` |
| 録画018の深度点を隣接する深度差だけで連結 | 人物と背景が少しずつつながり、異なる距離を同じ塊として採用する例があった。代表点の結果は不採用。 | `results/depth_person_018_{manual,box,mask}_20261105_01/` |
| 録画018の深度試作の途中版 | 深度帯で比較したが、入力のSVOハッシュ・フレーム番号を追加検証する前の出力。後続版で置き換えた。 | `results/depth_person_018_*_20261105_02/` |
| グループ４・５一括処理の公開前パッケージ | 時刻準備の進捗表示と録画ごとの内部パラメータ差への対応前の途中版。実録画には未使用。 | `programs/group004_005_intermediate_bundles_20261106/` |
| 範囲除外ビューア・一覧の公開前版 | グループ４・５のみの途中版で、グループ２〜５の範囲除外一覧・ビューアに置換。実機には未配布。 | `programs/spatial_viewer_intermediate_20261106/`、`results/group004_005_spatial_gallery_intermediate_20261106/` |
| 深度追跡の目視候補一覧の途中版 | 最初の版は時刻表示と候補照合に誤りがあり、次版は候補の直接再生を追加する前。完成版は通常の `results/tracking_v2/depth_quality_review_20261106_03/` を使用。 | `results/depth_quality_review_intermediate_20261106_01/`、`results/depth_quality_review_intermediate_20261106_02/` |

取得時間は保存画像12枚に基づく代理指標で、連続区間の正解率ではない。いずれも開発中に見たデータであり独立評価ではない。

再現するときはプロジェクトルートを作業ディレクトリとし、`PYTHONPATH=. python3 不要なもの/programs/<スクリプト名>` に必要な引数を付ける。多くは `--help` で確認できる。入力や共通追跡コードが当時から変わっていれば、同じ結果になるとは限らない。保存結果のメタデータは移動前の元パスとハッシュを記録した履歴としてそのまま保持している。

2026-11-05の移動後確認では、速度推定の比較CSVは保存版と一致した。保留試作の再実行は完了したが、保存版と確認点・一致点の集計が一部異なったため、当時の数値は保存版を参照する。

両試行の設定と旧トラッカー・テストは `legacy_body_20261106/body/` に保管している。凍結済み評価のメタデータは移動前のパスとハッシュを記録する。

## 2026-11-06：旧骨格追跡・Goal A/Bの整理

画像と深度からの位置推定を今後の主方式とするため、BODY・骨格に基づく追跡プログラム、Goal A/Bの計画・比較と旧解析結果を保管した。旧コードは `legacy_body_20261106/body/`、旧結果は `results/legacy_body_20261106/results/`。元の場所と移動先の全一覧は `legacy_body_20261106/移動一覧.json` を参照する。移動のみで削除はしていない。旧資料内の絶対パスや、残した校正データへの相対リンクは移動前のままで、再実行にはパスの調整が必要。

- 旧骨格追跡の候補は、一部録画でID対応が改善した一方、録画048では分断が増え、既定設定には採用しなかった。
- SDKの検出条件やモデルの比較は、条件により飛びの数が変わったが、骨格追跡の信頼性改善を結論できなかった。BODY_34のフィッティング無効化試行は、SDKが自動有効化したため有効な比較になっていなかった。
- 深度位置推定で引き続き使う録画別校正、人物領域・深度の試作と追跡結果、深度と骨格の比較による方式選択の根拠、深度距離のポール検証は通常の `results/` に残した。名前に `goal_b` があっても深度距離検証に必要なプログラム・結果は残している。
- 共通SDK書き出し・検証コードや、以前のBODY出力を深度データの時刻照合に使う処理は残している。ここにある旧骨格結果を深度由来の位置として扱わない。

### 共有フォルダからの保管

2026-11-06に、共有 `exchange/` 内のグループ１・48録画の旧BODYモデル比較、BODY_18比較、SDK条件比較、グループ２・３の旧頭部比較出力を `results/shared_exchange_legacy_20261106/exchange/` に移した。深度を使う現行の人物位置推定には使用しない旧比較であり、実験のSVOは含まない。各フォルダはコピー後に全ファイルのSHA-256を元と照合し、元のパス・移動先・集計ハッシュを `results/shared_exchange_legacy_20261106/移動記録.json` に記録した。

現在の深度解析・転送先、グループ２〜４のBODY時刻照合や画像参照に使う書き出し、深度・校正データ、および共有SDK配布物は移していない。共有SDKプログラムは実行中の利用箇所をUbuntu側から完全には確認できないため、旧版を含め元の場所に残している。

## 過去の単発分析

| 対象 | プログラム | 既存の主な結果 |
|---|---|---|
| グループ3録画018の固定画像領域の深度 | `analyze_rec018_depth.py` | `results/tracking_v2/group003_018_depth_analysis_20261105_01/` |
| 既存モデルの動きとSDK重なり比較 | `compare_existing_model_motion.py`、`analyze_sdk_stability_overlap.py` | `results/tracking_v2/model_motion_diagnostic_20261104_01/`、`stability_compare_group003_002_overlap_20261104_02.json` |
| グループ3録画001の追い越し・頭部比較 | `evaluate_goal_b_prepass.py`、`compare_goal_b_group003_heads.py` | `results/tracking_v2/goal_b_prepass_strict_20261104_02/`、`goal_b_group003_heads_20261104_01/` |
| グループ3録画002の混在・目視再生 | `diagnose_goal_b_mixed_confidence.py`、`build_reviewed_overlap_replay.py`、`build_goal_b_manual_exclusions.py` | `results/tracking_v2/goal_b_mixed_confidence_20261104_03/`、`goal_b_manual_exclusions_20261104_02/` |
| ポールの3点サンプル | `inspect_group002_pole_examples.py` | 画像確認済みの固定画素を使った参考例 |
| 旧48録画の基準集計とGoal Aのレポート | `diagnose_tracking.py`、`report_tracking_goal_a.py` | `results/tracking_v2/baseline_20261103/`、`goal_a_20261104_02/quality_report.md` |

上記の名前はすべて `programs/` 内。固定の入力・出力を持つものがあり、特に `analyze_rec018_depth.py` と `compare_existing_model_motion.py` はコマンド引数を持たず、既存出力の上書きを拒否するため再実行には編集が必要。`report_tracking_goal_a.py` が生成する古い再実行コマンドは移動前のパスを示す。旧骨格の結果・画像は上記の保管先に移動し、共有SDK書き出しは元の場所に残す。
