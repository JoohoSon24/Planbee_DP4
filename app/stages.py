"""Public workflow stages, distinct from negotiation rounds and demo feed steps."""
STAGES = [
    dict(id='01', key='input', title='입력·재견적'),
    dict(id='02', key='deadline', title='기한 회복'),
    dict(id='03', key='fairness', title='공정성 협상'),
]
SUPPORT = dict(id='별도', key='support', title='PM·명시적 조작')


def for_node(run, node):
    if run.kind == 'candidate':
        if node == 'candidate_input':return dict(STAGES[0])
        if node == 'candidate_generate':return dict(STAGES[1])
        if node in ('candidate_pm','candidate_confirm'):return dict(id='04',key='pm',title='PM 최종 결정')
        return dict(STAGES[2])
    if run.kind != 'record':
        return dict(SUPPORT)
    if node in ('ingest', 'dependency_check', 'deadline_gate'):
        return dict(STAGES[0])
    if node == 'fairness_gate':
        return dict(STAGES[2])
    if node == 'done':
        return dict(run.ctx.get('workflow_stage') or STAGES[0])
    return dict(STAGES[2] if run.ctx.get('rebalance_reason') == 'fairness' else STAGES[1])
