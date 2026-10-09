"""Exercise shell input rejection and pin the no-training publication boundary."""
import os
from pathlib import Path
import re
import subprocess
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
MANUAL = ROOT/'.github/workflows/yanjaro-remote-train.yml'
CI = ROOT/'.github/workflows/remote-acoustic-tests.yml'


def load(path):
    # BaseLoader preserves GitHub's YAML 1.2 'on' key as text.
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def test_manual_workflow_has_only_safe_probe_and_explicit_artifact():
    flow = load(MANUAL)
    assert set(flow['on']) == {'workflow_dispatch'}
    assert flow['permissions'] == {'contents': 'read'}
    inputs = flow['on']['workflow_dispatch']['inputs']
    assert set(inputs) == {'mode'} and inputs['mode']['options'] == ['probe']
    assert inputs['mode']['default'] == 'probe'
    assert flow['jobs']['probe']['timeout-minutes'] == '10'
    assert 'secrets.' not in MANUAL.read_text()
    steps = flow['jobs']['probe']['steps']
    for step in steps:
        if 'uses' in step:
            assert re.fullmatch(r'actions/(checkout|setup-python|upload-artifact)@[a-f0-9]{40}', step['uses'])
        if 'run' in step:
            assert '${{' not in step['run']  # untrusted inputs only through quoted env vars
            assert not re.search(r'remote_acoustic.cli\s+(train|prepare|extract|coverage)', step['run'])
    checkout = next(s for s in steps if s.get('uses', '').startswith('actions/checkout@'))
    assert checkout['with']['persist-credentials'] == 'false'
    upload = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@'))
    assert upload['with']['path'] == 'experiments/remote-acoustic/artifacts/probe.json'
    assert 'ulimit -v 6291456' in MANUAL.read_text()
    assert 'timeout --kill-after=10s 4m python -m remote_acoustic.cli probe' in MANUAL.read_text()


@pytest.mark.parametrize('mode,ref,ok', [
    ('probe', 'refs/heads/experiment/remote-acoustic-yambda', True),
    ('train-full', 'refs/heads/experiment/remote-acoustic-yambda', False),
    ('probe', 'refs/heads/main', False),
    ('probe', 'refs/tags/experiment/remote-acoustic-yambda', False),
    ('probe; touch injected', 'refs/heads/experiment/remote-acoustic-yambda', False),
    ('$(touch injected)', 'refs/heads/experiment/remote-acoustic-yambda', False),
])
def test_dispatch_guard_rejects_invalid_or_injected_inputs(tmp_path, mode, ref, ok):
    guard = load(MANUAL)['jobs']['probe']['steps'][0]['run']
    env = dict(os.environ, MODE=mode, GITHUB_REF=ref)
    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', guard], env=env,
                            cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert result.returncode == (0 if ok else 2)
    assert not (tmp_path/'injected').exists()


def test_pr_ci_runs_all_tests_without_yambda_or_training():
    flow = load(CI)
    assert set(flow['on']) == {'pull_request'}
    assert flow['permissions'] == {'contents': 'read'}
    assert 'experiments/remote-acoustic/**' in flow['on']['pull_request']['paths']
    scripts = '\n'.join(s.get('run', '') for s in flow['jobs']['test']['steps'])
    assert 'python -m pytest -q' in scripts
    assert 'remote_acoustic.cli' not in scripts and 'synthetic_smoke' not in scripts
    assert not re.search(r'pytest.*(?:--ignore|\s-k\s|\s-m\s)', scripts)
