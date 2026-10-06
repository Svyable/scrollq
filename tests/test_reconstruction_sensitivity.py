import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from scrollq import reconstruction_sensitivity as rs
from scrollq.reconstruction_sensitivity import (
    ReconstructionSensitivityError, assess, channel_change, classify_license, evaluate, main,
    positive_control, validate_spec,
)


def raw_spec():
    return rs._control_spec(rs.CONTROL_ROWS)


def planted(seed=rs.CONTROL_SEED):
    return rs._control_arrays(seed, plant=True)


def run(spec_doc=None, data=None, masks=None):
    spec = validate_spec(spec_doc or raw_spec())
    if data is None:
        data, masks = planted()
    return spec, data, masks, assess(spec, data, masks)


def classes(result):
    out = {}
    for component in result["components"]:
        centre = component["centroid_uv"]
        name = min(rs.CONTROL_COMPONENTS, key=lambda n: (rs.CONTROL_COMPONENTS[n][0][0] - centre[0]) ** 2
                   + (rs.CONTROL_COMPONENTS[n][0][1] - centre[1]) ** 2)
        out[name] = component
    return out


# ----------------------------------------------------------------------------- planted outcomes


def test_planted_outcomes_are_recovered_for_the_right_reasons():
    _, _, _, result = run()
    found = classes(result)
    assert {n: c["evidence_class"] for n, c in found.items()} == {
        "G": "reconstruction_stable", "H": "reconstruction_stable", "A": "reconstruction_sensitive",
        "B": "reconstruction_sensitive", "C": "reconstruction_sensitive", "E": "reconstruction_sensitive"}
    assert found["B"]["reasons"] == ["reconstruction:absent-in:tik_strong"]
    assert found["C"]["reasons"] == ["reconstruction:absent-in:lsqr"]
    assert found["E"]["reasons"] == ["reconstruction:normal_displacement-exceeds-tolerance-in:tik_weak"]
    assert found["A"]["reasons"] == ["calibration:absent-in:cor_plus"]
    assert found["A"]["arms"]["reconstruction"]["status"] == "stable"  # only calibration exposed it
    assert result["summary"] == {"reconstruction_stable": 2, "reconstruction_sensitive": 4,
                                 "unverified": 0, "reference_components": 6, "variant_only": 2}
    only = {(v["variant_id"], v["touches_negative_region"]) for v in result["variant_only_components"]}
    assert only == {("lsqr", False), ("tik_strong", True)}


def test_geometry_alone_makes_a_component_sensitive_and_ink_alone_does_not():
    spec, data, masks, _ = run()
    for vid in data:  # no planted geometry at all
        data[vid]["surface_xyz"] = data["official"]["surface_xyz"].copy()
        data[vid]["neighbor_xyz"] = data["official"]["neighbor_xyz"].copy()
    found = classes(assess(spec, data, masks))
    assert found["E"]["evidence_class"] == "reconstruction_stable"


def test_stable_is_never_reported_for_a_family_that_did_not_vary():
    spec, data, masks, _ = run()
    ok = {k: v.copy() for k, v in data["official"].items()}
    noop_data = {vid: {k: v.copy() for k, v in ok.items()} for vid in data}
    result = assess(spec, noop_data, masks)
    assert result["summary"]["reconstruction_stable"] == 0
    record = result["arms"]["reconstruction"]["variant_records"][0]
    assert record["effective"] is False
    assert "ink-prediction-bitwise-identical-to-baseline" in record["not_varied_reasons"]
    document = raw_spec()
    for row in document["variants"]:
        row["fingerprint"]["volume_sha256"] = hashlib.sha256(b"same").hexdigest()
    spec2 = validate_spec(document)
    data2, masks2 = planted()
    record = assess(spec2, data2, masks2)["arms"]["reconstruction"]["variant_records"][0]
    assert record["not_varied_reasons"] == ["volume-identical-to-baseline"]


def test_null_family_is_all_stable_with_nothing_manufactured():
    spec = validate_spec(raw_spec())
    data, masks = rs._control_arrays(rs.CONTROL_SEED + 5, plant=False)
    result = assess(spec, data, masks)
    assert result["summary"]["reconstruction_stable"] == len(rs.CONTROL_COMPONENTS)
    assert result["summary"]["variant_only"] == 0


def test_failed_variant_is_listed_and_neither_hides_nor_certifies():
    document = raw_spec()
    failing = next(v for v in document["variants"] if v["id"] == "tik_strong")
    failing.update(outcome="failed", failure_reason="LSQR did not converge", data=None)
    spec = validate_spec(document)
    data, masks = planted()
    del data["tik_strong"]
    result = assess(spec, data, masks)
    found = classes(result)
    assert result["failed_variants"] == ["tik_strong"]
    # B vanished only under the failed variant: no sensitivity is observed, but nothing is certified
    assert found["B"]["evidence_class"] == "unverified"
    assert found["G"]["evidence_class"] == "unverified"
    assert "reconstruction:failed-variants:tik_strong" in found["G"]["reasons"]
    assert found["C"]["evidence_class"] == "reconstruction_sensitive"  # measured sensitivity survives


def test_failed_calibration_baseline_makes_the_arm_unverified():
    document = raw_spec()
    lsqr = next(v for v in document["variants"] if v["id"] == "lsqr")
    lsqr.update(outcome="failed", failure_reason="out of memory", data=None)
    spec = validate_spec(document)
    data, masks = planted()
    del data["lsqr"], data["cor_plus"], data["cor_minus"]
    document_data = {k: v for k, v in data.items()}
    document2 = copy.deepcopy(document)
    for row in document2["variants"]:
        if row["id"] in ("cor_plus", "cor_minus"):
            row.update(outcome="failed", failure_reason="baseline failed", data=None)
    result = assess(validate_spec(document2), document_data, masks)
    found = classes(result)
    assert found["G"]["evidence_class"] == "unverified"
    assert found["G"]["arms"]["calibration"]["reasons"] == ["arm-baseline-failed"]


def test_minimum_variant_counts_are_enforced():
    document = raw_spec()
    document["rules"]["min_reconstruction_variants"] = 4
    _, _, _, result = run(document)
    assert classes(result)["G"]["evidence_class"] == "unverified"
    assert "reconstruction:fewer-than-4-effective-variants" in classes(result)["G"]["reasons"]


def test_required_channels_must_be_measured_for_stable():
    spec, data, masks, _ = run()
    del data["tik_weak"]["fiber_angle"]
    found = classes(assess(spec, data, masks))
    assert found["G"]["evidence_class"] == "unverified"
    assert "reconstruction:required-channel-not-measured:fiber_angle:tik_weak" in found["G"]["reasons"]
    document = raw_spec()
    document["rules"]["required_channels"] = ["surface_xyz"]
    spec = validate_spec(document)
    assert classes(assess(spec, data, masks))["G"]["evidence_class"] == "reconstruction_stable"


def test_calibration_arm_optional_only_when_not_required():
    document = raw_spec()
    document["variants"] = [v for v in document["variants"] if v["kind"] != "calibration_perturbation"]
    with pytest.raises(ReconstructionSensitivityError, match="requires a calibration arm"):
        validate_spec(document)
    document["rules"]["require_calibration_arm"] = False
    spec = validate_spec(document)
    data, masks = planted()
    result = assess(spec, data, masks)
    assert result["arms"]["calibration"]["status"] == "not_run"
    assert classes(result)["G"]["evidence_class"] == "reconstruction_stable"
    assert classes(result)["G"]["arms"]["calibration"] == {"status": "not_run"}


def test_calibration_arm_with_the_official_reference_as_baseline_is_identity_mapped():
    document = raw_spec()
    for row in document["variants"]:
        if row["kind"] == "calibration_perturbation":
            row["baseline"] = "official"
            row["algorithm"] = copy.deepcopy(document["variants"][0]["algorithm"])
            row["software"] = copy.deepcopy(document["variants"][0]["software"])
    spec = validate_spec(document)
    data, masks = planted()
    result = assess(spec, data, masks)
    assert result["arms"]["calibration"]["baseline"] == "official"
    assert classes(result)["A"]["arms"]["calibration"]["baseline_component"] == classes(result)["A"]["component_id"]


# ----------------------------------------------------------------------------- matching & thresholds


def make_pair(shift=0, radius=6, extra_cells=0):
    shape = (80, 80)
    spec = validate_spec(raw_spec())
    data, masks = rs._control_arrays(rs.CONTROL_SEED + 9, plant=False)
    centre = rs.CONTROL_COMPONENTS["G"][0]
    for vid in data:
        field = np.clip(data[vid]["ink"], 0, 0.2)
        field[rs._disc(shape, (centre[0], centre[1] + (shift if vid == "tik_weak" else 0)), radius)] = 0.9
        data[vid]["ink"] = field
    return spec, data, masks


def test_match_iou_boundary_and_component_extraction_rules():
    shape = (80, 80)
    base = np.zeros(shape, bool)
    base[10:20, 10:20] = True            # 100 cells
    moved = np.zeros(shape, bool)
    moved[10:20, 13:23] = True           # 70 shared, IoU 70/130
    labels_a, n_a = rs.connected_components(base)
    labels_b, n_b = rs.connected_components(moved)
    iou = rs._iou(labels_a, n_a, labels_b, n_b)
    assert iou[0, 0] == pytest.approx(70 / 130)
    rules = validate_spec(raw_spec())["rules"]
    ink = np.full(shape, 0.1)
    ink[10:12, 10:12] = 0.9               # 4 cells < min_component_cells
    ink[30:40, 30:40] = 0.49              # below the ink threshold
    ink[50:60, 50:60] = 0.5               # exactly at the threshold counts
    valid = np.ones(shape, bool)
    valid[50:55, :] = False               # masked rows are not ink
    labels, info = rs._components(ink, valid, rules)
    assert [i["area_cells"] for i in info] == [50]
    # diagonal neighbours form one component (8-connectivity)
    diagonal = np.full(shape, 0.1)
    for k in range(15):
        diagonal[20 + k, 20 + k] = 0.9
    assert len(rs._components(diagonal, valid, rules)[1]) == 1


def test_small_shift_keeps_a_match_and_a_large_shift_loses_it():
    spec, data, masks = make_pair(shift=1)
    entry = classes(assess(spec, data, masks))["G"]
    assert entry["evidence_class"] == "reconstruction_stable"
    spec, data, masks = make_pair(shift=8)
    entry = classes(assess(spec, data, masks))["G"]
    assert entry["evidence_class"] == "reconstruction_sensitive"
    assert "reconstruction:absent-in:tik_weak" in entry["reasons"]


def square_family(variant_half=False):
    """Every variant shows one 10x10 square; ``tik_weak`` optionally keeps only its left half."""
    spec = validate_spec(raw_spec())
    data, masks = rs._control_arrays(rs.CONTROL_SEED + 11, plant=False)
    for vid in data:
        field = np.clip(data[vid]["ink"], 0, 0.2)
        field[10:20, 10:20 if not (variant_half and vid == "tik_weak") else 15] = 0.9
        data[vid]["ink"] = field
    return spec, data, masks


def test_iou_exactly_at_the_threshold_still_counts_as_present():
    spec, data, masks = square_family(variant_half=True)   # IoU = 50 / 100 = 0.5 exactly
    assert spec["rules"]["match_iou"] == 0.5
    result = assess(spec, data, masks)
    record = next(r for r in result["arms"]["reconstruction"]["variant_records"] if r["variant_id"] == "tik_weak")
    entry = record["components"]["c001"]
    assert entry["best_iou"] == 0.5 and entry["present"] is True
    assert result["components"][0]["evidence_class"] == "reconstruction_stable"
    spec["rules"]["match_iou"] = 0.51
    assert classes_of_single(assess(spec, data, masks))["evidence_class"] == "reconstruction_sensitive"


def classes_of_single(result):
    assert len(result["components"]) == 1
    return result["components"][0]


def test_one_no_op_variant_blocks_stable_even_when_the_minimum_is_still_met():
    document = raw_spec()
    extra = copy.deepcopy(variant(document, "tik_weak"))
    extra.update(id="tik_mid")
    extra["algorithm"]["parameters"]["regularisation_strength"] = 0.1
    extra["fingerprint"]["volume_sha256"] = variant(document, "official")["fingerprint"]["volume_sha256"]
    extra["data"] = "tik_mid.npz"
    document["variants"].append(extra)
    spec = validate_spec(document)
    data, masks = planted()
    data["tik_mid"] = {k: v.copy() for k, v in data["official"].items()}   # 4 declared, 3 effective >= min 3
    found = classes(assess(spec, data, masks))
    assert found["G"]["evidence_class"] == "unverified"
    assert "reconstruction:not-varied:tik_mid" in found["G"]["reasons"]


def test_calibration_status_follows_the_matched_baseline_component_not_its_label():
    spec, data, masks, _ = run()
    footprint_g = rs._disc((80, 80), *rs.CONTROL_COMPONENTS["G"])
    footprint_a = rs._disc((80, 80), *rs.CONTROL_COMPONENTS["A"])
    for vid in ("lsqr", "cor_plus", "cor_minus"):      # the baseline lacks G, which shifts its labels
        data[vid]["ink"] = np.where(footprint_g, 0.05, data[vid]["ink"])
    data["cor_plus"]["ink"] = np.where(footprint_a, 0.05, data["cor_plus"]["ink"])   # A already absent there
    found = classes(assess(spec, data, masks))
    assert found["G"]["arms"]["calibration"]["status"] == "not_applicable"
    assert found["A"]["arms"]["calibration"]["status"] == "sensitive"
    assert found["A"]["arms"]["calibration"]["baseline_component"] != found["A"]["component_id"]
    assert found["A"]["evidence_class"] == "reconstruction_sensitive"
    assert found["H"]["arms"]["calibration"]["status"] == "stable"


def test_measured_sensitivity_survives_an_incomplete_other_arm():
    document = raw_spec()
    variant(document, "cor_minus").update(outcome="failed", failure_reason="did not converge", data=None)
    spec = validate_spec(document)
    data, masks = planted()
    del data["cor_minus"]
    found = classes(assess(spec, data, masks))
    assert found["B"]["evidence_class"] == "reconstruction_sensitive"      # absent under strong regularisation
    assert found["B"]["arms"]["calibration"]["status"] == "unverified"
    assert found["G"]["evidence_class"] == "unverified"


# ----------------------------------------------------------------------------- channel math


def tilted_surface():
    rows, cols = np.mgrid[:40, :40].astype(float)
    return np.stack([0.5 * cols + 100.0, rows, cols], axis=-1)   # plane tilted about the row axis


def test_normal_displacement_is_measured_along_the_base_normal():
    base = {"surface_xyz": tilted_surface()}
    normal = np.array([-1.0, 0.0, 0.5])
    normal /= np.linalg.norm(normal)
    along = {"surface_xyz": base["surface_xyz"] + 1.5 * normal}
    change, ok = channel_change("normal_displacement", base, along)
    assert ok.all() and np.allclose(change, 1.5)
    tangent = np.array([0.0, 1.0, 0.0])
    sliding = {"surface_xyz": base["surface_xyz"] + 2.0 * tangent}
    assert np.allclose(channel_change("normal_displacement", base, sliding)[0], 0.0)
    flipped = {"surface_xyz": base["surface_xyz"] - 1.5 * normal}
    assert np.allclose(channel_change("normal_displacement", base, flipped)[0], -1.5)
    degenerate = {"surface_xyz": np.zeros((40, 40, 3))}
    assert not channel_change("normal_displacement", degenerate, degenerate)[1].any()


def test_fibre_orientation_is_modulo_pi_in_degrees():
    base = {"fiber_angle": np.full((8, 8), 0.05)}
    other = {"fiber_angle": np.full((8, 8), math.pi - 0.05)}
    change, _ = channel_change("fiber_orientation", base, other)
    assert np.allclose(np.abs(change), math.degrees(0.1))
    assert np.allclose(channel_change("fiber_orientation", base, {"fiber_angle": base["fiber_angle"] + math.pi})[0], 0.0,
                       atol=1e-9)


def test_neighbour_separation_and_ink_depth_changes():
    sheet = tilted_surface()
    base = {"surface_xyz": sheet, "neighbor_xyz": sheet + [6.0, 0, 0], "ink_depth_offset": np.full((40, 40), 1.0)}
    other = {"surface_xyz": sheet, "neighbor_xyz": sheet + [7.5, 0, 0], "ink_depth_offset": np.full((40, 40), 2.25)}
    assert np.allclose(channel_change("neighbor_separation", base, other)[0], 1.5)
    assert np.allclose(channel_change("ink_depth_offset", base, other)[0], 1.25)
    assert channel_change("fiber_orientation", base, other) is None  # channel absent => not measured


def test_geometry_tolerance_boundary_is_strict():
    def exceeds(displacement):
        spec, data, masks, _ = run()
        footprint = rs._disc((80, 80), *rs.CONTROL_COMPONENTS["G"])
        data["tik_weak"]["surface_xyz"] = data["official"]["surface_xyz"].copy()
        data["tik_weak"]["neighbor_xyz"] = data["official"]["neighbor_xyz"].copy()
        data["tik_weak"]["surface_xyz"][footprint, 0] += displacement   # +z is -normal; magnitude is what counts
        found = classes(assess(spec, data, masks))["G"]["arms"]["reconstruction"]
        return found["status"] == "sensitive"
    assert not exceeds(1.0)    # exactly the frozen tolerance is not an exceedance
    assert exceeds(1.05)


# ----------------------------------------------------------------------------- negatives and manufacture


def test_negative_region_flags_extra_components_and_respects_the_tolerance():
    document = raw_spec()
    _, _, _, result = run(document)
    record = next(r for r in result["arms"]["reconstruction"]["variant_records"] if r["variant_id"] == "tik_strong")
    assert record["negative_region"]["extra_components"] == 1
    assert record["negative_region"]["manufactures_negative_components"] is True
    document["rules"]["negative_component_tolerance"] = 1
    _, _, _, relaxed = run(document)
    record = next(r for r in relaxed["arms"]["reconstruction"]["variant_records"] if r["variant_id"] == "tik_strong")
    assert record["negative_region"]["manufactures_negative_components"] is False


def test_no_negative_cells_is_not_measured_rather_than_clean():
    spec, data, masks, _ = run()
    masks = {**masks, "negative": np.zeros_like(masks["negative"])}
    result = assess(spec, data, masks)
    record = result["arms"]["reconstruction"]["variant_records"][0]
    assert record["negative_region"]["status"] == "not_measured"


def test_assess_is_deterministic_and_strict_json():
    spec, data, masks, first = run()
    assert first == assess(spec, data, masks)
    json.dumps(first, allow_nan=False)


# ----------------------------------------------------------------------------- spec validation


def mutate(mutator):
    document = raw_spec()
    mutator(document)
    return document


def variant(document, vid):
    return next(v for v in document["variants"] if v["id"] == vid)


@pytest.mark.parametrize("name, mutator, message", [
    ("ink selected", lambda d: variant(d, "lsqr")["selection"].update(ink_used_in_selection=True), "ink must not"),
    ("ink flag missing", lambda d: variant(d, "lsqr")["selection"].pop("ink_used_in_selection"), "ink must not"),
    ("after ink", lambda d: variant(d, "lsqr")["selection"].update(selected_before_ink_inference=False),
     "before ink inference"),
    ("no selection", lambda d: variant(d, "lsqr").pop("selection"), "selection"),
    ("selection criteria empty", lambda d: variant(d, "lsqr")["selection"].update(criteria=[]), "criteria"),
    ("schema", lambda d: d.update(schema="x"), "schema"),
    ("duplicate id", lambda d: variant(d, "lsqr").update(id="official"), "duplicate"),
    ("two references", lambda d: variant(d, "lsqr").update(
        role="reference", kind="official", dependencies=None, baseline=None, selection=None),
     "exactly one reference"),
    ("reference failed", lambda d: variant(d, "official").update(outcome="failed", failure_reason="x", data=None),
     "exactly one reference"),
    ("reference dependencies", lambda d: variant(d, "official").update(
        dependencies={"manifest_sha256": "0" * 64, "complete_transitive": True, "packages": []}), "null"),
    ("projections differ", lambda d: variant(d, "lsqr")["fingerprint"].update(projections_sha256="1" * 64),
     "projections"),
    ("pipeline differs", lambda d: variant(d, "tik_weak")["fingerprint"].update(pipeline_sha256="1" * 64), "pipeline"),
    ("preprocessing differs", lambda d: variant(d, "tik_weak")["fingerprint"].update(preprocessing_sha256="1" * 64),
     "preprocessing"),
    ("convention differs", lambda d: variant(d, "tik_weak")["fingerprint"].update(coordinate_convention="cw"),
     "coordinate_convention"),
    ("geometry differs in reconstruction arm", lambda d: variant(d, "lsqr")["fingerprint"].update(
        geometry_sha256="2" * 64), "calibration perturbation"),
    ("perturbation too large", lambda d: variant(d, "cor_plus")["perturbation"].update(value=1.01), "plausible bound"),
    ("perturbation zero", lambda d: variant(d, "cor_plus")["perturbation"].update(value=0), "nonzero"),
    ("unbounded parameter", lambda d: variant(d, "cor_plus")["perturbation"].update(parameter="tilt_deg"),
     "no preregistered"),
    ("perturbation not declared", lambda d: variant(d, "cor_plus").pop("perturbation"), "perturbation"),
    ("calibration algorithm differs", lambda d: variant(d, "cor_plus")["algorithm"]["parameters"].update(iterations=3),
     "only by the declared perturbation"),
    ("calibration geometry unchanged", lambda d: variant(d, "cor_plus")["fingerprint"].update(
        geometry_sha256=raw_spec()["family"]["geometry_sha256"]), "no perturbation was applied"),
    ("calibration baselines differ", lambda d: variant(d, "cor_minus").update(baseline="official"), "baseline"),
    ("baseline missing", lambda d: variant(d, "lsqr").update(baseline="nowhere"), "baseline"),
    ("self baseline", lambda d: variant(d, "lsqr").update(baseline="lsqr"), "baseline"),
    ("reconstruction not vs official", lambda d: variant(d, "tik_weak").update(baseline="lsqr"), "official reference"),
    ("tikhonov without strength", lambda d: variant(d, "tik_weak")["algorithm"]["parameters"].clear(),
     "regularisation_strength"),
    ("duplicate declaration", lambda d: variant(d, "tik_strong")["algorithm"]["parameters"].update(
        regularisation_strength=0.01), "duplicates"),
    ("dependencies missing", lambda d: variant(d, "lsqr").pop("dependencies"), "dependencies"),
    ("no packages", lambda d: variant(d, "lsqr")["dependencies"].update(packages=[]), "transitive packages"),
    ("duplicate package", lambda d: variant(d, "lsqr")["dependencies"]["packages"].append(
        {"name": "cil", "version": "26.0.0", "license": "Apache-2.0"}), "twice"),
    ("bad manifest hash", lambda d: variant(d, "lsqr")["dependencies"].update(manifest_sha256="zz"), "64-hex"),
    ("tolerance keys", lambda d: d["rules"]["tolerances"].pop("fiber_angle_degrees"), "tolerances"),
    ("negative tolerance", lambda d: d["rules"]["tolerances"].update(fiber_angle_degrees=0), "fiber_angle_degrees"),
    ("channel unknown", lambda d: d["rules"].update(required_channels=["fibre_angle"]), "required_channels"),
    ("threshold", lambda d: d["rules"].update(ink_threshold=1.5), "ink_threshold"),
    ("match iou", lambda d: d["rules"].update(match_iou=0), "match_iou"),
    ("grid", lambda d: d["grid"].update(shape=[4, 80]), "grid"),
    ("roi space", lambda d: d["roi"].update(coordinate_space="mm"), "roi"),
    ("roi order", lambda d: d["roi"].update(start=[9, 0, 0]), "start < stop"),
    ("failed without reason", lambda d: variant(d, "lsqr").update(outcome="failed", data=None), "failure_reason"),
    ("bool count", lambda d: d["rules"].update(min_component_cells=True), "min_component_cells"),
])
def test_spec_fails_closed(name, mutator, message):
    with pytest.raises(ReconstructionSensitivityError, match=message):
        validate_spec(mutate(mutator))


def test_perturbation_exactly_at_the_bound_is_allowed():
    document = raw_spec()
    variant(document, "cor_plus")["perturbation"]["value"] = 1.0
    assert validate_spec(document)["variants"][4]["perturbation"]["value"] == 1.0


# ----------------------------------------------------------------------------- licences


@pytest.mark.parametrize("expression, expected", [
    ("Apache-2.0", "permissive"), ("MIT", "permissive"), ("BSD-3-Clause", "permissive"),
    ("GPL-3.0-only", "copyleft"), ("GPL-3.0-or-later", "copyleft"), ("AGPL-3.0", "copyleft"),
    ("LGPL-2.1-or-later", "weak_copyleft"), ("MPL-2.0", "weak_copyleft"),
    ("MIT OR GPL-3.0-only", "permissive"), ("MIT AND GPL-3.0-only", "copyleft"),
    ("Apache-2.0 AND LGPL-2.1", "weak_copyleft"), ("(MIT OR Apache-2.0)", "unknown"),
    ("Proprietary", "unknown"), ("", "unknown"), (None, "unknown"), (3, "unknown"),
])
def test_license_classification_is_conservative(expression, expected):
    assert classify_license(expression) == expected


def test_license_audit_records_the_copyleft_backend_not_the_framework_licence():
    audit = validate_spec(raw_spec())["license_audit"]
    assert audit["overall"] == "copyleft_present"
    for entry in audit["variants"].values():
        assert entry["copyleft_packages"] == ["astra-toolbox 2.x (GPL-3.0-only)"]
        assert entry["status"] == "copyleft_present"
    assert "official" not in audit["variants"]
    assert "not inferred" in audit["note"]


def test_license_overall_status_ordering():
    def audit_with(license_name, complete=True):
        document = raw_spec()
        for row in document["variants"]:
            if row.get("dependencies"):
                row["dependencies"]["packages"] = [{"name": "cil", "version": "26.0.0", "license": "Apache-2.0"},
                                                   {"name": "other", "version": "1", "license": license_name}]
                row["dependencies"]["complete_transitive"] = complete
        return validate_spec(document)["license_audit"]["overall"]
    assert audit_with("MIT") == "permissive_only"
    assert audit_with("LGPL-3.0") == "weak_copyleft_present"
    assert audit_with("Custom-EULA") == "unknown_present"
    assert audit_with(None) == "unknown_present"
    assert audit_with("GPL-3.0-only") == "copyleft_present"
    assert audit_with("MIT", complete=False) == "incomplete_manifest"
    assert rs._overall_license([]) == "not_applicable"


# ----------------------------------------------------------------------------- controls


def test_positive_control_fires_and_fails_closed_under_mutations(monkeypatch):
    control = positive_control()
    assert control["fired"] is True and control["classes"]["G"] == "reconstruction_stable"
    real = rs._assess_variant

    def leaks_everything(variant, base_variant, data, comps, masks, rules):
        record = real(variant, base_variant, data, comps, masks, rules)
        for entry in record["components"].values():
            entry["present"] = True
        return record

    monkeypatch.setattr(rs, "_assess_variant", leaks_everything)  # nothing is ever sensitive
    assert positive_control()["fired"] is False

    def never_effective(variant, base_variant, data, comps, masks, rules):
        record = real(variant, base_variant, data, comps, masks, rules)
        record["effective"] = False
        return record

    monkeypatch.setattr(rs, "_assess_variant", never_effective)  # nothing is ever stable
    assert positive_control()["fired"] is False


def test_self_test_passes_and_reports_each_check():
    result = rs.self_test()
    assert result["passed"] is True
    assert all(result["checks"].values()) and len(result["checks"]) == 7


# ----------------------------------------------------------------------------- evaluate / CLI


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "positive_control", lambda: {"fired": True, "synthetic": "stub"})
    document = raw_spec()
    data, masks = planted()
    for vid, arrays in data.items():
        np.savez(tmp_path / f"{vid}.npz", **arrays)
    np.savez(tmp_path / "masks.npz", **masks)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(document))
    return tmp_path, document, path


def test_evaluate_end_to_end(workspace):
    root, document, path = workspace
    report = evaluate(path)
    assert report["status"] == "measured" and report["promotional"] is False
    assert report["summary"]["reconstruction_sensitive"] == 4
    assert set(report["sha256"]) == {"spec", "masks", *[v["id"] for v in document["variants"]]}
    assert report["license_audit"]["overall"] == "copyleft_present"
    assert "stable is not prize-grade" in report["claim"]
    json.dumps(report, allow_nan=False)


def test_unfired_control_withholds_every_verdict(workspace, monkeypatch):
    _, _, path = workspace
    monkeypatch.setattr(rs, "positive_control", lambda: {"fired": False})
    report = evaluate(path)
    assert report["status"] == "unverified"
    assert "components" not in report and "summary" not in report


@pytest.mark.parametrize("mutation", [
    "unknown_array", "missing_ink", "bad_shape", "nan", "ink_range", "int_dtype", "missing_mask_key",
    "negative_outside_valid", "empty_valid", "mask_dtype", "path_escape", "missing_file", "pickle",
])
def test_evaluate_refuses_bad_inputs(workspace, mutation):
    root, document, path = workspace
    arrays = {k: v for k, v in np.load(root / "lsqr.npz").items()}
    masks = {k: v for k, v in np.load(root / "masks.npz").items()}
    if mutation == "unknown_array":
        arrays["fibre_angle"] = arrays["fiber_angle"]
    elif mutation == "missing_ink":
        del arrays["ink"]
    elif mutation == "bad_shape":
        arrays["ink"] = arrays["ink"][:70]
    elif mutation == "nan":
        arrays["surface_xyz"][0, 0, 0] = np.nan
    elif mutation == "ink_range":
        arrays["ink"] = arrays["ink"] + 1.0
    elif mutation == "int_dtype":
        arrays["fiber_angle"] = arrays["fiber_angle"].astype(int)
    elif mutation == "missing_mask_key":
        del masks["negative"]
    elif mutation == "negative_outside_valid":
        masks["valid"][masks["negative"]] = False
    elif mutation == "empty_valid":
        masks["valid"][:] = False
        masks["negative"][:] = False
    elif mutation == "mask_dtype":
        masks["negative"] = masks["negative"].astype(int)
    elif mutation == "path_escape":
        document["masks"] = "../masks.npz"
    elif mutation == "missing_file":
        (root / "lsqr.npz").unlink()
    if mutation == "pickle":
        np.save(root / "lsqr.npz.npy", np.array([{"a": 1}], dtype=object), allow_pickle=True)
        (root / "lsqr.npz").unlink()
        (root / "lsqr.npz.npy").rename(root / "lsqr.npz")
    elif mutation != "missing_file":
        np.savez(root / "lsqr.npz", **arrays)
    np.savez(root / "masks.npz", **masks)
    path.write_text(json.dumps(document))
    with pytest.raises((ReconstructionSensitivityError, OSError, ValueError)):
        evaluate(path)


def test_cli_help_self_test_and_create_only(workspace, capsys, monkeypatch):
    root, _, path = workspace
    for argv in (["--help"], ["evaluate", "--help"], ["self-test", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 0
    assert main(["evaluate", "--spec", str(path), "--out", str(root / "report.json")]) == 0
    assert "2 stable, 4 sensitive, 0 unverified of 6 reference components; 2 variant-only" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", "--spec", str(path), "--out", str(root / "report.json")])
    assert exc.value.code == 2
    bad = root / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", "--spec", str(bad), "--out", str(root / "bad-report.json")])
    assert exc.value.code == 2 and not (root / "bad-report.json").exists()
    capsys.readouterr()
    monkeypatch.undo()  # the workspace fixture stubs the control; self-test must run the real one
    assert main(["self-test"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_committed_synthetic_artifact_matches_a_fresh_self_test():
    root = Path(__file__).resolve().parents[1] / "artifacts" / "2026-10-06-reconstruction-sensitivity-synthetic"
    committed = json.loads((root / "self-test.json").read_text())
    assert committed == rs.self_test()
    readme = (root / "README.md").read_text()
    assert hashlib.sha256((root / "self-test.json").read_bytes()).hexdigest() in readme
    assert "Synthetic only" in readme and "neither CIL nor ASTRA was executed" in readme.replace("\n", " ")
