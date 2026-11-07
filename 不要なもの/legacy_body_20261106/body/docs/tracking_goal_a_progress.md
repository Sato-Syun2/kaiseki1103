Goal A 実装状況

目的と完了条件は tracking_goal_prompts_20261103.md のGoal A、詳細仕様は tracking_improvement_plan_20261103.md P0〜P5。

2026-11-03: Goalを開始。既存48録画のACCURATE_GEN2出力が存在することを確認。旧版は全grab後にretrieve_bodiesを呼び、保存だけを間引いている。未コミットのREADMEと計画書はユーザー依頼で作成した成果物として保全する。

Ubuntuにはpyzedパッケージがあるが、importは libnvidia-encode.so.1 不足で失敗し、nvidia-smiもドライバー接続に失敗。SDK実機実行は現在利用できない。これをGoal A全体の停止理由とはせず、CPU解析・SDKコードとモック検証・配布物を進め、SDK実機検証だけGoal Bへ引き継ぐ。

2026-11-04 続行: P0〜P5のコード、SDK配布版、校正CLI、互換アダプター、既存CLI統合を実装。38件のCPU/合成/SDKアダプターモック試験が通過。旧リプレイの243点と旧互換アダプターの時刻・SDK IDが完全一致し、座標差は旧CSVの小数4桁丸め範囲。

凍結した原データ基準: results/tracking_v2/baseline_20261103/baseline.json。初期分割は調整001/003/025、評価002/044/048。追加の短区間画像注釈は results/tracking_v2/visual_review_20261104/annotations_final.json。001/003/025の調整に加え、一括処理で分かった005/021/026/035/040の3D状態時刻・到達可能範囲の実装不具合を修正。評価側の結果も既に確認しているため、最終再解析を未見の独立評価とは呼ばない。

追跡候補は body/configs/tracking_candidate_final_20261104.json。最終の出力先 results/tracking_v2/goal_a_20261104_02/ の48件は全件成功、旧8,770点→候補8,640点。003の画像確認点ではIDの人物間再利用1→0、分断下限3→0。044は再利用2→0だが分断が残り、048はSDK骨格の大きな変形付近で分断が増える。候補の既定採用はしない。

位置を保持するゲートには3Dの最終更新時刻を使い、画像によるID更新時刻と区別した。到達可能範囲は外挿先ではなく最後の3D状態を中心に評価する。SDK ID分岐直前の画像位置が飛ぶ点は対応保留に戻す。003の境界では約0.13秒を保留して取り違えを減らした。後方人物の追い越し前の取得開始の改善は未確認。追加部分点は主にカメラ直近の画面外骨盤を上半身から推定したもの。

SDK正本: zed_sdk_package/tracking_v2/。共有配布物: /data/experiment_data/kaiseki1103/zed_sdk_package/tracking_v2_20261104_01/。原共有版は上書きしていない。SDK実機とPowerShellのWindows実行、新しい測量・1080p撮影による性能は未検証でGoal Bへ残す。

最終検証: 48件の入力CSV・原画像6,269枚・出力とコードのハッシュを確認し、旧基準の受付件数は全録画で一致。Chrome上で旧／候補／手動切替と、合成30fps人物・間引き画像の時刻差表示を確認。結果と採否は results/tracking_v2/goal_a_20261104_02/quality_report.md、機械可読の集計は adoption.json と reviewed_interval_metrics.csv、照合結果は verification.json。最終追い越し注釈には未確定な時刻があるため、追い越し前取得時間は未評価としている。

Goal Aの実装・既存録画による評価・SDK配布準備は完了。精度の自動採用条件は満たしていない。SDK実機での出力確認、新設置の測量・1080p・頭部検出の実験結果はGoal Bへ引き継ぐ。
