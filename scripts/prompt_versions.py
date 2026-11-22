"""Immutable prompt snapshots for the M4 experiments (no .env, API keys or cards)."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'past_versions'/'agent_prompts'

def snapshot(label,hypothesis):
    stamp=datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S_%f')
    target=BASE/(stamp+'_'+label);target.mkdir(parents=True,exist_ok=False)
    hashes={}
    for p in sorted((ROOT/'prompts').rglob('*.md')):
        rel=p.relative_to(ROOT/'prompts');dst=target/'prompts'/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,dst);hashes[str(rel)]=sha256(p.read_bytes()).hexdigest()
    manifest=dict(version=target.name,created_at=datetime.now().astimezone().isoformat(),hypothesis=hypothesis,prompt_hashes=hashes,
                  code_hashes={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'app').rglob('*.py'))},
                  seed_hashes={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'seed').glob('m4_t*/*.yaml'))})
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (target/'NOTES.md').write_text('# '+label+'\n\n가설: '+hypothesis+'\n\n실행 결과는 이 버전의 experiments/ 아래 저장합니다. 실제 Live, Mock, 모의 당사자 승인은 구분합니다.\n',encoding='utf-8')
    return target

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('--hypothesis',required=True)
    a=p.parse_args();print(snapshot(a.label,a.hypothesis))
