"""Create a new group 6–9 SSD template from the verified, frozen group 4/5 template."""
import argparse
import json
from pathlib import Path
import shutil

from corridor_tracking.build_group004_pilot_bundle import digest
from corridor_tracking.prepare_group004_005_bundle import verify_template


def replace_once(path, old, new):
    text = path.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise ValueError(f'expected exactly one patch location in {path}: {old}')
    path.write_text(text.replace(old, new), encoding='utf-8', newline='\n')


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    manifest = verify_template(source)
    if output.exists():
        raise FileExistsError(output)
    project = Path(__file__).resolve().parent
    output.mkdir(parents=True, exist_ok=False)
    for name, expected in manifest['files_sha256'].items():
        if name.startswith('timelines/') or name in ('group4_inventory.json', 'group5_recordings.json', 'run_group004_005.ps1'):
            continue
        target = output/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, target)
        if digest(target) != expected: raise OSError(f'copy mismatch: {name}')
    for name in ('prepare_group006_009_bundle.py', 'group006_009_batch.py', 'offline_group006_009.py', 'offline_group004_005.py'):
        shutil.copyfile(project/'corridor_tracking'/name, output/'corridor_tracking'/name)
    shutil.copyfile(project/'corridor_tracking/run_group006_009.ps1', output/'run_group006_009.ps1')
    pipeline = output/'corridor_tracking/local_depth_pipeline.py'
    replace_once(pipeline, 'choices=[2, 3, 4, 5]', 'choices=[2, 3, 4, 5, 6, 7, 8, 9]')
    marker = "    if svo_timeline:\n        metadata['reference_kind'] = 'svo_sdk_timeline_no_body'"
    addition = ("    metadata.update(source_svo_path=row['svo_path'], source_label=row['source_label'],\n"
                "                    reported_trial=row['reported_trial'], base_calibration_sha256=row['base_calibration_sha256'],\n"
                "                    camera_intrinsics_left=json.loads(row['camera_intrinsics_left']))\n"
                "    if svo_timeline:\n        metadata['reference_kind'] = 'svo_sdk_timeline_no_body'")
    replace_once(pipeline, marker, addition)
    replay = output/'corridor_tracking/portable_depth_replay.py'
    replace_once(replay, 'group not in (2, 3, 4, 5)', 'group not in (2, 3, 4, 5, 6, 7, 8, 9)')
    replace_once(replay, 'choices=[2, 3, 4, 5]', 'choices=[2, 3, 4, 5, 6, 7, 8, 9]')
    marker = "        title = f'グループ{group} {recording}' + (' ID再割当て候補' if candidate_dir is not None else '')"
    replace_once(replay, marker, "        title = f'グループ{group} {recording}（元録画: {row.get(\"source_label\", recording)}）' + (' ID再割当て候補' if candidate_dir is not None else '')")
    files = {f.relative_to(output).as_posix():digest(f) for f in output.rglob('*') if f.is_file()}
    (output/'template_manifest.json').write_text(json.dumps({'status':'prepared_not_windows_validated',
        'base_template_manifest_sha256':digest(source/'template_manifest.json'),'files_sha256':files},indent=2)+'\n',encoding='utf-8')
    print(f'Prepared group 6–9 template with {len(files)} files: {output}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args(); prepare(a.source,a.output)


if __name__ == '__main__':
    main()
