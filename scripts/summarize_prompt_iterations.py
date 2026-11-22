"""Build the public iteration index from recorded results; never invent scores."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
base=ROOT/'past_versions'/'agent_prompts'
lines=['# 에이전트 MD 개선과 실험 기록','',
 '각 버전의 `prompts/`에 당시 MD 원본, `manifest.json`에 프롬프트·코드·시드 hash, `NOTES.md`에 가설과 실패 원인을 보존합니다. `experiments/`에는 실제 실행 결과를 둡니다. Live와 Mock을 분리하며, 오류·중단·부분 기록을 삭제하거나 성공으로 바꾸지 않습니다.','',
 '**기준 충족**은 T1~T4의 검증된 후보가 당사자 검토를 거쳐 PM 선택 대기에 도달하거나 T5가 Dev·QA의 제약 확인 후 PM 검토로 끝났다는 뜻입니다. 실제 PM 선택·사람 동의·적용 완료율이나 사람 순위 평가 점수가 아닙니다.','',
 '| 버전 | 가설 | 기록된 실행 |','|---|---|---|']
for folder in sorted(base.iterdir()):
    if not (folder/'manifest.json').is_file():continue
    m=json.loads((folder/'manifest.json').read_text());rows=[]
    for p in sorted((folder/'experiments').glob('*/summary.json')):
        records=json.loads(p.read_text());mode=p.parent.name.rsplit('_',1)[-1];ready=sum(r.get('checks',{}).get('expected_outcome_ready',False) for r in records)
        status='부분/스크립트 오류' if (p.parent/'RUNNER_ERROR.md').exists() else '완료'
        seeds=sorted({str(r.get('seed',17)) for r in records})
        rows.append(f'[{mode} · {ready}/{len(records)} · seed {",".join(seeds)} · {status}](agent_prompts/{folder.name}/experiments/{p.parent.name}/summary.json)')
    lines.append(f'| [{folder.name.split("_v",1)[-1]}](agent_prompts/{folder.name}/NOTES.md) | {m["hypothesis"]} | '+('<br>'.join(rows) or '실행 결과 없음 / 원본 보존')+' |')
lines+=['','## 해석과 재실행','',
 '- v003은 형식 복구 중 budget ctx가 복사되어 호출 수 일부가 누락되는 결함이 있었습니다. v003 호출 수를 비용 통계로 사용하지 않습니다. v004에서 재현 테스트와 함께 수정했습니다.',
 '- v001과 v004에서도 T1의 결과를 실패로 남겼으며, 같은 6h를 8h로 바꾸는 문제가 남았는지 실제 Live로 계속 검증합니다. 재견적과 후보 배치를 별개로 검사합니다.',
 '- T4 원문의 예시는 Retest 생략이지만, 월요일에 임시 Integration과 최종 교체를 끝내 Retest를 유지하는 유효 대안도 있습니다. 생략을 강제로 고르도록 프롬프트를 조작하지 않습니다. 생략 후보는 QA 본인 Confirm이 필요합니다.',
 '- 버전별 과거 MD는 런타임 `prompts/` 밖에 두므로 새 run에 옛 지시가 섞이지 않습니다. 실행 중 편집은 이미 시작한 run의 고정된 프롬프트를 바꾸지 않습니다.',
 '- 실제 사람 평가 라벨이나 CE 점수를 대신 만들지 않습니다. Live 실험에서 PM 선택과 당사자 본인 확인은 자동 승인하지 않습니다.','',
 '```bash',
 '.venv/bin/python scripts/prompt_versions.py 다음버전이름 --hypothesis "검증할 변경 가설"',
 '.venv/bin/python scripts/iterate_m4_prompts.py --version past_versions/agent_prompts/버전폴더 --llm live --max-calls 36',
 '.venv/bin/python scripts/summarize_prompt_iterations.py',
 '```','',
 '실험은 버전 manifest와 현재 코드·MD가 같은지 먼저 검사합니다. 이전 코드 hash가 다르면 새 버전을 만들어 실험해야 합니다. 현재 실행·역할 체험은 [Live 가이드](../docs/LIVE_GUIDE.md)를 따르세요.','']
(ROOT/'past_versions'/'README.md').write_text('\n'.join(lines),encoding='utf-8')
