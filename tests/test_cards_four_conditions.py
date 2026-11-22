"""Integration check: information and authority have separate observable effects."""
import evaluate_cards

def test_four_conditions_keep_safety_and_separate_confirmation_from_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate_cards,'OUT',tmp_path)
    rows=evaluate_cards.run()
    assert len(rows)==4
    for row in rows:
        assert row['metrics']['overload']==0
        assert row['metrics']['past_deadline']==0
        assert 'Sol' in row['state']['resolved'][0]['body']
    none,objective,authority,both=[r['metrics'] for r in rows]
    # The extra fairness split misses the original handoff deadline and is now
    # blocked before requesting consent; only the agreed deadline repair counts.
    assert none['confirms']==objective['confirms']==2
    assert authority['confirms']==both['confirms']==1
    assert none['hive_rejects']==authority['hive_rejects']==1
    assert objective['hive_rejects']==both['hive_rejects']==0
    assert len(list(tmp_path.glob('*.md')))==5
