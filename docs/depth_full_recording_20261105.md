# グループ3録画018：録画全体の深度再生

> 2026-11-05更新：以後は深度・画像を共有しない。[Windowsローカル解析・座標のみ共有](depth_local_coordinates_20261105.md)を使用する。以下は録画018の過去の手順と記録。

現在の再生は全297フレームのうち0〜89のみ。すでに受領・照合・解析した90フレームは再利用し、残りの90〜296を69フレームずつ3回書き出す。各回は同じSVO全体を読み、指定した連続区間だけを保存する。分割すると既存のSDK書き出しが一度に保持する深度点を減らせるが、ピークメモリ・時間は実機での保証値ではない。90フレームの書き出しはこのPCで成功しており、共有に届いた深度・画像は約400 MiB。残りは内容によって変わるが、ローカルと共有の両方に十分な空き容量を用意する。

## Windows SDK PCで残りを出力

グループ4のSDK処理が動作中なら、その終了後に実行する。SDK 5.5.1で動いたPython環境のPowerShellを使う。`$Svo` が異なる場合はWindows上の実際のSVOパスに変更する。

```powershell
$Package = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\tracking_v2_20261105_depthclip_01'
$Svo = 'F:\experiment_data\20261104_group003\recording_018\recording_018.svo2'
$ExchangeRoot = '\\tsclient\_data_experiment_data\kaiseki1103\exchange'
$LocalRoot = Join-Path $env:USERPROFILE 'kaiseki1103_exchange'
$Starts = @(90, 159, 228)

if (-not (Test-Path -LiteralPath $Svo -PathType Leaf)) { throw "SVOがありません: $Svo" }
foreach ($Start in $Starts) {
  $Last = $Start + 68
  $Tag = 'group003_018_depth_{0:D3}_{1:D3}_20261105_01' -f $Start, $Last
  if ((Test-Path -LiteralPath (Join-Path $LocalRoot $Tag)) -or
      (Test-Path -LiteralPath (Join-Path $ExchangeRoot $Tag))) {
    throw "出力先が存在します: $Tag。既存データを上書きしないでください。"
  }
}

foreach ($Start in $Starts) {
  $Last = $Start + 68
  $Tag = 'group003_018_depth_{0:D3}_{1:D3}_20261105_01' -f $Start, $Last
  $SharedRun = Join-Path $ExchangeRoot $Tag
  python "$Package\export_depth_clip.py" `
    --svo "$Svo" `
    --setup-id group003_hallway_20261104_candidate `
    --tag "$Tag" --shared-dir "$SharedRun" `
    --first-frame $Start --frame-count 69 --pixel-stride 2 `
    --expected-svo-sha256 73f2c8a64e4fe873a0b93019f1f63b89aeca6574a355eedde4eac0545585626c
  if ($LASTEXITCODE -ne 0) { throw "失敗: $Tag。ローカル出力とログを残してください。" }
}
Write-Host '3区間の書き出し・共有が完了しました。'
```

区間は `090_158`、`159_227`、`228_296`。各区間はまずWindowsローカルの `$LocalRoot` に保存・検証し、完了時に共有へコピーする。SVOは読み取り専用。各区間で `Export status: validated` と `shared copy complete` が出る。途中で失敗した場合は既存の成功区間やローカルのログを残し、失敗した区間の状況を確認する。この3区間をまとめるコマンドは、すでに存在する出力を上書きせず停止する。

## 共有受領後のUbuntu処理

各深度出力を既存のBODYと照合し、SVOハッシュ、セットアップ、フレーム番号、時刻、ファイルハッシュ、連続範囲を確認する。各区間を同一モデル・同一設定で処理し、元の0〜89と結合してから、**全297フレームを一続きで追跡し直す**。区間ごとに作ったIDを後からそのまま結合しない。

結合コマンド `python3 -m corridor_tracking.merge_depth_person_runs` は `--part <人物深度結果ディレクトリ> <BODYとの照合JSON>` を区間ごとに指定する。`--first-frame 0 --frame-count 297 --require-full-svo` とすると、全フレームが過不足なく一度ずつあり、同じBODY出力・モデル・設定・校正・解析コードに対応することを確認する。実行後の結果を `python3 -m corridor_tracking.depth_tracking` に渡すと、既存の再生ページと同様に画像・暫定ID・可視表面の位置を表示できる。

各区間は別SDKパスである。照合できるのは同じSVO・フレーム番号・画像時刻と記録されたカメラ設定であり、深度推定の内部状態が1パスの全録画と一致する保証はない。境界の深度変化も確認する。代表点は身体中心ではなく、IDや位置の正確さは独立した正解で未評価。

## 2026-11-05：全区間の受領と再生

3区間のSDK出力を受領し、元の0〜89と合わせてSVOハッシュ、BODYとの画像時刻、出力ハッシュ、0〜296の連続性を確認した。共通の人物領域モデル・設定で解析し、全297フレームを結合してから追跡した。[録画全体の深度再生](../results/tracking_v2/group003_018_depth_full_tracking_20261105_01/index.html)。再生は記録時刻に従う。枠は暫定ID、色付きの点はそのフレームの深度候補、十字は可視表面の代表点を示す。

全575検出領域のうち538件に深度表面候補があり、33件は深度が曖昧、4件は深度点不足で位置を保留した。フレーム121では対応未確定の候補、228・284・287では一時的な追加IDが生じた。これらを実在する別人物と判断しない。290〜296は検出0件。検出がないことは、画面に人物がいないことの証明ではない。

区間境界では主要ID 1・2が継続したが、227→228ではID 1の表面候補のZが約5.08→4.78m、ID 2が約5.14→4.92mと変化し、さらに深度点不足の追加候補が1件現れた。人物の重なりや可視表面の変化などもあり、分割SDKパスの影響かどうかは確定できない。画像・深度の候補を確認し、追跡IDや身体中心位置の正解と扱わない。
