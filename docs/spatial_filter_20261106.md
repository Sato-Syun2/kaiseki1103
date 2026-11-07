# 深度座標の範囲除外

**後の変更:** この文書の15 m設定は過去の出力を説明する。通常利用は [10 m以内の処理](trusted_depth_10m_20261106.md) を参照する。

ユーザー指定により、廊下座標の `X > 15 m`、または左右の壁の外にある観測を範囲外とする。X=15 mおよび壁上の境界は範囲内。負のXを追加条件なしで除外しない。対象はカメラからの直線距離ではなく、廊下方向X。位置が欠測している観測は内外を判定できないため保留して残す。

グループ２・３は各録画の校正に入っている推定壁を使う。グループ４・５はユーザーが同じ廊下幅と確認したため、グループ３で推定した幅 2.376029800280445 m を使い、グループ４の見える壁 `Y=2.1730862846836314 m` から反対側 `Y=-0.2029435155968136 m` を推定する。壁と校正は暫定で、代表点は身体中心ではない。境界ぎりぎりでは深度や校正誤差により実際の人物を除外する可能性がある。

原本と別に、グループ２・３は `exchange/depth_group002_003_spatial_20261106_01`、グループ４・５は `exchange/depth_group004_005_spatial_20261106_01` に、範囲内の座標だけを保存する。各 `originals` / `candidates` の録画フォルダにあるのは `positions.json` と `manifest.json` のみ。除外理由の件数、元座標・候補のSHA-256、壁位置と仮定を記録。フレーム番号・時刻・保持した観測・既存IDは変更せず、位置を補間しない。

既存のID候補は元の候補と原本を照合してから同条件で絞り込む。候補を作成する時点で全IDを改めて推定したわけではない。グループ４の20録画の候補は、候補点、基点と候補フレームの基準IDが今回の範囲内であることを確認済み。IDは暫定で、全フレームの正解は未検証。

現在のUbuntu側監視プロセスは共有されたグループ４・５の新規結果を120秒間隔で確認し、独立した範囲内座標を作る。グループ４はSVO・時刻・校正ハッシュを照合する。グループ５は同じ一括パッケージの記録・設置ID・座標ハッシュと時刻の連続性を確認するが、Windowsにだけある録画別校正ファイルはUbuntuから直接照合できない。全91録画が共有・処理されると監視は終了。プロセスまたは共有が停止した場合は再起動が必要で、既存の同一出力は再利用し、異なる出力は上書きしない。

```bash
python3 -u -m corridor_tracking.filter_shared_positions \
  --source-root /data/experiment_data/kaiseki1103/exchange/depth_group004_005_coordinates_20261106_01 \
  --candidate-root /data/experiment_data/kaiseki1103/exchange/depth_group004_identity_candidates_20261106_01 \
  --output-root /data/experiment_data/kaiseki1103/exchange/depth_group004_005_spatial_20261106_01 \
  --calibration results/tracking_v2/group004_005_coordinate_audit_20261106_01/base_calibration.json \
  --group4-template /data/experiment_data/kaiseki1103/zed_sdk_package/depth_group004_005_batch_20261106_03 \
  --fallback-width-m 2.376029800280445 \
  --expected-bundle-sha256 0e6974e3ccc5f469f4479172a942ecfe213666be9a9f67023775ef53dd0f754a \
  --watch --interval-seconds 120
```

[Ubuntuの範囲内再生一覧](../results/tracking_v2/group002_005_spatial_gallery_20261106_01/index.html)は作成時点のスナップショット。Windowsの別の範囲内再生では、SSD内の既存の確認画像を使用する。画像自体に既に描かれた点・輪郭は除外前のものが残る場合があり、追加表示のID枠と上面図は範囲適用後。新規のWindows再生プログラムは合成テスト済みで、Windows実機では未実行。
