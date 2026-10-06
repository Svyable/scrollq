import copy
import json

import numpy as np
import pytest

from scrollq.ink_detectability import (
    DetectabilityError, digest, main, plant, preprocessing_gate,
    run_probe, stroke_mask, validate_spec, verify_bundle,
)
from scrollq.ink_audit import audit_ink_manifest


@pytest.fixture
def contract(tmp_path):
    stack = np.full((9, 48, 48), 100, dtype=np.uint8)
    face = np.full((48, 48), 4., dtype=np.float32)
    np.save(tmp_path / 'stack.npy', stack)
    np.save(tmp_path / 'face_depth.npy', face)
    spec = dict(schema_version=1, volume_root='exact-target', region_id='r1',
                orientation_source='geometry', layer_order='forward', selection_used_ink=False,
                synthetic_used_for_training=False, uses_prohibited_higher_resolution=False,
                seed=3, contrasts=[8, 32, 64], widths_px=[1, 2], reference_contrast=32,
                threshold=.5, min_lift=.05, max_off_mask_lift=.02, depth_sigma=1.)
    for key in ('stack', 'face_depth', 'surface', 'checkpoint', 'engine', 'config'):
        path = tmp_path / (key + '.npy' if key in ('stack', 'face_depth') else key)
        if not path.exists():
            path.write_text('synthetic-fixture-only')
        spec[key] = dict(path=str(path), sha256=digest(path), terms='synthetic test fixture MIT', intended_use_permitted=True)
    return spec


def responsive(stack):
    return np.clip((stack[4].astype(float) - 100) / 32, 0, 1)


def bundle(tmp_path, contract, fn=responsive):
    directory = tmp_path / 'bundle'
    report = run_probe(contract, fn, directory)
    return directory, report, digest(directory / 'spec.json')


def test_recovery_and_real_synthetic_separation(tmp_path, contract):
    directory, report, sha = bundle(tmp_path, contract)
    assert report['negative_evidence'] == 'SUPPORTED_NEGATIVE'
    verified = verify_bundle(directory, sha)
    assert verified['rows'] == report['rows']
    assert len(report['rows']) == 6
    assert np.load(directory / 'real.npy').sum() == 0
    assert np.load(directory / 'synthetic-0-1.npy').sum() > 0
    with pytest.raises(FileExistsError):
        run_probe(contract, responsive, directory)


@pytest.mark.parametrize('kind', ['blind', 'fixed-letter', 'global-response'])
def test_adversarial_detectors(tmp_path, contract, kind):
    mask = stroke_mask((48, 48), 1, contract['seed']).astype(float)
    fn = {'blind': lambda s: np.zeros(s.shape[1:]),
          'fixed-letter': lambda s: mask,
          'global-response': lambda s: np.ones(s.shape[1:]) if s.max() > 100 else np.zeros(s.shape[1:])}[kind]
    _, report, _ = bundle(tmp_path, contract, fn)
    assert report['detectability'] == 'FAIL'
    assert report['negative_evidence'] != 'SUPPORTED_NEGATIVE'


def test_nonmonotonic_curve_does_not_select_a_successful_contrast(tmp_path, contract):
    def inverted(s):
        return responsive(s) if s.max() < 130 else np.zeros(s.shape[1:])
    _, report, _ = bundle(tmp_path, contract, inverted)
    assert report['detectability'] == 'FAIL'


@pytest.mark.parametrize('field,value', [('orientation_source', 'most_ink'), ('selection_used_ink', True),
    ('synthetic_used_for_training', True), ('uses_prohibited_higher_resolution', True),
    ('min_lift', float('nan')), ('reference_contrast', 16), ('widths_px', [1])])
def test_frozen_contract_rejections(contract, field, value):
    contract[field] = value
    with pytest.raises(DetectabilityError):
        validate_spec(contract)


def test_mutating_adapter_is_rejected(tmp_path, contract):
    def mutates(s):
        from pathlib import Path
        Path(contract['checkpoint']['path']).write_text('changed')
        return responsive(s)
    with pytest.raises(DetectabilityError, match='checkpoint bytes changed'):
        run_probe(contract, mutates, tmp_path / 'bundle')


@pytest.mark.parametrize('kind', ['array', 'spec', 'verdict', 'missing'])
def test_receipt_verification(tmp_path, contract, kind):
    directory, _, sha = bundle(tmp_path, contract)
    if kind == 'array':
        np.save(directory / 'synthetic-0-1.npy', np.zeros((48, 48)))
    elif kind == 'spec':
        with (directory / 'spec.json').open('a') as f:
            f.write(' ')
    elif kind == 'missing':
        (directory / 'synthetic-0-1.npy').unlink()
    else:
        path = directory / 'report.json'
        report = json.loads(path.read_text())
        report['detectability'] = 'FAIL'
        report['negative_evidence'] = 'UNINFORMATIVE'
        path.write_text(json.dumps(report))
        assert verify_bundle(directory, sha)['negative_evidence'] == 'SUPPORTED_NEGATIVE'
        return
    with pytest.raises((DetectabilityError, OSError)):
        verify_bundle(directory, sha)


def test_face_location_and_stack_immutability():
    stack = np.full((9, 48, 48), 100, dtype=np.uint8)
    face = np.full((48, 48), 2.)
    mask = stroke_mask(face.shape, 1, 3)
    planted = plant(stack, face, mask, 32, 1)
    assert stack.max() == 100
    assert planted[2, mask].max() == 132
    assert planted[6, mask].max() == 100
    with pytest.raises(DetectabilityError):
        plant(stack, face + 20, mask, 32, 1)


def test_preprocessing_regression_even_with_better_detectability(tmp_path, contract):
    _, probe, _ = bundle(tmp_path, contract)
    truth = stroke_mask((48, 48), 1, 3)
    bad = np.ones((48, 48))
    improved = copy.deepcopy(probe)
    for row in improved['rows']:
        row['ink_lift'] = 1.
    assert preprocessing_gate(truth, truth.astype(float), bad, probe, improved)['verdict'] == 'FAIL'
    assert preprocessing_gate(truth, truth.astype(float), truth.astype(float), probe, probe)['verdict'] == 'PASS'
    improved['rows'].pop()
    with pytest.raises(DetectabilityError, match='incomplete'):
        preprocessing_gate(truth, truth.astype(float), truth.astype(float), probe, improved)


def test_negative_claim_is_mandatory_and_bound(tmp_path, contract):
    directory, _, sha = bundle(tmp_path, contract)
    manifest = dict(volume_root='exact-target', model=dict(checkpoint='fixture', checkpoint_sha256=contract['checkpoint']['sha256']),
        evaluation_regions=[dict(id='r1', volume_root='exact-target', bbox_zyx_half_open=[[0,0,0],[9,48,48]], split='test')],
        negative_ink_claims=[dict(bundle_dir=str(directory), spec_sha256=sha, receipt_sha256=digest(directory / "report.json"), prediction_sha256=digest(directory / "real.npy"), evaluation_region_id='r1', surface_sha256=contract['surface']['sha256'])])
    assert audit_ink_manifest(manifest)['negative_evidence'][0]['status'] == 'SUPPORTED_NEGATIVE'
    manifest['negative_ink_claims'][0]['surface_sha256'] = '0' * 64
    assert audit_ink_manifest(manifest)['status'] == 'fail'
    manifest['negative_ink_claims'] = [{}]
    assert audit_ink_manifest(manifest)['negative_evidence'][0]['status'] == 'UNINFORMATIVE'


def test_cli_preserves_exact_preregistered_spec_bytes(tmp_path, contract):
    from pathlib import Path
    engine = Path(contract['engine']['path'])
    engine.write_text('import sys,numpy as np\ns=np.load(sys.argv[1]);np.save(sys.argv[2],np.clip((s[4].astype(float)-100)/32,0,1))\n')
    contract['engine']['sha256'] = digest(engine)
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps(contract))
    out = tmp_path / 'cli-bundle'
    assert main(['--spec', str(spec), '--spec-sha256', digest(spec), '--out', str(out)]) == 0
    assert digest(out / 'spec.json') == digest(spec)
    assert main(['--verify', str(out), '--spec-sha256', digest(spec)]) == 0


@pytest.mark.parametrize('operation', ['smoothing', 'bright-sheet-tightening', 'brightest-layer-recentering'])
def test_adversarial_preprocessing_fixture(tmp_path, contract, operation):
    from scipy.ndimage import gaussian_filter
    _, probe, _ = bundle(tmp_path, contract)
    truth = stroke_mask((48, 48), 1, 3)
    before = truth.astype(float)
    # Numerical adverse fixtures, not measurements of physical scroll preprocessing.
    after = (gaussian_filter(before, 2.) if operation == 'smoothing' else
             np.roll(before, 2 if operation == 'bright-sheet-tightening' else 4, axis=0))
    assert preprocessing_gate(truth, before, after, probe, probe)['verdict'] == 'FAIL'


@pytest.mark.parametrize('value', [float('nan'), -1., 2.])
def test_invalid_inference_values_fail_closed(tmp_path, contract, value):
    with pytest.raises(DetectabilityError, match='probability'):
        run_probe(contract, lambda s: np.full(s.shape[1:], value), tmp_path / 'bad')


def test_one_width_failure_cannot_be_dropped(tmp_path, contract):
    def fine_only(s):
        from scipy.ndimage import binary_erosion
        mask = s[4] > 110
        # Responsive for fine strokes; blind when the thicker family produces solid interiors.
        return np.zeros(mask.shape) if binary_erosion(mask).any() else responsive(s)
    _, report, _ = bundle(tmp_path, contract, fine_only)
    assert any(r['passed'] for r in report['rows'] if r['contrast'] == 32)
    assert report['detectability'] == 'FAIL'



def test_stochastic_inference_cannot_masquerade_as_recovery(tmp_path, contract):
    calls = []
    def drifting(s):
        calls.append(1)
        return np.full(s.shape[1:], len(calls) * .1)
    with pytest.raises(DetectabilityError, match="not deterministic"):
        run_probe(contract, drifting, tmp_path / "drifting")


def test_callback_cannot_retune_caller_spec(tmp_path, contract):
    def retunes(s):
        contract["min_lift"] = 0.000001
        contract["reference_contrast"] = 8
        return responsive(s)
    directory, report, sha = bundle(tmp_path, contract, retunes)
    assert report["rule"]["reference_contrast"] == 32
    assert report["rule"]["min_lift"] == .05
    assert verify_bundle(directory, sha)["negative_evidence"] == "SUPPORTED_NEGATIVE"


def test_preprocessing_ignores_forged_producer_verdict(tmp_path, contract):
    _, probe, _ = bundle(tmp_path, contract)
    truth = stroke_mask((48, 48), 1, 3)
    forged = copy.deepcopy(probe)
    for row in forged["rows"]:
        row["ink_lift"] = 0.
        row["passed"] = True
    forged["detectability"] = "PASS"
    assert preprocessing_gate(truth, truth.astype(float), truth.astype(float), forged, forged)["verdict"] == "FAIL"


def test_explicit_absence_requires_probe_evidence():
    result = audit_ink_manifest({"absence_of_ink_claimed": True})
    assert any("requires negative_ink_claims" in error for error in result["errors"])


def test_streaming_digest_matches_exact_bytes(tmp_path):
    import hashlib
    data = b"0123456789" * 300000
    path = tmp_path / "large"
    path.write_bytes(data)
    assert digest(path) == hashlib.sha256(data).hexdigest()



def test_empty_preprocessing_rule_cannot_pass():
    truth = np.array([[True, False]])
    forged = {"rule": {"contrasts": [], "widths_px": [], "threshold": .5}, "rows": [], "detectability": "PASS"}
    with pytest.raises(DetectabilityError):
        preprocessing_gate(truth, truth.astype(float), truth.astype(float), forged, forged)
