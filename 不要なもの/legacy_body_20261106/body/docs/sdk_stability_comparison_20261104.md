# SDK骨格の安定性比較

目的は、同一SVOでSDKの条件を一つずつ変え、人物の混在・位置の飛び・見失いを同じ画像で比較すること。グループ1は別の撮影・約0.1秒間隔の出力のため参考値として扱う。画像での正解注釈はまだ整備されておらず、自動の数値だけで改善や同等性を確定しない。

現行のグループ2・3のACCURATE GEN_2、BODY_34、NEURAL、fitting有効、prediction 0.2秒、confidence 35、minimum keypoints 8を基準に、次の3条件を1回ずつ別パスで実行する。

| 条件名 | 基準からの変更 | 確認したいこと |
|---|---|---|
| medium | MEDIUM GEN_2 | 別の骨格モデルによる変化 |
| no_prediction | prediction timeout 0秒 | 見失い後のSDK予測による影響 |
| confidence_50 | detection confidence 50 | 検出閾値による影響 |

初回のno_fittingはSDKログにBODY_34では自動的にフィッティングを有効化すると警告があり、実際の無効化比較ではない。camera.jsonのfalseは要求値である。修正版はこの条件を拒否する。

SDK内部の予測・フィッティングがあるため、基準の出力も直接観測の正解ではない。角度判定は肘・膝の3D角度20度未満、または隣接保存フレームで90度超かつ450度/秒超の変化を確認候補とする簡易診断であり、身体としてあり得ない角度の網羅判定ではない。背景・人物間の混在もこれらに当たるとは限らない。骨盤の飛びは0.75m超かつ6m/秒超。個人の正解とSDK IDの正解を使用していないため、誤検出率・追跡成功率ではない。

## 1. Windows SDK PCで書き出し

ZED SDK 5.5.1と既存のPython環境を使う。既存出力と元SVOは変更しない。入力は外付けSSDなどWindows側のローカルSVOを指定する。各パスは実際の環境に合わせて変更する。全3録画×3条件を処理するため時間と空き容量が必要。開始前に出力先のタグが存在しないことを確認する。途中エラーでは出力とログがローカルに残り、最後に失敗として終了する。

```powershell
$Package = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261104_stability_02'
$SharedOutput = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\stability_20261104_02'
python "$Package\export_stability_comparison.py" `
  --tag stability_20261104_02 `
  --shared-dir "$SharedOutput" `
  --job group002 recording_001 group002_hallway_20261104_candidate 'F:\experiment_data\20261104_group002\recording_001\recording_001.svo2' `
  --job group003 recording_001 group003_hallway_20261104_candidate 'F:\experiment_data\20261104_group003\recording_001\recording_001.svo2' `
  --job group003 recording_002 group003_hallway_20261104_candidate 'F:\experiment_data\20261104_group003\recording_002\recording_002.svo2'
```

子ツールを `%USERPROFILE%\kaiseki1103_exchange\.sdk_tools\stability_stability_20261104_02` に複製し、結果を `%USERPROFILE%\kaiseki1103_exchange\stability_20261104_02` に保存する。各出力は `group003/recording_002/medium/body/` 等に作られる。全条件の書き出しと検証が成功した場合に共有へミラーする。共有失敗時はローカル結果を保持するので、以下で再同期する。既に共有先が存在する場合は新しい共有先名を使う。

```powershell
python "$Package\sync_exchange.py" `
  --local-dir "$env:USERPROFILE\kaiseki1103_exchange\stability_20261104_02" `
  --shared-dir "$SharedOutput"
```

1種類だけ試す場合は末尾に `--presets medium` のように指定できる。1録画だけ試す場合は不要な `--job` 行を削除し、新しいタグと出力先を指定する。

## 2. Ubuntuで比較

例としてグループ3録画002を比較する。ほかの録画はBASEとRUNを対応するパスへ変更し、別の未使用出力先を指定する。グループ1の3録画は参考例で、被験者や歩行条件を対応付けた比較ではない。

```bash
BASE=/data/experiment_data/kaiseki1103/exchange/group003_20261104_candidate_01/recording_002/body
RUN=/data/experiment_data/kaiseki1103/exchange/stability_20261104_02/group003/recording_002
REF=/data/experiment_data/kaiseki1103/exchange
python3 -m body.compare_sdk_stability \
  --baseline "$BASE" \
  --candidate "medium=$RUN/medium/body" \
  --candidate "no_prediction=$RUN/no_prediction/body" \
  --candidate "confidence_50=$RUN/confidence_50/body" \
  --reference "$REF/recording_001/model_comparison_20261103/ACCURATE_GEN2" \
  --reference "$REF/recording_003/model_comparison_20261103/ACCURATE_GEN2" \
  --reference "$REF/recording_025/model_comparison_20261103/ACCURATE_GEN2" \
  --review-frame 29 --review-frame 35 --review-frame 41 --review-frame 47 --review-frame 53 \
  --output results/tracking_v2/stability_group003_002_NEW
```

同一SVOハッシュ、全フレームの番号と時刻、解像度、内部パラメータ、深度、設置IDなどを照合し、異なる場合は中止する。`--review-frame` は基準出力に保存した画像のフレーム番号。上記はグループ3録画002の確認済み混在区間なので、別録画では指定を外すか、その録画の保存画像番号に変える。レポート `index.html` は同一画像に各条件の2D骨格を並べ、0.1秒間隔と全フレームの診断を表示する。全フレームの指標はグループ1には存在しない。`summary.json` に設定・入力ハッシュ・イベント、`metrics.csv` に集計を記録する。候補画像は指定フレーム、等間隔8枚、飛びや角度の自動候補から最大30枚で、全時刻や背景誤検出を網羅しない。

## 3. 評価の進め方

まず同じ画像で1人ずつ頭・胴・足の所属、混在、人物以外への検出、消失、ID変化を確認する。骨盤の飛びと肘・膝の数値は確認箇所の手掛かりとし、位置観測数や位置が少なくとも1つあるフレーム数を併記する。誤った検出を見えなくするだけの設定や、人が消えて飛びが減った設定を改善と判断しない。複数人物の正解、連続時刻、位置の実測はない。設定を選んだ後は別録画でも確認する。
