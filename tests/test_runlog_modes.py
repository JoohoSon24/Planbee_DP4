"""Mode-aware transcript paths and truthful mode changes on resumed runs."""
from pathlib import Path
import pytest
from sqlalchemy.orm import Session
from app import llm,runlogs,store
from app.models import Run


@pytest.fixture
def db():
    engine=store.make_engine('sqlite://')
    with Session(engine) as session:yield session
    engine.dispose()


@pytest.mark.parametrize('mode',['mock','live'])
def test_run_records_adapter_mode_origin_and_relative_path(db,monkeypatch,mode):
    adapter=object.__new__(llm.LiveLLM) if mode=='live' else object.__new__(llm.MockLLM)
    monkeypatch.setattr(llm,'_llm',adapter)
    run=Run(kind='record',step='ingest',ctx={});db.add(run);db.flush()
    assert run.ctx['llm_mode']==mode
    assert Path(run.ctx['transcript_file']).parts[0]==mode
    target=runlogs.directory()/run.ctx['transcript_file']
    assert target.exists() and f'- LLM 모드: {mode}' in target.read_text()
    assert '- 실행 출처: test' in target.read_text()
    name=run.ctx['transcript_file'];db.commit();db.expire_all()
    assert db.get(Run,run.id).ctx['transcript_file']==name


def test_resumed_run_with_different_adapter_is_mixed_without_duplicate_file(db,monkeypatch):
    monkeypatch.setattr(llm,'_llm',object.__new__(llm.MockLLM))
    run=Run(kind='record',step='ingest',ctx={});db.add(run);db.flush()
    original=runlogs.directory()/run.ctx['transcript_file']
    monkeypatch.setattr(llm,'_llm',object.__new__(llm.LiveLLM))
    run.ctx={**run.ctx,'resumed':True};db.flush()
    target=runlogs.directory()/run.ctx['transcript_file']
    assert run.ctx['llm_mode']=='mixed' and run.ctx['llm_modes']==['mock','live']
    assert target.parent.name=='mixed' and target.name==original.name
    assert target.exists() and not original.exists()
    assert len(list(runlogs.directory().rglob('*.md')))==1


def test_legacy_record_never_inherits_current_live_mode(db,monkeypatch):
    monkeypatch.setattr(llm,'_llm',object.__new__(llm.LiveLLM))
    root=runlogs.directory();root.mkdir(parents=True)
    (root/'old.md').write_text('legacy unknown execution')
    run=Run(kind='record',step='ingest',ctx={'transcript_file':'old.md'})
    db.add(run);db.flush()
    assert run.ctx['llm_mode']=='mixed' and run.ctx['llm_modes']==['unknown','live']
    assert (root/'mixed/old.md').exists() and not (root/'old.md').exists()
