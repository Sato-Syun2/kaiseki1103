# 過去の試行と単発プログラム

`不要なもの/` は不採用の試行、旧骨格追跡・Goal A/Bの資料、過去の特定データだけに使った単発プログラムを保管する場所。通常の作業では内容を読んだり検索対象に含めたりしない。同じ改善案の再検討や過去結果の検証などで必要になった場合だけ、まず同フォルダーの `README.md` を読み、必要なファイルに限定して参照する。保管物を現行実装や採用済みの結果とみなさない。

# 深度解析と BODY 解析の区分

画像と深度による人物位置・ID解析を主な方式とする。従来のBODY・骨格由来の解析コード、設定、テスト、資料は `不要なもの/legacy_body_20261106/body/` に保管する。BODY方式の過去の結果やモデル選択を深度方式の採用結果とみなさない。

`corridor_tracking/` の共通処理、`zed_sdk_package/tracking_v2/` の共通SDK書き出し・検証、`results/` に残る既存結果にはBODYと深度が混在する。深度処理が必要とする共通コード、録画ごとの校正値、BODY出力との入力・時刻照合、深度距離検証は引き続き利用できる。検索時は `不要なもの/` を除外し、目的に応じて `results/` なども絞る。

# 深度位置の利用範囲

歩行位置の通常利用は、カメラの床面投影を原点とする廊下方向Xが10 m以下、かつ推定された壁の内側に限定する。X=10 mと壁上は含み、Xはカメラからの直線距離ではない。位置欠測は範囲内と決め付けない。明らかな連続時刻の急変は `docs/trusted_depth_10m_20261106.md` の手順で別出力に保留し、元の観測を変更・補間しない。過去の15 m範囲の結果・再生は履歴であり、この10 m条件を満たすとみなさない。

位置は身体中心や足元ではなく、深度から得た可視表面の代表点候補。校正、壁位置、追跡IDは暫定で、10 m以内であることや急変を保留したことは実測に基づく精度の保証ではない。ID未確定の点は同一人物として速度判定できず、欠測をまたぐ不連続やID入れ替わりも残る。元IDは10 m超の観測を含む追跡から得られている。ID番号を被験者番号と同一視しない。

# 解析結果と再生

- `results/tracking_v2/trusted_depth_10m_20261106_01/` は2026-11-06時点の10 m版の一覧・上面再生・判定記録。追加処理を自動反映する一覧ではない。新しい一覧は `python3 -m corridor_tracking.refresh_trusted10_report --report results/tracking_v2/trusted_depth_10m_NEW` のように未使用の出力名で作る。
- `results/tracking_v2/depth_quality_review_20261106_03/` は旧15 m版に基づく目視候補のスナップショットで、現在の10 m版ではない。自動判定の優先度は正解率・誤り率や目視検証済みの判定を意味しない。ID再割当て候補も未検証の別結果で、10 m版に自動適用されていない。
- 大きな変位の保留は、原本を残したうえで座標を欠測にする処理であり、身体位置を復元したり精度を実測検証したりしたものではない。比較では除外・保留した観測数、対象録画・時刻、判定条件と欠測による影響を明示する。
- Windows SSDの旧 `G:\kaiseki1005\depth_replay_index.html` は10 m・急変保留が自動反映されない。10 m版の画像との同時再生は、共有パッケージ `depth_trusted10_replay_20261106_01` で別に作る `G:\kaiseki1005\trusted10_replays_20261106_01\index.html` を使う。実機で未確認の場合はその旨を伝える。背景画像に描画済みの点や輪郭が処理前のまま残る場合がある。

# Windows SSDと共有フォルダ

- SVO/SVO2は実験の元録画で読み取り専用。現在の深度解析はWindowsの元録画（例: `F:\experiment_data`）を読み、実行環境・深度中間データ・画像付き再生・座標のローカル原本をSSD `G:\kaiseki1005` に保存する。容量削減後に点群がない場合は元SVOから再計算できるが、旧結果との完全一致は保証できない。元録画・校正・ログ・原本を上書き、移動、削除しない。
- Ubuntuの共有ルートは `/data/experiment_data/kaiseki1103/`、Windowsからは通常 `\\tsclient\_data_experiment_data\kaiseki1103\`。Ubuntuから見えてもWindowsのリモートデスクトップのドライブ共有が接続中とは限らない。
- `exchange/depth_group002_003_coordinates_20261105_01/` と `exchange/depth_group004_005_coordinates_20261106_01/` は深度由来座標の共有原本。`exchange/depth_group002_005_trusted10_20261106_01/originals/` はそれを基にした10 m・急変保留版。各録画の座標とmanifestのハッシュ・録画情報を照合し、原本と別結果を混同しない。`depth_group002_003_spatial_20261106_01/` と `depth_group004_005_spatial_20261106_01/` は旧15 m版。
- 新しい深度処理の共有は座標・時刻・ID・品質理由・照合用メタデータに限る。SVO、深度点群、人物画像や動画を共有先へ複製しない。共有先の既存BODY書き出しには深度解析の時刻照合・画像確認に必要なものがあるため、一律に不要と判断しない。人物データや解析結果を公開Gitへ追加しない。
- 共有接続が切れても解析済みデータを失わず、原則としてSSD上に座標と再生を完成させ、可能な場合は残りの録画も処理する。グループ４・５向けに用意済みのSSDキュー方式は `depth_offline_group004_005_20261106_01` を参照する。解析中は接続回復時に再送し、解析終了後に未共有分があれば `-SyncOnly` で照合・送信する。同期は新規先へ行い、不一致を上書きしない。この挙動を未対応の旧スクリプト全てに備わっていると仮定しない。
- `/data/experiment_data/kaiseki1103/zed_sdk_package/` はWindows配布物の共有先。実行中のSDKプログラム、共有先、WindowsのカレントディレクトリやSSD上の稼働状態はUbuntuだけでは完全に確認できない。稼働中のパッケージ・転送先には干渉せず、既存のパッケージや結果を上書き・移動しない。新しい配布物は別名で作り、ハッシュを確認する。SDKの正本を扱う際は `zed_sdk_package/tracking_v2/AGENTS.md` も読む。
- `corridor_tracking.trusted_depth_10m --watch` が稼働している場合、共有済みのグループ４・５結果を約120秒ごとに別の10 m版へ処理する。監視は全91録画の処理後に終了し得るため、稼働状況と `results/tracking_v2/trusted_depth_10m_watch_20261106_01.log` をその都度確認する。既存結果の数や停止状態を過去のスナップショットから断定しない。
- グループ６〜９の新しい配布物、個別校正、録画の仮名、SSDキューと10 m別結果は `docs/group006_009_depth_20261107.md`。Windows SDKでの全処理を模擬試験だけから成功とみなさない。`recording_900`〜`902` は例外録画の解析上の仮名であり、物理録画番号や被験者IDではない。新しい10 m監視は `corridor_tracking.trusted_group006_009 --watch` で、元の４・５監視とは別プロセス。稼働状況・失敗をログとsummaryで確認する。SSDの画像付き原本再生に10 m制限が自動反映されたとみなさない。
- 共有済み10 m版の追跡確認一覧は `results/tracking_v2/trusted10_quality_live_20261107_01/`。`corridor_tracking.audit_trusted10_live --watch` の稼働中は新着を反映する。グループ４・５の `results/tracking_v2/identity_proposals_10m_group004_005_20261107_01/` は画像未確認の自動基点を使ったスナップショットで、元の10 m版に適用された結果ではない。判断基準・例外・制約は `docs/trusted10_quality_and_identity_20261107.md` を参照する。
- グループ２〜９の10 m版のID候補一覧は `results/tracking_v2/identity_proposals_10m_all_live_20261107_01/`。`corridor_tracking.propose_trusted10_identities_live --watch` が稼働中なら追跡確認済みの新着に候補抽出を行う。計画上の単独歩行は保留し、条件不明の録画は実際の人数や条件を確定せず仮説として扱う。基点はすべて自動選択で画像未確認。元データにも既存の視覚確認済み基点を使った候補にも自動適用しない。監視の稼働と失敗は同名の `.log` および一覧の `summary.json` で確認する。
- 短い基点も検討する候補一覧は別の `results/tracking_v2/identity_short_anchor_v2_live_20261107_01/`。`corridor_tracking.short_anchor_identity_v2 --watch` が稼働中なら新着に反映する。５〜９観測の基点も既存の時系列条件で評価するもので、前の一覧や10 m原本は変更しない。複数候補は保留し、すべて未確定IDとして扱う。比較と画像照合の範囲は `docs/short_anchor_identity_v2_20261107.md` を参照。監視の停止・エラーは同名の `.log` と `summary.json` を確認する。
- 実験計画の左右と未確認ID候補の整合チェックは `results/tracking_v2/overtaking_condition_review_20261108_02/`、競合する候補それぞれの比較は `results/tracking_v2/overtaking_ambiguous_review_20261108_01/`。どちらも作成時点のスナップショットで自動更新しない。計画どおりとは限らず、一致を正解、不一致を追跡の誤りと断定しない。複数候補のうち一つが一致していても他候補が観測不足なら選択しない。再実行・座標軸・制限は `docs/overtaking_condition_review_20261108.md` を参照。
- 2026-11-09の共有430録画について、条件照合を `results/tracking_v2/overtaking_condition_review_20261109_01/` に、競合候補の比較を `results/tracking_v2/overtaking_ambiguous_review_20261109_01/` に別出力した。いずれも自動更新されないスナップショット。10 m処理や暫定ID候補の現行状況は、それぞれの監視とsummaryを確認する。
- SDK BODY_34をグループ７〜９へ別途書き出す配布物は共有先 `zed_sdk_package/body_groups007_009_local_20261109_01/`。新規ランナーは未実機検証で、出力はWindows SSD `G:\kaiseki1005\sdk_body_group007_009_20261109_01` のみ。元録画名を保持しグループ７追加２録画を解析上の仮名901・902にする。同じコマンドで再開できるが、不完全な出力は消さず別attemptに作る。SDK IDは深度IDや被験者IDと同一視しない。

# 録画番号と実験条件

グループ６・７・９の録画を実験条件や人物IDに結び付ける前に `experiment_metadata/recording_exceptions_20261106.md` を確認する。特にグループ６の番号ずれ、グループ７の追加試行、グループ９の試行９は、録画進捗や計画上の条件を実施条件として自動採用しない。元の計画と録画進捗は履歴として保持する。

2026-11-09の実験者の指定により `experiment_metadata/analysis_exclusions_20261109.json` の３録画は歩行・ID・実験条件の解析から除外する。グループ２の録画017に代えて同じ試行の録画018（take 2）、グループ４の録画022に代えて録画023（take 2）を対象にし、グループ７の録画007も除外する。元録画・原本・旧スナップショットは履歴として保持し、旧スナップショットの件数・集計には除外前の３件が含まれる。最新の条件照合は `results/tracking_v2/overtaking_condition_review_20261109_excluded_01/`、競合候補は `results/tracking_v2/overtaking_ambiguous_review_20261109_excluded_01/`。スナップショット以外の任意のスクリプトがこの除外リストを自動適用するとは仮定せず、解析結果に使う前に明示的に確認する。
