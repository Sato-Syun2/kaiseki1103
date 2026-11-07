# Windowsで深度解析し、人物座標だけ共有する

> 最新の保存先は `G:\kaiseki1005`。[SSD保存・Windows/Ubuntu再生の手順](depth_ssd_portable_20261105.md)を使用する。以下は以前のCドライブ利用時の記録。

2026-11-05の指定に従い、深度・点群・画像・人物マスクと中間解析結果は `C:\Users\sawaragilab2024\Desktop\sato_shun\1105depth` に保存する。共有するのは、各録画の `positions.json`（フレーム時刻・暫定ID・廊下座標・欠測理由）と `manifest.json`（照合記録）の2ファイルのみ。共有先の一時領域もこの2ファイルしか含まない。SVOと既存出力は変更しない。

共有された座標だけを使う[録画018の上面再生例](../results/tracking_v2/group003_018_coordinates_only_replay_20261105_01/index.html)は、すでにUbuntuで保持していた録画018の解析結果から作った動作確認である。Windowsの新規実行結果ではない。画像は表示されない。深度の可視表面代表点であり、身体中心や足の位置ではない。IDと校正は暫定。

グループ2の55録画、グループ3の54録画のSVOハッシュ・フレーム時刻・各録画に対応した校正を同梱した。すでに処理済みのグループ3録画018を除いた108録画が対象。SDKには既存のPython環境を使い、画像解析用には別の仮想環境を作るため、SDK側のNumPy等は変更しない。画像解析にはインターネット経由でUltralytics 8.4.89等のインストールが必要。人物モデルはパッケージに同梱し、実行時にハッシュを照合する。

Windows Cドライブには、深度だけで概算約157 GiBのほか、画像・中間解析・仮想環境用の空きが必要。実量は録画内容によって変わる。録画開始前にその録画について概算8 MiB/フレームと5 GiBの予備を確認し、足りない場合は停止する。処理済みの深度を自動削除しない。SDKの書き出しは各69フレーム以下の区間でSVO全体を読み直すため、多数録画の処理には長時間を要する。

2026-11-05にpilotの2録画を受領した。[上面再生一覧](../results/tracking_v2/depth_coordinates_gallery_20261105_01/index.html)。グループ2録画001は375フレーム、グループ3録画001は361フレームで、共有先は各録画とも座標JSONとmanifestの2ファイルのみ。フレーム連続性と元SVO・校正・座標ファイルのハッシュを照合した。グループ2では375フレーム中132フレームにID未確定の候補が1つ以上あり、候補の重複等も含み得るため実人数や誤検出率を意味しない。グループ3にも暫定IDが増える区間がある。軌跡や人数の正確さはこれらの照合だけでは未検証。

## Windows SDK PC：まず両グループの録画001

以前ZED SDK 5.5.1の `python` が動作したPowerShellで、下をまとめて実行する。インストール中はネットワーク接続が必要。`-Mode pilot` はグループ2と3の録画001のみを処理する。今回追加したWindows一括実行はSDK実機では未検証なので、まずこの2件の結果を確認する。出力先に同名の処理途中データがある場合は上書きせず停止する。

```powershell
$LocalRoot = 'C:\Users\sawaragilab2024\Desktop\sato_shun\1105depth'
$BundleShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_local_coordinates_20261105_05'
$CoordShare = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_003_coordinates_20261105_01'
powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_local_depth.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" -SharedRoot "$CoordShare" -Mode pilot
if ($LASTEXITCODE -ne 0) { throw '処理が停止しました。Windowsローカルのデータと表示されたエラーを残してください。' }
```

途中経過はPowerShellに表示する。深度区間は `1105depth\depth_clips\`、中間解析と画像は `1105depth\analysis\`、共有用の小さな座標出力の原本は `1105depth\coordinates\` に残る。共有先は `...\exchange\depth_group002_003_coordinates_20261105_01\` で、録画ごとに2ファイルだけを安全にコピーする。共有に失敗してもローカルを保持する。画像付きの再生を見たい場合はWindowsのローカル結果を使用し、画像や深度を共有へコピーしない。

## 初回確認後に残りを実行

同じPowerShellで、上記の変数が残っていれば以下を実行する。残っていない場合は上記の `$LocalRoot`、`$BundleShare`、`$CoordShare` を再設定する。`-Mode all` はpilotの成功済み2件を座標ハッシュ・元SVO等で照合して再利用し、残りを順次処理する。失敗途中の録画は自動上書き・削除しない。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_local_depth.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" -SharedRoot "$CoordShare" -Mode all
if ($LASTEXITCODE -ne 0) { throw '処理が停止しました。Windowsローカルのデータと表示されたエラーを残してください。' }
```

## Ubuntu：受領した座標の再生一覧

座標出力が届いたら、共有フォルダーの2ファイルとハッシュ、元SVO、校正、全フレームの連続性を確認して上面図を作る。`--output` には新規名を指定し、前回の一覧は上書きしない。未受領の録画は一覧で未受領と表示する。

```bash
python3 -m corridor_tracking.coordinate_gallery \
  --inventory /data/experiment_data/kaiseki1103/exchange/depth_group002_003_inventory_20261105_01.csv \
  --shared-root /data/experiment_data/kaiseki1103/exchange/depth_group002_003_coordinates_20261105_01 \
  --output results/tracking_v2/depth_coordinates_gallery_NEW
```

座標変換にはグループごとの暫定校正を使う。廊下原点はそれぞれのカメラの床面投影であり、2つのグループを単一の共通原点として重ねない。区間ごとのSDK実行は別パスであり、ひとつの全録画処理と深度内部状態が完全一致する保証はない。タイムスタンプとSVO・カメラ情報は照合する。
