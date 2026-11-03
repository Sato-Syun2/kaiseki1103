#!/usr/bin/env python3
"""Build Ubuntu-side corridor replays from the raw ZED exchange export."""

from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path


ALL_PROFILES = ("ACCURATE_GEN2", "ACCURATE_GEN1", "MEDIUM_GEN2", "MEDIUM_GEN1", "FAST_GEN1")


def build_replay(
    script: Path,
    folder: Path,
    calibration: Path,
    lidar: Path,
    alignment: Path | None,
    recording_label: str | None,
) -> None:
    command = [
        sys.executable,
        str(script),
        str(folder),
        "--calibration",
        str(calibration),
        "--lidar-candidate",
        str(lidar),
    ]
    if alignment and alignment.is_file():
        command.extend(["--time-alignment", str(alignment)])
    if recording_label:
        command.extend(["--recording-label", recording_label])
    subprocess.run(command, check=True)


def make_report(root: Path, ranking: list[dict], selected: dict) -> None:
    rows = []
    for rank, item in enumerate(ranking, start=1):
        marker = " <strong>採用</strong>" if item["profile"] == selected["profile"] else ""
        rows.append(
            "<tr>"
            f"<td>{rank}</td><td><a href=\"{html.escape(item['profile'])}/index.html\">{html.escape(item['profile'])}</a>{marker}</td>"
            f"<td>{html.escape(str(item.get('detection_model')))} / {html.escape(str(item.get('model_gen')))}</td>"
            f"<td>{item['trusted_skeleton_observations']}</td><td>{item['frames_with_trusted_skeleton']}</td>"
            f"<td>{item['mean_confident_3d_joints']:.1f}</td><td>{item['mean_confident_joint_score']:.1f}</td>"
            "</tr>"
        )
    criteria = selected["criteria"]
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZED BODYモデル比較</title><style>
body{{margin:32px auto;padding:0 20px;max-width:1100px;background:#f1f5f7;color:#1d3445;font:16px system-ui,'Yu Gothic UI',sans-serif}}
section{{background:white;border:1px solid #d5e0e7;border-radius:12px;padding:22px;margin:18px 0}}
h1{{font-size:26px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #dce5eb}}
th{{background:#eaf1f5}}a{{color:#145b91}}.winner{{font-size:20px;color:#126c52}}
</style></head><body><h1>ZED BODY モデル比較</h1>
<section><p class="winner">信頼骨格数による選択: <a href="selected/index.html">{html.escape(selected['profile'])}</a></p>
<p>同一SVO、深度設定、サンプリング間隔で書き出した骨格を、廊下座標系に変換して再生できます。</p></section>
<section><h2>比較結果</h2><table><thead><tr><th>順位</th><th>設定と再生</th><th>モデル / 世代</th><th>信頼骨格数</th><th>骨格が有効な画像数</th><th>平均3D関節数</th><th>平均関節信頼度</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></section>
<section><h2>信頼骨格の判定基準</h2><p>追跡状態 OK、骨盤信頼度 {criteria['minimum_pelvis_confidence']:.0f} 以上、3D座標が有効で信頼度 {criteria['minimum_joint_confidence']:.0f} 以上の関節が {criteria['minimum_confident_3d_joints']} 個以上ある人物フレームを1件として数えます。信頼骨格数を優先し、同数の場合は有効画像数、平均関節数、平均関節信頼度の順で選びます。</p></section>
</body></html>"""
    (root / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exchange_dir", type=Path, help="raw model-comparison export in the shared exchange folder")
    parser.add_argument("--output-dir", type=Path, required=True, help="new Ubuntu project output folder")
    parser.add_argument("--calibration", type=Path, required=True, help="ZED depth corridor calibration JSON")
    parser.add_argument("--lidar-candidate", type=Path, required=True, help="LiDAR corridor candidate JSON")
    parser.add_argument("--time-alignment", type=Path, help="optional LiDAR / ZED time alignment JSON")
    parser.add_argument("--recording-label", help="label displayed in all replay pages")
    args = parser.parse_args()

    source = args.exchange_dir.resolve()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f"output folder must be new or empty: {output}")
    summary_path = source / "comparison_summary.json"
    if not summary_path.is_file():
        parser.error(f"missing model comparison summary: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not summary.get("ranking") or not summary.get("selection"):
        parser.error("comparison summary must contain selection and ranking")
    requested_profiles = summary.get("sdk_comparison_profiles") or ALL_PROFILES
    profiles = tuple(profile for profile in requested_profiles if profile in ALL_PROFILES)
    if not profiles or len(profiles) != len(requested_profiles):
        parser.error("comparison summary lists an empty or unknown model profile")
    for profile in profiles:
        for filename in ("camera.json", "frames.csv", "bodies.csv"):
            if not (source / profile / filename).is_file():
                parser.error(f"missing raw ZED export: {source / profile / filename}")
    if not (source / "shared_images").is_dir():
        parser.error(f"missing sampled image folder: {source / 'shared_images'}")

    if output.exists():
        output.rmdir()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    shutil.copytree(source / "shared_images", output / "shared_images")
    for profile in profiles:
        shutil.copytree(source / profile, output / profile)
    for filename in ("comparison_summary.csv", "comparison_summary.json", "selected_model.txt"):
        path = source / filename
        if path.is_file():
            shutil.copy2(path, output / filename)
    for path in source.glob("*.log"):
        shutil.copy2(path, output / path.name)

    selected_profile = summary["selection"]["profile"]
    if selected_profile not in profiles:
        parser.error(f"unknown selected profile in summary: {selected_profile}")
    selected_dir = output / "selected"
    selected_dir.mkdir()
    for filename in ("camera.json", "frames.csv", "bodies.csv"):
        shutil.copy2(output / selected_profile / filename, selected_dir / filename)

    builder = Path(__file__).with_name("build_group001_replay.py")
    for folder in [*(output / profile for profile in profiles), selected_dir]:
        build_replay(
            builder,
            folder,
            args.calibration.resolve(),
            args.lidar_candidate.resolve(),
            args.time_alignment,
            args.recording_label,
        )

    ranking = summary["ranking"]
    for item in ranking:
        item["replay_page"] = f"{item['profile']}/index.html"
    selected = next(item for item in ranking if item["profile"] == selected_profile)
    summary["selection"] = selected
    selected["selected_replay_page"] = "selected/index.html"
    (output / "comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if (output / "comparison_summary.csv").is_file():
        with (output / "comparison_summary.csv").open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        fields = list(rows[0]) if rows else []
        if "replay_page" not in fields:
            fields.append("replay_page")
        with (output / "comparison_summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                row["replay_page"] = f"{row['profile']}/index.html"
                writer.writerow(row)
    (output / "selected_model.txt").write_text(
        f"{selected_profile}\nReplay: selected/index.html\n"
        f"Trusted skeleton observations: {selected['trusted_skeleton_observations']}\n",
        encoding="utf-8",
    )
    make_report(output, ranking, selected)
    print(json.dumps({
        "comparison_report": str(output / "index.html"),
        "selected_profile": selected_profile,
        "trusted_skeleton_observations": selected["trusted_skeleton_observations"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
