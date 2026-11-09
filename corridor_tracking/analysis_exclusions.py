"""Operator-requested recording exclusions; source data remain untouched."""
import json
from pathlib import Path
import re

REGISTRY=Path(__file__).resolve().parent.parent/'experiment_metadata/analysis_exclusions_20261109.json'


def load_exclusions(path=REGISTRY):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('schema_version')!=1 or not isinstance(data.get('exclusions'),list):
        raise ValueError('invalid analysis exclusions registry')
    result={}
    for item in data['exclusions']:
        group=item.get('group');recording=item.get('recording');sha=item.get('source_svo_sha256')
        if (not isinstance(group,int) or not isinstance(recording,str) or not re.fullmatch(r'recording_\d{3}',recording)
                or not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha) or not item.get('reason')):
            raise ValueError('invalid exclusion entry')
        key=(group,recording)
        if key in result:raise ValueError(f'duplicate analysis exclusion: {key}')
        result[key]=item
    return result


def excluded(row, registry):
    return registry.get((int(row['group']),row['recording']))
