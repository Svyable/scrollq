import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_spiral_run import _dataset, _git, _villa  # noqa: E402

from scrollq.spiral_cloud import (  # noqa: E402
    LAUNCH_TIME_FIELDS,
    S3_NS,
    SpiralCloudError,
    build_plan,
    check_manifest,
    choose_gpu_machine_type,
    compare_preflights,
    derive_smoke_recipe,
    disk_floor,
    failure_bundle,
    fetch_lasagna,
    gpu_gate,
    main,
    smoke_verdict,
)
from scrollq.spiral_export import SpiralExportError, export_checkpoint  # noqa: E402
from scrollq.spiral_reproduction_check import ReproductionCheckError, evaluate_run  # noqa: E402
from scrollq.spiral_run import SpiralRunError, prepare_run, run_baseline  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
MANIFEST_REL = "artifacts/2026-10-05-spiral-cloud-plan/cloud_execution_manifest.json"
RECIPE_REL = "artifacts/2026-10-03-spiral-baseline-target/pherc0826_baseline_recipe.json"


def _manifest():
    return json.loads((REPO / MANIFEST_REL).read_text())


def _failed(report):
    return {row["name"] for row in report["checks"] if not row["ok"]}


# ---------------------------------------------------------------- committed manifest


def test_committed_manifest_passes_but_is_not_ready_until_launch_identities_exist():
    report = check_manifest(_manifest(), repo_root=REPO)
    assert report["ok"], _failed(report)
    assert report["ready_to_launch"] is False
    assert report["unresolved_launch_time_fields"] == list(LAUNCH_TIME_FIELDS)
    assert report["storage_total_gib"] <= _manifest()["data_disk"]["size_gib"]


def test_every_cloud_script_is_pinned_and_syntactically_valid():
    manifest = _manifest()
    scripts = sorted(str(p.relative_to(REPO)) for p in (REPO / "cloud/spiral-gcp").glob("*.sh"))
    assert sorted(manifest["scripts"]) == scripts
    bootstrap = (REPO / "cloud/spiral-gcp/bootstrap.sh").read_text()
    assert f"MANIFEST_REL={manifest['self_path']}" in bootstrap
    for role in ("stage-env", "gpu-gate", "stage-data", "gpu-run"):
        assert f"cloud/spiral-gcp/{role}.sh" in manifest["scripts"]
        assert role in bootstrap
    for script in scripts:
        subprocess.run(["bash", "-n", str(REPO / script)], check=True)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda m: m["experiment_contract"].update(optimizer_num_training_steps=20000),
         "contract:optimizer_num_training_steps"),
        (lambda m: m["experiment_contract"].update(expected_tracks_in_roi=1),
         "contract:expected_tracks_in_roi"),
        (lambda m: m["experiment_contract"].update(satisfied_tracks_percent=10.0),
         "contract:satisfied_tracks_percent"),
        (lambda m: m["experiment_contract"].update(ink_may_select_geometry=True),
         "contract:ink_may_select_geometry"),
        (lambda m: m["software"]["villa"].update(commit="f" * 40), "software:villa"),
        (lambda m: m["gpu_vm"].update(termination_action="STOP"), "gpu_vm:termination"),
        (lambda m: m["gpu_vm"].update(max_run_duration_hours=24), "gpu_vm:max_run"),
        (lambda m: m["smoke"].update(optimizer_num_training_steps=30000), "smoke:steps"),
        (lambda m: m["smoke"].update(delete_outputs_after=False), "smoke:non_promotional"),
        (lambda m: m["smoke"].update(projection_safety_factor=0.5), "smoke:safety_factor"),
        (lambda m: m["storage_budget_gib"]["floors"]["before_pack"].update(min_free_gib=10),
         "storage:floor:before_pack"),
        (lambda m: m["data_disk"].update(size_gib=100), "storage:fits_disk"),
        (lambda m: m["staging_sources"].update(outward_sense="ACW"), "staging:outward_sense"),
        (lambda m: m["staging_sources"]["lasagna"]["stores"][0].update(expected_scale=[2.0, 2.0, 2.0]),
         "lasagna:scale"),
        (lambda m: m["staging_sources"]["lasagna"]["stores"][0].update(local="PHerc0826_nx.ome.zarr"),
         "lasagna:local_names"),
        (lambda m: m["watchdog"].update(gpu_prep_window_minutes=900), "watchdog:prep_window"),
        (lambda m: m["scripts"].update({"cloud/spiral-gcp/gpu-run.sh": "0" * 64}),
         "script:cloud/spiral-gcp/gpu-run.sh"),
    ],
)
def test_manifest_cannot_move_the_experiment_or_weaken_guards(mutate, expected):
    manifest = _manifest()
    mutate(manifest)
    report = check_manifest(manifest, repo_root=REPO)
    assert report["ok"] is False
    assert expected in _failed(report)


def test_recipe_bytes_are_bound(tmp_path):
    recipe = json.loads((REPO / RECIPE_REL).read_text())
    recipe["bounded_reproduction"]["optimizer_random_seed"] = 2
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe))
    report = check_manifest(_manifest(), repo_root=REPO, recipe_path=path)
    assert "recipe_sha256" in _failed(report)
    assert "contract:optimizer_random_seed" in _failed(report)


# --------------------------------------------------------------------------- plan


def _repo_copy(tmp_path):
    root = tmp_path / "repo"
    for rel in [MANIFEST_REL, RECIPE_REL, *_manifest()["scripts"]]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.org")
    _git(root, "config", "user.name", "T")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


LAUNCH = {
    "gcp.project": "proj-1",
    "gcp.zone": "us-central1-a",
    "gcp.image.name": "common-cu128-v20261001",
    "gcp.evidence_bucket.name": "proj-1-scroliq-evidence",
    "software.uv.version": "0.0.0-test",
    "software.uv.linux_x86_64_tarball_sha256": "a" * 64,
}


def test_plan_emits_guarded_gcloud_commands_without_executing(tmp_path):
    root, commit = _repo_copy(tmp_path)
    manifest_bytes = (root / MANIFEST_REL).read_bytes()
    plan = build_plan(json.loads(manifest_bytes), manifest_bytes, repo_root=root, run_id="run1",
                      overrides={**LAUNCH, "software.scrollq.commit": commit})
    assert plan["executes_nothing"] is True
    assert plan["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    creates = [s["argv"] for s in plan["steps"] if s["argv"][:4] == ["gcloud", "compute", "instances", "create"]]
    assert [a[4] for a in creates] == [
        "scroliq-stage-env-run1", "scroliq-gpu-gate-run1", "scroliq-stage-data-run1", "scroliq-gpu-run-run1"]
    for argv in creates:
        assert "--instance-termination-action=DELETE" in argv
        assert any(a.startswith("--max-run-duration=") for a in argv)
        assert any("auto-delete=no" in a for a in argv)
        assert "--metadata-from-file=startup-script=cloud/spiral-gcp/bootstrap.sh" in argv
        assert f"scroliq-commit={commit}" in next(a for a in argv if a.startswith("--metadata="))
    assert "--max-run-duration=720m" in creates[3]
    assert "--maintenance-policy=TERMINATE" in creates[3]
    assert "--machine-type=g2-standard-4" in creates[1]
    assert "--machine-type=e2-standard-8" in creates[0]


def test_plan_refuses_unresolved_or_mismatched_commit(tmp_path):
    root, commit = _repo_copy(tmp_path)
    manifest_bytes = (root / MANIFEST_REL).read_bytes()
    manifest = json.loads(manifest_bytes)
    with pytest.raises(SpiralCloudError, match="unresolved"):
        build_plan(manifest, manifest_bytes, repo_root=root, run_id="run1",
                   overrides={"software.scrollq.commit": commit})
    (root / MANIFEST_REL).write_text(manifest_bytes.decode() + " ")
    _git(root, "commit", "-q", "-am", "drift")
    drifted = _git(root, "rev-parse", "HEAD")
    with pytest.raises(SpiralCloudError, match="differs"):
        build_plan(manifest, manifest_bytes, repo_root=root, run_id="run1",
                   overrides={**LAUNCH, "software.scrollq.commit": drifted})


def test_gpu_machine_type_follows_measured_pools():
    manifest = _manifest()
    assert choose_gpu_machine_type(manifest, None)["machine_type"] == "g2-standard-16"
    assert choose_gpu_machine_type(manifest, 4 * (1 << 30))["machine_type"] == "g2-standard-8"
    assert choose_gpu_machine_type(manifest, 30 * (1 << 30))["machine_type"] == "g2-standard-16"
    with pytest.raises(SpiralCloudError, match="no single-L4"):
        choose_gpu_machine_type(manifest, 200 * (1 << 30))


# ---------------------------------------------------------------------- smoke


def _progress_villa(tmp_path, steps_seen):
    villa, _ = _villa(tmp_path)
    (villa / "spiral-fitting" / "fit_spiral.py").write_text(
        "import json, os, pathlib, sys\n"
        "run=pathlib.Path(os.environ['FIT_SPIRAL_RUN_DIR'])\n"
        "cfg=json.loads(os.environ['FIT_SPIRAL_CONFIG_OVERRIDES'])\n"
        "n=cfg['optimizer_num_training_steps']\n"
        "print('loaded 480117 tracks within z-roi [11000, 12000)')\n"
        "print('fitting 0 patches')\n"
        f"print(f'PROGRESS optimize \\u2014 {{n:,}}/{{n:,}} iterations (100.0%) \\u2014 {steps_seen} it/s \\u2014 elapsed 0:01')\n"
        "(run/'checkpoint_fitted.ckpt').write_bytes(b'ckpt')\n"
    )
    _git(villa, "commit", "-q", "-am", "progress fitter")
    return villa, _git(villa, "rev-parse", "HEAD")


def _smoke_run(tmp_path, rate="100.0"):
    villa, commit = _progress_villa(tmp_path, rate)
    dataset, recipe_path = _dataset(tmp_path, commit)
    smoke = derive_smoke_recipe(recipe_path.read_bytes(), 300)
    smoke_path = tmp_path / "smoke-recipe.json"
    smoke_path.write_text(json.dumps(smoke))
    run_dir = tmp_path / "smoke-run"
    receipt = run_baseline(dataset=dataset, recipe_path=smoke_path, villa_root=villa,
                           run_dir=run_dir, python_executable=sys.executable)
    return SimpleNamespace(villa=villa, dataset=dataset, recipe=recipe_path, smoke=smoke,
                           run_dir=run_dir, receipt=receipt)


def test_smoke_recipe_changes_only_the_step_count():
    base_bytes = (REPO / RECIPE_REL).read_bytes()
    base = json.loads(base_bytes)
    smoke = derive_smoke_recipe(base_bytes, 300)
    assert smoke["bounded_reproduction"]["optimizer_num_training_steps"] == 300
    assert smoke["bounded_reproduction"]["config_overrides"]["optimizer_num_training_steps"] == 300
    assert smoke["smoke"]["promotional"] is False
    assert smoke["smoke"]["base_recipe_sha256"] == hashlib.sha256(base_bytes).hexdigest()
    for document in (smoke, base):
        document["bounded_reproduction"]["optimizer_num_training_steps"] = None
        document["bounded_reproduction"]["config_overrides"]["optimizer_num_training_steps"] = None
        document["bounded_reproduction"].pop("shell_template", None)
        document.pop("status")
    smoke.pop("smoke")
    assert smoke == base
    with pytest.raises(SpiralCloudError):
        derive_smoke_recipe(base_bytes, 30000)


def test_smoke_receipt_is_non_promotional_and_cannot_be_reproduced_or_exported(tmp_path):
    run = _smoke_run(tmp_path)
    assert run.receipt["success"] is True
    assert run.receipt["mode"] == "smoke" and run.receipt["promotional"] is False
    assert run.receipt["supervision"]["ok"] is True
    with pytest.raises(ReproductionCheckError, match="smoke"):
        evaluate_run(run.run_dir)
    (run.run_dir / "reproduction-check.json").write_text("{}")
    with pytest.raises(SpiralExportError, match="smoke"):
        export_checkpoint(run_dir=run.run_dir, dataset=run.dataset, villa_root=run.villa,
                          output=tmp_path / "out.tifxyz", evidence_dir=tmp_path / "ev",
                          reproduction_check=run.run_dir / "reproduction-check.json",
                          python_executable=sys.executable, device="cpu")


def test_baseline_receipt_is_promotional(tmp_path):
    villa, commit = _progress_villa(tmp_path, "100.0")
    dataset, recipe_path = _dataset(tmp_path, commit)
    receipt = run_baseline(dataset=dataset, recipe_path=recipe_path, villa_root=villa,
                           run_dir=tmp_path / "run", python_executable=sys.executable)
    assert receipt["mode"] == "baseline" and receipt["promotional"] is True


def test_runner_rejects_a_malformed_smoke_contract(tmp_path):
    villa, commit = _villa(tmp_path)
    dataset, recipe_path = _dataset(tmp_path, commit)
    smoke = derive_smoke_recipe(recipe_path.read_bytes(), 300)
    smoke["smoke"]["promotional"] = True
    path = tmp_path / "bad-smoke.json"
    path.write_text(json.dumps(smoke))
    with pytest.raises(SpiralRunError, match="smoke"):
        prepare_run(dataset=dataset, recipe_path=path, villa_root=villa, run_dir=tmp_path / "r",
                    python_executable=sys.executable, cache_dir=None)


def test_smoke_verdict_projects_frozen_runtime(tmp_path):
    run = _smoke_run(tmp_path, rate="100.0")
    manifest = _manifest()
    verdict = smoke_verdict(manifest, run_dir=run.run_dir, elapsed_vm_seconds=3600)
    assert verdict["status"] == "proceed", _failed(verdict)
    assert verdict["projection"]["basis"] == "rate"
    # 30,000 steps at 100 it/s is ~300 s plus setup; inflated by the safety factor.
    assert 300 * 1.25 <= verdict["projection"]["projected_fit_seconds_with_safety"] < 400


def test_smoke_verdict_stops_when_projection_exceeds_vm_lifetime(tmp_path):
    run = _smoke_run(tmp_path, rate="0.5")
    verdict = smoke_verdict(_manifest(), run_dir=run.run_dir, elapsed_vm_seconds=3600)
    assert verdict["status"] == "stop"
    assert "projection_fits_budget" in _failed(verdict)


def test_smoke_verdict_stops_on_failed_receipt(tmp_path):
    run = _smoke_run(tmp_path)
    receipt_path = run.run_dir / "spiral-run.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["success"] = False
    receipt_path.write_text(json.dumps(receipt))
    verdict = smoke_verdict(_manifest(), run_dir=run.run_dir, elapsed_vm_seconds=0)
    assert verdict["status"] == "stop"
    assert "receipt_success" in _failed(verdict)


# ------------------------------------------------------------------ Lasagna fetch


BASE = "https://bucket.example"


def _fake_bucket(objects, *, page=2):
    """objects: key -> bytes. Returns a get() implementing paged ListObjectsV2."""
    keys = sorted(objects)

    def get(url):
        if url.startswith(f"{BASE}/?list-type=2"):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(url).query)
            prefix = query["prefix"][0]
            start = int(query.get("continuation-token", ["0"])[0])
            match = [k for k in keys if k.startswith(prefix)]
            chunk = match[start:start + page]
            more = start + page < len(match)
            body = "".join(
                f"<Contents><Key>{k}</Key><Size>{len(objects[k])}</Size>"
                f"<ETag>&quot;{hashlib.md5(objects[k]).hexdigest()}&quot;</ETag></Contents>"
                for k in chunk)
            token = f"<NextContinuationToken>{start + page}</NextContinuationToken>" if more else ""
            return (f'<ListBucketResult xmlns="{S3_NS[1:-1]}"><IsTruncated>{str(more).lower()}'
                    f"</IsTruncated>{token}{body}</ListBucketResult>").encode()
        key = url[len(BASE) + 1:]
        if key not in objects:
            raise SpiralCloudError(f"404 {key}")
        return objects[key]

    return get


def _lasagna_fixture(chunks_per_store=3):
    run_prefix = "S/run"
    objects = {f"{run_prefix}/scroll.lasagna.json": b'{"version":2}'}
    stores = []
    for src, local in (("S_nx.ome.zarr", "las_008_nx.ome.zarr"), ("S_ny.ome.zarr", "las_008_ny.ome.zarr"),
                       ("S_grad_mag.ome.zarr", "las_008_grad_mag.ome.zarr")):
        attrs = json.dumps({"multiscales": [{"datasets": [
            {"path": "2", "coordinateTransformations": [{"type": "scale", "scale": [4.0, 4.0, 4.0]}]}]}]}).encode()
        meta = {".zattrs": attrs, ".zgroup": b'{"zarr_format":2}', "2/.zarray": b'{"shape":[64,64,64]}'}
        for rel, data in meta.items():
            objects[f"{run_prefix}/{src}/{rel}"] = data
        for i in range(chunks_per_store):
            objects[f"{run_prefix}/{src}/2/0/0/{i}"] = f"{src}-{i}".encode() * 7
        stores.append({"source": src, "local": local, "expected_scale": [4.0, 4.0, 4.0],
                       **{f"{k}_sha256": hashlib.sha256(meta[rel]).hexdigest()
                          for k, rel in (("zattrs", ".zattrs"), ("zgroup", ".zgroup"), ("zarray", "2/.zarray"))}})
    manifest = {"staging_sources": {"lasagna": {
        "bucket_url": BASE, "run_prefix": run_prefix, "group": "2", "stores": stores,
        "manifest_file": {"name": "scroll.lasagna.json",
                          "sha256": hashlib.sha256(objects[f"{run_prefix}/scroll.lasagna.json"]).hexdigest()}}}}
    return manifest, objects


def test_fetch_lasagna_verifies_every_object_and_renames_stores(tmp_path):
    manifest, objects = _lasagna_fixture()
    report = fetch_lasagna(manifest, dataset=tmp_path / "ds", evidence_dir=tmp_path / "ev",
                           workers=4, get=_fake_bucket(objects))
    assert report["ok"], _failed(report)
    for row in report["stores"]:
        assert row["listed_objects"] == 3 and row["md5"] == 3 and row["failed"] == 0
    chunk = tmp_path / "ds/lasagna_inputs/las_008_nx.ome.zarr/2/0/0/1"
    assert chunk.read_bytes() == objects["S/run/S_nx.ome.zarr/2/0/0/1"]
    assert (tmp_path / "ds/lasagna_inputs/las_008_grad_mag.ome.zarr/2/.zarray").is_file()
    # Re-running resumes: everything is already present and verified.
    again = fetch_lasagna(manifest, dataset=tmp_path / "ds", evidence_dir=tmp_path / "ev2",
                          workers=4, get=_fake_bucket(objects))
    assert again["ok"] and all(r["already_present"] == 3 and r["downloaded"] == 0 for r in again["stores"])


def test_fetch_lasagna_empty_group_is_not_a_pass(tmp_path):
    manifest, objects = _lasagna_fixture(chunks_per_store=0)
    report = fetch_lasagna(manifest, dataset=tmp_path / "ds", evidence_dir=tmp_path / "ev",
                           workers=2, get=_fake_bucket(objects))
    assert report["ok"] is False
    assert "las_008_nx.ome.zarr:listed_chunks" in _failed(report)


def test_fetch_lasagna_rejects_corrupt_object_and_drifted_metadata(tmp_path):
    manifest, objects = _lasagna_fixture()
    clean_get = _fake_bucket(objects)

    def corrupt(url):
        data = clean_get(url)
        return data[:-1] + b"X" if url.endswith("S_ny.ome.zarr/2/0/0/2") else data

    report = fetch_lasagna(manifest, dataset=tmp_path / "a", evidence_dir=tmp_path / "ea",
                           workers=2, get=corrupt)
    assert "las_008_ny.ome.zarr:complete" in _failed(report)

    drifted = copy.deepcopy(manifest)
    drifted["staging_sources"]["lasagna"]["stores"][2]["expected_scale"] = [2.0, 2.0, 2.0]
    report = fetch_lasagna(drifted, dataset=tmp_path / "b", evidence_dir=tmp_path / "eb",
                           workers=2, get=clean_get)
    assert "las_008_grad_mag.ome.zarr:scale" in _failed(report)


# --------------------------------------------------------------- small gates


def test_compare_preflight_detects_any_input_change():
    first = {"ready_for_fit": True, "config_overrides_canonical_json": "{}",
             "input_files": {"tracks/t.dbm": {"sha256": "a", "size": 1, "mtime_ns": 5}}}
    assert compare_preflights(first, copy.deepcopy(first))["ok"] is True
    second = copy.deepcopy(first)
    second["input_files"]["tracks/t.dbm"]["mtime_ns"] = 6
    report = compare_preflights(first, second)
    assert report["ok"] is False and report["changed"] == ["tracks/t.dbm"]
    assert compare_preflights({"ready_for_fit": True, "input_files": {}}, {"ready_for_fit": True,
                              "input_files": {}})["ok"] is False


def test_disk_floor(tmp_path):
    assert disk_floor(tmp_path, 0.0, "x")["ok"] is True
    assert disk_floor(tmp_path, 1e9, "x")["ok"] is False
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"storage_budget_gib": {"floors": {"huge": {"min_free_gib": 1e9}}}}))
    assert main(["disk-floor", "--path", str(tmp_path), "--manifest", str(manifest), "--floor", "huge"]) == 3


GOOD_PROBE = {name: {"ok": True, "value": "x"} for name in (
    "import_torch", "import_triton", "import_vc_spiral", "import_fit_spiral",
    "triton_kernel", "villa_cuda_startup")}
GOOD_PROBE["torch_cuda"] = {"ok": True, "value": {"device": "NVIDIA L4"}}


def _runner(probe, code=0, test_code=0):
    def run(argv, **kwargs):
        if "pytest" in argv:
            return subprocess.CompletedProcess(argv, test_code, stdout="1 passed", stderr="")
        return subprocess.CompletedProcess(argv, code, stdout="noise\nSCROLIQ_GATE_JSON=" + json.dumps(probe),
                                           stderr="")
    return run


def _smi(name="NVIDIA L4", driver="570.86.15"):
    return lambda: {"ok": True, "gpus": [{"name": name, "driver_version": driver, "memory_total": "23034 MiB"}]}


@pytest.mark.parametrize("smi, probe, test_code, failed", [
    (_smi(), GOOD_PROBE, 0, None),
    (_smi(name="Tesla T4"), GOOD_PROBE, 0, "gpu_name"),
    (_smi(driver="550.54.15"), GOOD_PROBE, 0, "driver_major"),
    (_smi(), {**GOOD_PROBE, "triton_kernel": {"ok": False, "error": "no cc"}}, 0, "probe:triton_kernel"),
    (_smi(), GOOD_PROBE, 1, "villa_test:t.py"),
])
def test_gpu_gate(tmp_path, smi, probe, test_code, failed):
    report = gpu_gate(python="py", villa_root=tmp_path, expect_gpu="L4", min_driver_major=570,
                      cpu_only=False, villa_tests=["t.py"], runner=_runner(probe, test_code=test_code), smi=smi)
    if failed is None:
        assert report["ok"], _failed(report)
    else:
        assert report["ok"] is False and failed in _failed(report)


def test_cpu_only_gate_skips_gpu_checks(tmp_path):
    probe = {k: GOOD_PROBE[k] for k in ("import_torch", "import_triton", "import_vc_spiral", "import_fit_spiral")}
    report = gpu_gate(python="py", villa_root=tmp_path, expect_gpu="L4", min_driver_major=570,
                      cpu_only=True, runner=_runner(probe), smi=lambda: pytest.fail("smi called"))
    assert report["ok"] and report["mode"] == "cpu-import-only"


def test_failure_bundle_is_compact_and_create_only(tmp_path):
    log = tmp_path / "fit.log"
    log.write_text("x" * 1000 + "\nTHE END\n")
    out = tmp_path / "bundle"
    doc = failure_bundle(out_dir=out, stage="gpu-run", failed_gate="fit", reason="rc 1",
                         include=[log, tmp_path / "missing.log"], tail_bytes=100)
    assert doc["failed_gate"] == "fit"
    assert doc["files"][0]["tail_truncated"] is True and doc["files"][1]["missing"] is True
    assert "THE END" in (out / doc["files"][0]["tail_file"]).read_text()
    with tarfile.open(doc["archive"]["path"]) as tar:
        assert "bundle/failure-bundle.json" in tar.getnames()
    with pytest.raises(SpiralCloudError):
        failure_bundle(out_dir=out, stage="s", failed_gate="g", reason="", include=[])
