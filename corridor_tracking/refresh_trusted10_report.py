"""Make a new local report from already-published 10 m packets while the watcher runs."""
import argparse
from pathlib import Path
from corridor_tracking.trusted_depth_10m import OUT, SHARE, TAG, load_context, process, save_report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-root',type=Path,default=OUT)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();context=load_context();records=[];failures=[]
    for completed in sorted((a.output_root/'originals').glob('g*')):
        match=TAG.fullmatch(completed.name)
        if not completed.is_dir() or not match:continue
        group=int(match[1]);root=SHARE/('depth_group002_003_coordinates_20261105_01' if group in (2,3) else 'depth_group004_005_coordinates_20261106_01')
        try:
            records.append(process(root/completed.name,context,a.output_root))
        except (OSError,ValueError,KeyError,TypeError) as e:
            failures.append({'tag':completed.name,'error':str(e)})
    save_report(records,failures,a.report)
    print(f'Report: {a.report}; {len(records)} validated recordings; {len(failures)} failures.',flush=True)
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
