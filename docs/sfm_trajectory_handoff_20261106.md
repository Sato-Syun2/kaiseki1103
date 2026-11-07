# SFM等の別プロジェクトで使う歩行位置データ

作成・保存状況確認：2026-11-06 17:49（日本時間）。この資料は、今回の画像・深度解析から得た歩行位置を見て、SFMなどのパラメーター調整に使う人向けの案内です。SFM側には選択した録画の **`positions.json` だけ**をコピーします。この資料は解析プロジェクトに置き、必要に応じて参照してください。SFMの実装、位置データのコピー、パラメーター推定はまだ行っていません。

## 1. まず経路を見る

1. このPCで[範囲内の深度座標・再生一覧](../results/tracking_v2/group002_005_spatial_gallery_20261106_01/index.html)をブラウザーで開き、グループと録画を選びます。画像なしの上面図です。`originals` は元の暫定ID、`candidates` は一部の観測に暫定IDを追加した別候補です。
2. 「再生」「停止」、時刻スライダー、速度で確認します。横軸Xは廊下方向、縦軸Yは横方向、単位はmです。点と線の色はその録画内の暫定IDを示します。実線は推定した見える側の壁、破線は推定した反対側の壁です。
3. 点と線は観測された位置を示します。0.1秒を超える時間差、欠測やフレームの欠けは線で結びません。ID未確定の点は上面図の軌跡には表示されません。画面下の観測内容には位置不明やID未確定の観測も含まれます。候補の白縁の点・破線は追加した仮IDを示します。

この一覧は**2026-11-06 15:18頃のスナップショット**で、後から完了した録画は自動追加されません。一覧にない場合は下記の座標保存先を確認してください。一覧内の「時刻付き座標」「照合記録」はこのPCの元の共有場所を参照します。ページ自体は確認用で、SFM側にコピーするデータではありません。

画像と同じ時刻の位置を確認する必要があれば、解析用Windows SSD上の `G:\kaiseki1005\depth_replay_index.html` を開きます。SSDの接続と対象録画の再生作成が必要です。画像はSFMプロジェクトに渡しません。範囲除外後のWindows用再生では、画像に元から描かれた点・輪郭が除外前のまま残る場合があります。

## 2. 位置データの保存場所

以下はこのUbuntu環境での絶対パスです。別PCでは共有ドライブのマウント場所が異なります。各録画のフォルダー名は `g002_recording_001_20261105_01` などで、末尾には `compact` や `retry01` が付く場合があります。番号だけでパスを固定せず、実際のフォルダー名を確認してください。

| 内容 | 場所 |
| --- | --- |
| グループ2・3：範囲除外後、元の暫定ID | `/data/experiment_data/kaiseki1103/exchange/depth_group002_003_spatial_20261106_01/originals/` |
| グループ4・5：範囲除外後、元の暫定ID | `/data/experiment_data/kaiseki1103/exchange/depth_group004_005_spatial_20261106_01/originals/` |
| グループ2・3：範囲除外後のID再割当て候補 | `/data/experiment_data/kaiseki1103/exchange/depth_group002_003_spatial_20261106_01/candidates/` |
| グループ4・5：範囲除外後のID再割当て候補 | `/data/experiment_data/kaiseki1103/exchange/depth_group004_005_spatial_20261106_01/candidates/` |

各録画フォルダーに `positions.json` と `manifest.json` があります。**`originals` も範囲除外後のデータ**です。範囲除外前の共有原本は、それぞれ `/data/experiment_data/kaiseki1103/exchange/depth_group002_003_coordinates_20261105_01/`、`/data/experiment_data/kaiseki1103/exchange/depth_group004_005_coordinates_20261106_01/` にあります。SFMで比較する際は範囲除外の有無を混ぜないでください。

上記確認時点で、範囲除外後の `originals` はグループ2が55録画、グループ3が54録画、グループ4が35録画、グループ5が0録画でした。`candidates` はグループ2が3録画、グループ4が20録画です。処理は進行する可能性があり、これらは最終件数ではありません。ファイルがあることは処理・共有の完了を意味し、人物IDや位置の精度を保証するものではありません。

## 3. SFMプロジェクトに渡す方法

1. 比較する録画を選び、まず範囲除外後の **`originals`** の `positions.json` を使います。ID再割当ての影響を検討する場合だけ対応する `candidates` のファイルを別に選びます。両者は同じ録画の代替版であり、別の試行として重複集計しません。候補のIDも正解ではありません。
2. 元の録画フォルダー名を保って、`positions.json` だけをSFMプロジェクトへコピーします。同名ファイルの上書きや、別録画・別版の混同を避けてください。`manifest.json`、再生HTML、画像、深度、SVO、解析コードはコピーしません。
3. コピー前に解析側の `manifest.json` の `status` と `positions_sha256` を確認し、`positions.json` のSHA-256と一致することを確認します。`originals` の正常な範囲除外結果は `complete`、候補は `proposed_not_verified` です。ハッシュの一致はファイル照合であり、追跡の正確さを意味しません。
4. SFM側で入力に使った録画名・版・ファイルのハッシュと、採用した前処理や分割方法を記録します。元ファイルを変更せず、生成した結果は別に保存します。`positions.json` 内にも録画名・時刻・ID・座標と、照合用のハッシュなどが含まれています。

例えばグループ2録画001の元の暫定ID版を確認するには、Ubuntuで次を実行します。表示される2つのハッシュが一致することを確認してください。`manifest.json` は解析側で参照するだけです。

```bash
cd /data/experiment_data/kaiseki1103/exchange/depth_group002_003_spatial_20261106_01/originals/g002_recording_001_20261105_01
sha256sum positions.json
python3 -c 'import json; m=json.load(open("manifest.json", encoding="utf-8")); print("status:", m["status"], "expected SHA-256:", m["positions_sha256"])'
```

## 4. `positions.json` の読み方

JSONは録画ごとに `metadata` と `frames` を持ち、範囲除外版には `walls` と `spatial_filter` も含まれます。`frames` 内はフレーム単位、その `observations` 内はそのフレームで得られた観測単位です。

| 項目 | 意味・扱い |
| --- | --- |
| `metadata.group`, `metadata.recording` | グループ番号と録画名。録画を区別するキーに使う。 |
| `metadata.setup_id`, `metadata.calibration_sha256` | カメラ設置と暫定校正の識別・照合情報。 |
| `frame_index` | 録画内のフレーム番号。 |
| `elapsed_s` | 録画開始からの経過時間、秒。速度算出には実際の時間差を用いる。 |
| `timestamp_ns` | フレーム時刻、ナノ秒の**文字列**。整数に変換して扱い、精度を失う浮動小数点への直接変換を避ける。 |
| `track_id` | 録画内の暫定追跡ID。`null` はID未確定。同じ番号でも録画が異なれば同一人物とは限らず、被験者番号でもない。 |
| `surface_corridor_m` | 廊下座標 `[X, Y, Z]`、m。Xは廊下方向、Yは横方向、Zは床から上向き。`null` は位置不明であり、ゼロ座標ではない。 |
| `depth_status`, `association_reason` | 深度位置の状態と追跡上の対応理由。位置・IDの品質確認に用いる。 |
| `identity_assignment`, `original_track_id` | ID再割当て候補の一部観測にある項目。`identity_assignment: "proposed"` は未検証の仮割当て。元版と区別する。 |
| `walls`, `spatial_filter` | 推定壁と範囲除外の情報。版や録画ごとに確認する。 |

例えば次の観測は、その時刻にID 1の暫定位置があることを表します。数値は形式の説明用です。

```json
{"track_id": 1, "depth_status": "surface_candidate", "surface_corridor_m": [11.71, 1.06, 0.94]}
```

読み込み時の最小例です。`PATH` をコピーした `positions.json` のパスに置き換えます。ID不明や位置不明は勝手に軌跡へ接続せず、元データに残します。

```python
import json
from pathlib import Path

data = json.loads(Path("PATH/positions.json").read_text(encoding="utf-8"))
group, recording = data["metadata"]["group"], data["metadata"]["recording"]
for frame in data["frames"]:
    for obs in frame["observations"]:
        point, track_id = obs.get("surface_corridor_m"), obs.get("track_id")
        if point is None or track_id is None:
            continue  # この例では軌跡を作れる観測だけを表示
        x, y, z = point
        print(group, recording, frame["frame_index"], frame["elapsed_s"],
              track_id, x, y, z, obs.get("identity_assignment"))
```

## 5. SFM調整時に守る解釈

- 座標は画像の人物領域と深度から推定した**可視表面の代表点**です。身体中心・骨盤・足の接地点の実測値ではなく、表面の見え方が変わると点も変動します。床面にXYを投影しても身体中心の正解にはなりません。観測ノイズを含む代理指標として扱ってください。
- 原点はその設置でのカメラ光学中心の床面投影です。校正は暫定で、独立した絶対位置精度検証は未完了です。グループ2・3はそれぞれの原点を使うため、単一の共通原点とみなして重ねないでください。グループ4・5も設置・校正の互換性を確認してから比較してください。
- 範囲除外版は `X > 15 m` または推定された左右の壁の外の位置を除きます。X=15 mと壁上は残し、負のXはこの理由だけでは除きません。位置不明の観測は内外を判定できず残っています。壁と校正は暫定で、特にグループ4・5の反対側の壁はグループ3の幅を使った推定です。除外された点を観測済みと解釈しないでください。
- IDの分断・入れ替わり、誤検出、遮蔽、位置欠測が残り得ます。位置やIDがない区間を無条件に補間したり、IDの異なる点を自動で同一人物に結び付けたりしないでください。速度・加速度は欠測、時刻間隔、座標の揺れに敏感です。採用する平滑化、補間、除外条件は明示し、観測値と区別してください。
- パラメーター調整に使った録画と、性能評価に使う録画は録画単位で分けてください。条件ごとに比較する際は、録画番号だけから実施条件を確定せず、特にグループ6・7・9は[録画と実施条件の例外](../experiment_metadata/recording_exceptions_20261106.md)を確認してください。条件表や参加者情報は位置ファイルには含まれず、SFMに渡す範囲には含めません。

詳細な範囲除外の根拠は[深度座標の範囲除外](spatial_filter_20261106.md)、ID候補の制約は[グループ4の進捗](group004_identity_progress_20261106.md)を参照してください。
