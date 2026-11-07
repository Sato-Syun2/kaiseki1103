# 2026-11-04 グループ2・3 書き出しと校正候補

図つきの確認ページ: [グループ2・3 校正と解析](20261104_group002_group003/index.html)

## グループ2 BODY_34

共有交換先を分けて保存した前半・後半を合わせ、`recording_001`〜`recording_055` の全55件にフルSVOの完了マニフェストがあります。前半001〜015と後半017〜055はWindowsの検証ログが終了コード0です。前半016は共有切断で検証ログが途切れたため、Ubuntu上で改めて出力全体を検証し、352/352フレーム、552観測、121画像のハッシュ確認まで通りました。

| 番号 | 共有先 | 件数 |
|---|---|---:|
| 001〜016 | `exchange/group002_20261104_candidate_01/` | 16 |
| 017〜055 | `exchange/group002_20261104_candidate_02/` | 39 |

## LiDAR空間校正候補

各校正録画のLiDAR点群から廊下両壁を独立に当てはめた暫定値です。廊下幅は3候補で2.376〜2.379 mにまとまりました。LiDAR原点の高さ候補は各2.485 mです。ZEDカメラ原点との対応と変換はまだ含みません。

| グループ | 録画 | 推定廊下幅 | 点群フレーム | 可視化 |
|---|---|---:|---:|---|
| 2 | calibration_001 | 2.379 m | 746 | [SVG](20261104_group002/calibration_001/lidar_candidate/lidar_corridor_candidate.svg) |
| 3 | calibration_001 | 2.377 m | 283 | [SVG](20261104_group003/calibration_001/lidar_candidate/lidar_corridor_candidate.svg) |
| 3 | calibration_002 | 2.376 m | 744 | [SVG](20261104_group003/calibration_002/lidar_candidate/lidar_corridor_candidate.svg) |

対応するJSONにはIMU姿勢、LiDARフレームの壁位置と縦方向範囲、元MCAPのパスを記録しています。

## ZED・LiDAR校正候補

校正SVO深度3件は全件 `validated_depth_export` で、SDK 5.5.1・ZED S/N 35290843・1920×1080として検証済みです。グループ2は `calibration_001`、グループ3は指定された `calibration_002` の深度を使いました。グループ3の `calibration_001` 深度は今回の校正計算に使っていません。

| グループ | 使用した深度録画 | サンプル数 | カメラ高候補 | ZED可視壁まで | LiDAR壁幅から推定した反対壁まで | 結果 |
|---|---|---:|---:|---:|---:|---|
| 2 | calibration_001 | 146 | 2.401 m | 2.103 m | 0.276 m | [JSON](20261104_group002/calibration_001/zed_depth_calibration_candidate/zed_corridor_candidate.json) · [SVG](20261104_group002/calibration_001/zed_depth_calibration_candidate/zed_corridor_cross_section.svg) |
| 3 | calibration_002 | 145 | 2.431 m | 2.065 m | 0.311 m | [JSON](20261104_group003/calibration_002/zed_depth_calibration_candidate/zed_corridor_candidate.json) · [SVG](20261104_group003/calibration_002/zed_depth_calibration_candidate/zed_corridor_cross_section.svg) |

どちらも候補値です。反対壁の位置はZEDが見た壁とLiDARが求めた両壁が同じ境界であるという仮定を置いています。カメラ高と平面当てはめの残差、現場のカメラ設置位置を確認してから採用します。グループ2と3は同じカメラ個体ですが、設置条件の取り違えを避けるため別 `setup_id` の候補にしています。

## グループ3実験録画

`recording_001`〜`recording_054` の54件のSDK BODY_34書き出しを取得し、全件の解析とファイル検証を完了しました。グループ3専用の `calibration_002` 暫定校正を適用しています。

[解析レポート](tracking_v2/group003_20261104_analysis_01/analysis_report.md) / [録画別の軌跡表示](tracking_v2/group003_20261104_analysis_01/sdk_reference_gap_aware_overview.html)。候補はID分断が多く未採用で、SDKの元IDも人物の正解を保証しません。絶対距離精度は独立検証していません。

SDK書き出しパッケージは `/data/experiment_data/kaiseki1103/zed_sdk_package/tracking_v2_20261104_test005_10/`、校正候補は `results/20261104_group002/calibration_001/zed_depth_calibration_candidate/` と `results/20261104_group003/calibration_002/zed_depth_calibration_candidate/` にあります。
