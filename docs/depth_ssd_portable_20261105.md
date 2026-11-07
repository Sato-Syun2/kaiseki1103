# SSDに深度解析を保存し、Windows・Ubuntuで再生する

> 次回用の進捗・終了予想表示は[こちら](depth_ssd_progress_20261105.md)。現在実行中の処理はそのまま続ける。

保存先はWindowsの `G:\kaiseki1005`。深度・画像・中間解析・人物座標、Windows用解析仮想環境、プログラムとモデルをここに置く。共有先へは引き続き人物座標と照合情報だけを送る。SDKの `pyzed` とPython本体は従来どおりWindows PCの動作済み環境が必要で、Windowsの仮想環境をUbuntuで実行できるわけではない。

各録画の全フレーム画像は解析時にすでに保存された画像を利用し、動画ファイルや画像の二重コピーを作らない。画像と上面の人物座標は同じSVOフレームと時刻で照合して表示する。ID、校正、可視表面の代表点は暫定であり、身体中心や足の位置を保証しない。画像を読む速度が追いつかない場合はフレームが飛ぶことがあるが、表示する画像・時刻・上面図は同じフレームに揃える。

## Windows：既存2録画を移して再生を確認

以前のCドライブへの解析が実行中なら終了してから実行する。ZED SDK 5.5.1の `python` を使っていたPowerShellを使用する。初回はGドライブに別の解析用仮想環境を作り、Ultralytics 8.4.89等をインターネットからインストールする。SDK環境は変更しない。

```powershell
$LocalRoot = 'G:\kaiseki1005'
$PriorLocalRoot = 'C:\Users\sawaragilab2024\Desktop\sato_shun\1105depth'
$BundleShare = '\\tsclient\_data_experiment_data\kaiseki1103\zed_sdk_package\depth_ssd_portable_20261105_01'
$CoordShare = '\\tsclient\_data_experiment_data\kaiseki1103\exchange\depth_group002_003_coordinates_20261105_01'

powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_local_depth.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" -PriorLocalRoot "$PriorLocalRoot" `
  -SharedRoot "$CoordShare" -Mode pilot
if ($LASTEXITCODE -ne 0) { throw '処理が停止しました。C・G両方のデータと表示されたエラーを残してください。' }
```

プログラムは以前の `depth_clips`、`analysis`、`coordinates` をCからGへコピーし、内容をSHA-256で照合する。Cの元データは残す。Gに同名のファイルがある場合は同一内容なら再利用し、異なる場合は上書きせず停止する。Windowsの仮想環境はパスが固定されるのでCからコピーせずGに作り直す。`pilot` は共有済みのグループ2・3録画001を照合し、G上の元画像・中間解析・座標から再生を生成する。

完了後、Windowsで **`G:\kaiseki1005\depth_replay_index.html`** をブラウザーで開く。未処理の録画はまだ一覧にない。SSDの画像を読んで表示するので、共有へ画像や点群は送らない。

## 残りの録画

上記で再生を確認した後、同じPowerShellで以下を実行する。変数が残っていなければ上記の `$LocalRoot`、`$BundleShare`、`$CoordShare` を再設定する。既存の2録画はG上のデータを確認して再利用する。グループ3録画018もSSD上に再生を作るため新たに処理し、グループ2・3の全109録画を対象にする。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$BundleShare\corridor_tracking\bootstrap_local_depth.ps1" `
  -BundleShare "$BundleShare" -LocalRoot "$LocalRoot" -SharedRoot "$CoordShare" -Mode all
if ($LASTEXITCODE -ne 0) { throw '処理が停止しました。Gのデータと表示されたエラーを残してください。' }
```

各録画の処理後に再生一覧を更新する。Gの空き容量は録画ごとに概算8 MiB/フレームと5 GiBの予備を確認し、不足時は停止する。全録画では深度だけで概算約157 GiB、画像・中間解析等は別途必要。各クリップはSVO全体を読み直すため処理は長時間かかる。失敗した録画の出力は上書きや自動削除を行わず、停止箇所のエラーを確認する。

## Ubuntu：同じSSDから再生

WindowsでSSDの書き込みが完了したことを確認し、安全に取り外してUbuntuへ接続する。Ubuntuが対応するファイルシステムとしてマウントした後、SSD内の `kaiseki1005/depth_replay_index.html` をファイルマネージャーからブラウザーで開く。Ubuntu上でSDK、Python、仮想環境、インターネットは再生に不要。パソコンやSSDのマウント場所を変えても、HTMLと画像は相対パスで参照する。

UbuntuではSSDを実際に接続しての確認はまだできていない。手元では録画018を使い、フォルダーを別の場所に移した後もブラウザーで画像と同時刻の経路が表示されることを確認した。Windowsでの新パッケージ実行も未検証。
