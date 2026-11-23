"""Keep synthetic test transcripts out of the user's real run-history folder."""
import pytest


@pytest.fixture(autouse=True)
def isolate_test_transcripts(tmp_path, monkeypatch):
    from app import llm
    monkeypatch.setenv('PLANBEE_LLM','mock')
    monkeypatch.setenv('PLANBEE_T6_FORCE_AGREE','0')
    monkeypatch.setattr(llm,'_llm',None)
    monkeypatch.setenv('PLANBEE_RUN_ORIGIN','test')
    monkeypatch.setenv('PLANBEE_RUNS_DIR', str(tmp_path / 'runs'))
