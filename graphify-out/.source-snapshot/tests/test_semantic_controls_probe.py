"""Keep the live evaluation honest without calling a real model in pytest."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from memory_review_support import grounded_response

from core.config import config
from providers.base_provider import ProviderResponse
from tasks import probe_semantic_controls as probe


def test_explicit_verdict_is_authoritative_and_unavailable_is_not_rejection():
    assert probe.verdict(True, 'approved') == 'correct_approval'
    assert probe.verdict(True, 'rejected') == 'false_rejection'
    assert probe.verdict(False, 'approved') == 'false_approval'
    assert probe.verdict(False, 'rejected') == 'correct_rejection'
    assert probe.verdict(False, 'unavailable') == 'unavailable'


def test_saved_sources_must_preserve_exact_question_text_date_and_uncertainty():
    originals = {'owner_episode:1': {'text': 'It may be missing.', 'question': 'Which manual?',
                                  'noted': '2026-10-21T15:00:00'}}
    saved = {'consolidation:1': {'excerpts': [{'id': 'owner_episode:1', **originals['owner_episode:1']}]}}
    assert probe.preserved(saved, originals)
    saved['consolidation:1']['excerpts'][0]['question'] = ''
    assert not probe.preserved(saved, originals)
    assert not probe.preserved({}, originals)


def test_summary_separates_missing_work_false_approvals_and_unknown_startup():
    rows = [
        {'expected_related': True, 'workflow_ok': False, 'control': 'false_rejection', 'unrelated_group_saved': False,
         'trace': {'startup': {'was_resident': False, 'wall_ms': 100}}},
        {'expected_related': False, 'workflow_ok': True, 'control': 'false_approval', 'unrelated_group_saved': False,
         'trace': {'startup': {'was_resident': True, 'wall_ms': 2}}},
        {'expected_related': False, 'workflow_ok': False, 'control': 'unavailable', 'trace': None,
         'unrelated_group_saved': True},
    ]
    result = probe.summarize(rows)
    assert result['workflow_expectations_met'] == 1
    assert result['controls']['false_approval'] == 1
    assert result['controls']['false_rejection'] == 1
    assert result['controls']['unavailable'] == 1
    assert result['unrelated_groups_saved'] == 1
    assert result['startup']['nonresident']['count'] == 1
    assert result['startup']['resident']['count'] == 1
    assert result['startup']['unknown']['count'] == 1


def test_frozen_cases_cover_both_directions_and_do_not_repeat_training_examples():
    assert len(probe.CASES) == 8
    assert sum(case['related'] for case in probe.CASES) == 4
    assert len({case['id'] for case in probe.CASES}) == 8
    assert all(len(case['sources']) == 2 for case in probe.CASES)
    assert any(question for case in probe.CASES for _, question in case['sources'])


@pytest.mark.parametrize('index', [0, 4])
def test_actual_probe_runs_generation_critique_and_separate_control(monkeypatch, index):
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    case = probe.CASES[index]
    calls = []
    async def residency():
        return {'configured_model_resident': None}
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        if 'check_items' in payload:
            result = {'checks': [{'id': 0, 'supported': case['related'], 'reason': 'Frozen synthetic judgment.'}]}
        elif case['related']:
            result = {'work_kind': 'memories', 'item': {'subject': case['subject'],
                      'evidence': ['owner_episode:1', 'owner_episode:2']}}
        else:
            result = {'work_kind': 'silence'}
        return ProviderResponse(content=json.dumps(grounded_response(args, result)), provider='ollama', model='synthetic')
    monkeypatch.setattr(probe, 'residency', residency)
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    row = asyncio.run(probe.run_case(case, index))
    assert row['workflow_ok']
    assert row['control'] == ('correct_approval' if case['related'] else 'correct_rejection')
    assert len(calls) == (5 if case['related'] else 2)
    assert row['owner_facts_created'] == 0


def test_actual_probe_reports_false_save_even_when_separate_control_rejects(monkeypatch):
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    calls = []
    async def residency():
        return {}
    async def complete(*args, **kwargs):
        calls.append(json.loads(args[1][0].content))
        if 'check_items' in calls[-1]:
            result = {'checks': [{'id': 0, 'supported': len(calls) in (2, 3), 'reason': 'Synthetic model inconsistency.'}]}
        else:
            result = {'work_kind': 'memories', 'item': {'subject': 'Wrong grouping',
                      'evidence': ['owner_episode:1', 'owner_episode:2']}}
        return ProviderResponse(content=json.dumps(grounded_response(args, result)), provider='ollama', model='synthetic')
    monkeypatch.setattr(probe, 'residency', residency)
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    row = asyncio.run(probe.run_case(probe.CASES[4], 4))
    assert row['control'] == 'correct_rejection'
    assert row['unrelated_group_saved'] and not row['workflow_ok']
    assert probe.summarize([row])['unrelated_groups_saved'] == 1


def test_runner_fails_gate_and_keeps_evidence_for_false_save(monkeypatch, tmp_path):
    async def run_case(*args):
        return {'case': 'frozen-failure', 'expected_related': False, 'workflow_ok': False,
                'control': 'correct_rejection', 'unrelated_group_saved': True, 'trace': None}
    async def close():
        pass
    monkeypatch.setattr(probe, 'run_case', run_case)
    monkeypatch.setattr(probe.runtime, 'close', close)
    monkeypatch.setattr(probe.logger, 'handlers', [])
    output = tmp_path / 'evidence.json'
    assert not asyncio.run(probe.main(SimpleNamespace(output=output, cases=1)))
    data = json.loads(output.read_text())
    assert data['finished'] and data['sources_unchanged']
    assert data['summary']['unrelated_groups_saved'] == 1


def test_fresh_corpus_loads_and_rejects_ambiguous_expectations(tmp_path):
    from pathlib import Path
    cases = probe.load_cases(Path(__file__).resolve().parents[1] / 'tasks' / 'semantic_holdout_v2.json')
    assert len(cases) == 8 and sum(case['related'] for case in cases) == 4
    assert not {case['id'] for case in cases} & {case['id'] for case in probe.CASES}
    cases[0]['related'] = 'false'
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(cases))
    with pytest.raises(ValueError):
        probe.load_cases(path)
