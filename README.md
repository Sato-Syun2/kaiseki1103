# 深度情報による歩行位置解析

画像の人物領域と ZED 深度から位置・暫定 ID を求める手法を、このプロジェクトの主な解析とします。深度による位置は可視表面の代表点で、身体中心や足元の正解ではありません。校正と ID は暫定で、独立した精度検証が必要です。

- [深度解析の計画](docs/depth_person_tracking_plan_20261105.md)
- [SFM等の別プロジェクト向け歩行位置データの見方・受け渡し](docs/sfm_trajectory_handoff_20261106.md)
- [人物深度の試作](docs/depth_person_prototype_usage.md)と[連続追跡](docs/depth_person_continuous_20261105.md)
- [SSD での深度解析と再生](docs/depth_ssd_portable_20261105.md)、[進捗表示](docs/depth_ssd_progress_20261105.md)
- [10 m以内の位置と急変の保留](docs/trusted_depth_10m_20261106.md)
- [上半身・頭の向きの姿勢推定（試作）](docs/upper_body_pose.md)
- [廊下校正・撮影](docs/tracking_calibration_capture.md)、[深度出力 SDK パッケージ](zed_sdk_package/tracking_v2/README.md)

`depth_person_prototype.py` と `corridor_tracking/` の深度関連プログラムが主な解析コードです。LiDAR と深度を使う校正コード、録画条件の `experiment_metadata/`、共有 SDK 書き出しコードは共通の場所にあります。BODY 出力を深度との時刻・入力照合に使う箇所もありますが、骨格や SDK 人物 ID を深度由来の位置・ID 推定に使うものではありません。

従来の BODY・骨格追跡、Goal A/Bの旧資料や関連しない解析結果は [不要なもの](不要なもの/README.md) に保管しています。過去の検証が必要なときだけ参照してください。グループ２・３の録画別校正値、深度の距離検証、深度による位置とIDの解析結果は `results/` に残しています。

プロジェクトコードと校正・実験条件を管理し、録画、人物画像、骨格・軌跡などは `.gitignore` に従って扱います。Windows SDK 実行には対応する実機環境が必要です。
