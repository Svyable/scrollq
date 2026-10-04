"""Sealed-truth timing for blind physical controls.

Every refusal path has a paired clean path: a checker that cannot fail on a
tampered chain would also pass a clean one for no reason.
"""

import copy
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from scrollq import blind_control as bc
from scrollq.package_hash import sha256_path

NIST_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "artifacts" / "2026-10-04-nist-model-scroll" / "benchmark-manifest.json"
)

T_SEAL = "2026-10-05T09:00:00+00:00"
T_COMMIT = "2026-10-05T10:00:00+00:00"
T_ANCHOR = "2026-10-05T10:30:00+00:00"
T_REVEAL = "2026-10-06T12:00:00+00:00"


def at(stamp):
    return lambda: stamp


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _base_manifest() -> dict:
    manifest = json.loads(NIST_MANIFEST.read_text(encoding="utf-8"))
    manifest["truth"].append(
        {
            "id": "dev-calibration-strip",
            "role": "development_truth",
            "training_eligible": False,
            "description": "Visible strip used only to check the detector runs.",
        }
    )
    return manifest


class Chain:
    """A complete, clean blind-control chain built in a temp directory."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.ct = tmp_path / "ct"
        for i in range(3):
            _write(self.ct / f"slice_{i:04d}.tif", bytes([i]) * 64)
        self.truth = tmp_path / "truth"
        _write(self.truth / "known-text-transcription", b"ALPHA BETA")
        _write(self.truth / "leaded-letter-locations", b"12,34;56,78")
        self.preds = tmp_path / "preds"
        _write(self.preds / "surface" / "mesh.txt", b"surface v1")
        _write(self.preds / "detection" / "map.txt", b"detections v1")
        self.spec = _write(tmp_path / "detector.json", b'{"kind":"band-mean"}')
        self.salt = "ab" * 32

        inventory = bc.inventory_tree(self.ct)
        manifest = _base_manifest()
        manifest["acquisition"]["doi"] = "10.9999/fixture-not-a-real-doi"
        manifest["acquisition"]["license"]["verified"] = True
        manifest["acquisition"]["license"]["evidence_url"] = "https://example.invalid/license"
        manifest["acquisition"]["inventory"] = {
            k: inventory[k] for k in ("file_count", "total_bytes", "tree_sha256")
        }
        self.pinned = manifest
        self.seal, self.manifest = bc.seal_truth(
            manifest, self.truth, self.salt, clock=at(T_SEAL)
        )
        self.commitment = bc.commit_prediction(
            self.manifest, self.preds, self.spec,
            pipeline_id="geometry-v0",
            development_truth_used=["dev-calibration-strip"],
            clock=at(T_COMMIT),
        )
        self.commitment_path = _write(
            tmp_path / "commitment.json", bc._dump(self.commitment).encode()
        )
        self.commitment_file_sha = bc._file_bytes_sha256(self.commitment_path)

    def anchor_external(self, stamp=T_ANCHOR):
        return bc.anchor_external(self.commitment_path, "rfc3161:fixture-token", stamp)

    def reveal(self, *, attested_by="A. Reviewer", stamp=T_REVEAL):
        return bc.reveal_truth(
            self.manifest, self.commitment, self.preds, self.truth, self.salt,
            attested_by=attested_by, clock=at(stamp),
        )

    def report(self, reveal=None, anchor=None, manifest=None, commitment=None):
        return bc.build_report(
            manifest or self.manifest, commitment or self.commitment, reveal, anchor,
            commitment_file_sha256=self.commitment_file_sha,
        )


@pytest.fixture
def chain(tmp_path):
    return Chain(tmp_path)


def _rehash_commitment(doc):
    doc = dict(doc)
    doc["commitment_sha256"] = bc._self_digest(doc, "commitment_sha256")
    return doc


def _rehash_reveal(doc):
    doc = dict(doc)
    doc["reveal_sha256"] = bc._self_digest(doc, "reveal_sha256")
    return doc


# -- manifest -----------------------------------------------------------------


def test_nist_manifest_is_valid_but_unpinned_and_cannot_be_committed(tmp_path):
    manifest = json.loads(NIST_MANIFEST.read_text(encoding="utf-8"))
    assessment = bc.assess_manifest(manifest)

    assert assessment["pin_status"] == "unpinned"
    assert assessment["missing_pins"] == [
        "acquisition.doi", "acquisition.license.verified", "acquisition.inventory",
    ]
    assert assessment["seal_status"] == "unsealed"
    assert assessment["ready_for_commit"] is False
    assert assessment["training_eligible"] is False
    assert assessment["development_ids"] == []
    assert any("unverified" in w for w in assessment["warnings"])

    preds = _write(tmp_path / "p" / "x", b"x")
    spec = _write(tmp_path / "spec.json", b"{}")
    with pytest.raises(bc.BlindControlError, match="not ready"):
        bc.commit_prediction(manifest, preds.parent, spec, pipeline_id="p")


def test_nist_manifest_makes_no_unverifiable_pin():
    manifest = json.loads(NIST_MANIFEST.read_text(encoding="utf-8"))
    acq = manifest["acquisition"]
    assert acq["doi"] is None and acq["landing_url"] is None
    assert acq["inventory"] is None
    assert acq["license"]["verified"] is False and acq["license"]["evidence_url"] is None
    assert manifest["sealed_truth_commitment_sha256"] is None


def _mutations():
    def m(fn):
        return fn

    return {
        "sealed truth marked training eligible": m(
            lambda d: d["truth"][0].update(training_eligible=True)
        ),
        "manifest training eligible with sealed truth": m(
            lambda d: d.update(training_eligible=True)
        ),
        "unknown role": m(lambda d: d["truth"][0].update(role="hidden_truth")),
        "duplicate truth id": m(lambda d: d["truth"][1].update(id=d["truth"][0]["id"])),
        "unknown top-level key": m(lambda d: d.update(trainingeligible=False)),
        "missing training_eligible": m(lambda d: d.pop("training_eligible")),
        "non-boolean training_eligible": m(lambda d: d.update(training_eligible="no")),
        "malformed doi": m(lambda d: d["acquisition"].update(doi="not-a-doi")),
        "verified license without evidence": m(
            lambda d: d["acquisition"]["license"].update(verified=True)
        ),
        "bad commitment hex": m(
            lambda d: d.update(sealed_truth_commitment_sha256="XYZ")
        ),
        "commitment without sealed truth": m(
            lambda d: (
                d.update(truth=[d["truth"][0] | {"role": "development_truth"}]),
                d.update(sealed_truth_commitment_sha256="a" * 64),
            )
        ),
        "empty claim limits": m(lambda d: d.update(claim_limits=[])),
        "claimed facts without a source": m(lambda d: d["volume"].pop("claimed_source")),
        "naive as_of": m(lambda d: d.update(as_of="10/04/2026")),
        "empty truth": m(lambda d: d.update(truth=[])),
        "non-object inventory": m(lambda d: d["acquisition"].update(inventory=3)),
    }


@pytest.mark.parametrize("name", sorted(_mutations()))
def test_manifest_contract_rejects(name):
    manifest = json.loads(NIST_MANIFEST.read_text(encoding="utf-8"))
    _mutations()[name](manifest)
    with pytest.raises(bc.BlindControlError):
        bc.assess_manifest(manifest)


def test_claimed_slice_count_disagreeing_with_acquired_bytes_is_a_warning(chain):
    manifest = copy.deepcopy(chain.pinned)
    manifest["volume"]["claimed"]["slice_count"] = 620
    assessment = bc.assess_manifest(manifest)
    assert assessment["pin_status"] == "pinned"
    assert any("slice_count 620 != inventory.file_count 3" in w for w in assessment["warnings"])


# -- inventory / seal ---------------------------------------------------------


def test_inventory_tree_digest_is_the_repo_directory_digest(chain):
    inventory = bc.inventory_tree(chain.ct)
    assert inventory["tree_sha256"] == sha256_path(chain.ct)
    assert inventory["file_count"] == 3
    assert inventory["total_bytes"] == 3 * 64
    assert [f["path"] for f in inventory["files"]] == sorted(f["path"] for f in inventory["files"])


def test_inventory_rejects_empty_and_symlinked_roots(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(bc.BlindControlError, match="no files"):
        bc.inventory_tree(tmp_path / "empty")
    target = _write(tmp_path / "t.bin", b"x")
    link_root = tmp_path / "links"
    link_root.mkdir()
    (link_root / "a").symlink_to(target)
    with pytest.raises(bc.BlindControlError, match="symlinks"):
        bc.inventory_tree(link_root)


def test_seal_is_salted_and_publishes_no_per_item_hashes(chain):
    other_salt = "cd" * 32
    reseal, _ = bc.seal_truth(chain.pinned, chain.truth, other_salt, clock=at(T_SEAL))
    assert reseal["sealed_truth_commitment_sha256"] != chain.seal["sealed_truth_commitment_sha256"]

    published = json.dumps(chain.seal)
    for item in ("known-text-transcription", "leaded-letter-locations"):
        assert sha256_path(chain.truth / item) not in published
    assert chain.seal["sealed_item_ids"] == ["known-text-transcription", "leaded-letter-locations"]
    assert chain.manifest["sealed_truth_commitment_sha256"] == chain.seal["sealed_truth_commitment_sha256"]
    assert chain.pinned["sealed_truth_commitment_sha256"] is None  # input not edited in place


def test_seal_is_bound_to_the_acquired_bytes(chain):
    other = copy.deepcopy(chain.pinned)
    other["acquisition"]["inventory"]["tree_sha256"] = "e" * 64
    reseal, _ = bc.seal_truth(other, chain.truth, chain.salt, clock=at(T_SEAL))
    assert reseal["sealed_truth_commitment_sha256"] != chain.seal["sealed_truth_commitment_sha256"]


def test_seal_refuses_unpinned_resealed_and_missing_truth(chain, tmp_path):
    with pytest.raises(bc.BlindControlError, match="unpinned"):
        bc.seal_truth(json.loads(NIST_MANIFEST.read_text()), chain.truth, chain.salt)
    with pytest.raises(bc.BlindControlError, match="already sealed"):
        bc.seal_truth(chain.manifest, chain.truth, chain.salt)
    (chain.truth / "leaded-letter-locations").unlink()
    with pytest.raises(bc.BlindControlError, match="not found"):
        bc.seal_truth(chain.pinned, chain.truth, chain.salt)
    with pytest.raises(bc.BlindControlError, match="salt"):
        bc.seal_truth(chain.pinned, chain.truth, "short")


# -- commitment ---------------------------------------------------------------


def test_commitment_binds_manifest_seal_predictions_and_detector(chain):
    c = chain.commitment
    assert c["manifest_sha256"] == bc.digest(chain.manifest)
    assert c["sealed_truth_commitment_sha256"] == chain.seal["sealed_truth_commitment_sha256"]
    assert c["predictions"]["tree_sha256"] == sha256_path(chain.preds)
    assert c["predictions"]["file_count"] == 2
    assert c["detector_spec_sha256"] == bc._file_bytes_sha256(chain.spec)
    assert c["commitment_sha256"] == bc._self_digest(c, "commitment_sha256")
    assert c["development_truth_used"] == ["dev-calibration-strip"]


def test_commit_refuses_sealed_or_undeclared_truth_use_and_empty_inputs(chain, tmp_path):
    kw = dict(pipeline_id="p")
    with pytest.raises(bc.BlindControlError, match="sealed_truth"):
        bc.commit_prediction(chain.manifest, chain.preds, chain.spec,
                             development_truth_used=["known-text-transcription"], **kw)
    with pytest.raises(bc.BlindControlError, match="not a declared development_truth"):
        bc.commit_prediction(chain.manifest, chain.preds, chain.spec,
                             development_truth_used=["invented"], **kw)
    (tmp_path / "none").mkdir()
    with pytest.raises(bc.BlindControlError, match="no files"):
        bc.commit_prediction(chain.manifest, tmp_path / "none", chain.spec, **kw)
    with pytest.raises(bc.BlindControlError, match="detector spec"):
        bc.commit_prediction(chain.manifest, chain.preds, tmp_path / "missing.json", **kw)
    with pytest.raises(bc.BlindControlError, match="not ready"):
        bc.commit_prediction(chain.pinned, chain.preds, chain.spec, **kw)  # pinned, unsealed


# -- reveal -------------------------------------------------------------------


def test_reveal_records_the_moment_truth_becomes_visible(chain):
    reveal = chain.reveal()
    assert reveal["revealed_at"] == T_REVEAL
    assert reveal["prediction_commitment_sha256"] == chain.commitment["commitment_sha256"]
    assert reveal["predictions_tree_sha256"] == chain.commitment["predictions"]["tree_sha256"]
    assert reveal["attestation"]["statement"] == bc.ATTESTATION_STATEMENT
    assert reveal["reveal_sha256"] == bc._self_digest(reveal, "reveal_sha256")


def test_reveal_without_attestation_records_none(chain):
    assert chain.reveal(attested_by=None)["attestation"] is None


def test_reveal_refuses_changed_predictions_before_touching_truth(chain, tmp_path):
    (chain.preds / "detection" / "map.txt").write_bytes(b"detections v2 tuned after the fact")
    # The truth root does not even exist: the refusal must come from the
    # predictions check, proving truth bytes are never read first.
    with pytest.raises(bc.BlindControlError, match="predictions changed"):
        bc.reveal_truth(chain.manifest, chain.commitment, chain.preds,
                        tmp_path / "no-such-truth", chain.salt, clock=at(T_REVEAL))


def test_reveal_refuses_added_prediction_file(chain):
    _write(chain.preds / "detection" / "extra.txt", b"late addition")
    with pytest.raises(bc.BlindControlError, match="predictions changed"):
        chain.reveal()


def test_reveal_refuses_wrong_salt_and_altered_truth(chain):
    with pytest.raises(bc.BlindControlError, match="do not match"):
        bc.reveal_truth(chain.manifest, chain.commitment, chain.preds, chain.truth,
                        "00" * 32, clock=at(T_REVEAL))
    (chain.truth / "known-text-transcription").write_bytes(b"ALPHA GAMMA")
    with pytest.raises(bc.BlindControlError, match="do not match"):
        chain.reveal()


def test_reveal_refuses_time_not_after_commitment(chain):
    for stamp in (T_COMMIT, "2026-10-05T09:59:59+00:00"):
        with pytest.raises(bc.BlindControlError, match="strictly after"):
            chain.reveal(stamp=stamp)


def test_reveal_refuses_a_commitment_made_against_another_manifest(chain):
    other = copy.deepcopy(chain.manifest)
    other["as_of"] = "2026-10-09"
    with pytest.raises(bc.BlindControlError, match="different manifest"):
        bc.reveal_truth(other, chain.commitment, chain.preds, chain.truth, chain.salt,
                        clock=at(T_REVEAL))


# -- report -------------------------------------------------------------------


def test_clean_anchored_chain_is_sealed_order_anchored(chain):
    report = chain.report(chain.reveal(), chain.anchor_external())
    assert report["verdict"] == "sealed-order-anchored"
    assert report["violations"] == [] and report["weaknesses"] == []
    assert report["timing"] == {
        "prediction_committed_at": T_COMMIT,
        "anchored_at": T_ANCHOR,
        "truth_first_visible_at": T_REVEAL,
        "order": "prediction-before-truth",
        "ordering_evidence": "anchor-declared",
        "custody_attested": True,
    }
    assert report["benchmark"]["evaluation_only"] is True
    assert report["truth_roles"]["sealed_truth"] == ["known-text-transcription", "leaded-letter-locations"]
    assert "not evidence about carbon-ink detection on ancient papyrus" in report["interpretation"]
    assert not {"score", "scores", "metrics", "results"} & set(report)


def test_missing_anchor_or_attestation_stays_self_asserted(chain):
    no_anchor = chain.report(chain.reveal())
    assert no_anchor["verdict"] == "sealed-order-self-asserted"
    assert no_anchor["timing"]["ordering_evidence"] == "self-asserted-clock"
    assert any("no anchor" in w for w in no_anchor["weaknesses"])

    no_attest = chain.report(chain.reveal(attested_by=None), chain.anchor_external())
    assert no_attest["verdict"] == "sealed-order-self-asserted"
    assert any("unattested" in w for w in no_attest["weaknesses"])


def test_awaiting_reveal_is_valid_and_records_no_visibility(chain):
    report = chain.report(None, chain.anchor_external())
    assert report["verdict"] == "awaiting-reveal"
    assert report["timing"]["truth_first_visible_at"] is None
    assert report["timing"]["order"] == "truth-not-yet-visible"


def test_anchor_must_bind_this_commitment_and_precede_the_reveal(chain):
    good = chain.reveal()

    other = chain.anchor_external()
    other["commitment_sha256"] = "f" * 64
    r = chain.report(good, other)
    assert r["verdict"] == "sealed-order-self-asserted"
    assert any("different commitment" in w for w in r["weaknesses"])

    wrong_bytes = chain.anchor_external()
    wrong_bytes["file_sha256"] = "f" * 64
    assert any("commitment file bytes" in w for w in chain.report(good, wrong_bytes)["weaknesses"])

    late = chain.anchor_external(stamp="2026-10-07T00:00:00+00:00")
    r = chain.report(good, late)
    assert r["verdict"] == "sealed-order-self-asserted"
    assert any("does not precede the reveal" in w for w in r["weaknesses"])

    early = chain.anchor_external(stamp="2026-10-05T09:00:00+00:00")
    assert any("precedes the commitment time" in w for w in chain.report(good, early)["weaknesses"])


def test_tampered_commitment_is_not_blind(chain):
    forged = dict(chain.commitment, committed_at="2026-10-04T00:00:00+00:00")
    report = chain.report(chain.reveal(), commitment=forged)
    assert report["verdict"] == "not-blind"
    assert any("fails its own digest" in v for v in report["violations"])


def test_rehashed_commitment_against_a_different_manifest_is_not_blind(chain):
    forged = _rehash_commitment(dict(chain.commitment, manifest_sha256="1" * 64))
    report = chain.report(None, commitment=forged)
    assert report["verdict"] == "not-blind"
    assert any("different manifest" in v for v in report["violations"])


def test_commitment_listing_sealed_truth_as_used_is_not_blind(chain):
    forged = _rehash_commitment(
        dict(chain.commitment, development_truth_used=["known-text-transcription"])
    )
    report = chain.report(None, commitment=forged)
    assert report["verdict"] == "not-blind"
    assert any("sealed_truth item is listed as used" in v for v in report["violations"])


def test_reveal_that_is_not_after_commitment_is_not_blind_even_if_rehashed(chain):
    forged = _rehash_reveal(dict(chain.reveal(), revealed_at=T_COMMIT))
    report = chain.report(forged, chain.anchor_external())
    assert report["verdict"] == "not-blind"
    assert report["timing"]["order"] == "truth-not-after-prediction"
    assert any("no later than the prediction commitment" in v for v in report["violations"])


def test_reveal_of_other_commitment_or_changed_predictions_is_not_blind(chain):
    other = _rehash_reveal(dict(chain.reveal(), prediction_commitment_sha256="2" * 64))
    assert any("different prediction commitment" in v
               for v in chain.report(other)["violations"])

    moved = _rehash_reveal(dict(chain.reveal(), predictions_tree_sha256="3" * 64))
    assert any("differ from the committed predictions" in v
               for v in chain.report(moved)["violations"])

    wrong_seal = _rehash_reveal(dict(chain.reveal(), sealed_truth_commitment_sha256="4" * 64))
    assert any("different sealed-truth commitment" in v
               for v in chain.report(wrong_seal)["violations"])

    tampered = dict(chain.reveal(), revealed_at="2026-10-30T00:00:00+00:00")
    assert any("reveal record fails its own digest" in v
               for v in chain.report(tampered)["violations"])


def test_report_refuses_manifest_that_is_not_pinned_and_sealed(chain):
    report = chain.report(None, manifest=chain.pinned, commitment=chain.commitment)
    assert report["verdict"] == "not-blind"
    assert any("not pinned and sealed" in v for v in report["violations"])


def test_naive_timestamps_are_rejected(chain):
    forged = _rehash_commitment(dict(chain.commitment, committed_at="2026-10-05T10:00:00"))
    with pytest.raises(bc.BlindControlError, match="UTC offset"):
        chain.report(None, commitment=forged)


# -- anchor (git) -------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo, *args, env_extra=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    env.update(env_extra or {})
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


@needs_git
def test_git_anchor_is_content_verified_and_refuses_uncommitted_changes(chain, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    path = repo / "commitment.json"
    path.write_bytes(chain.commitment_path.read_bytes())

    with pytest.raises(bc.BlindControlError):
        bc.anchor_git(path, repo)  # untracked

    _git(repo, "add", "commitment.json")
    _git(repo, "commit", "-q", "-m", "commit predictions",
         env_extra={"GIT_COMMITTER_DATE": T_ANCHOR, "GIT_AUTHOR_DATE": T_ANCHOR})
    anchor = bc.anchor_git(path, repo)
    assert anchor["kind"] == "git-commit"
    assert anchor["anchored_at"] == T_ANCHOR
    assert anchor["file_sha256"] == chain.commitment_file_sha
    assert anchor["commitment_sha256"] == chain.commitment["commitment_sha256"]
    assert anchor["verified_by_tool"] == ["commitment file bytes equal the committed blob"]
    assert any("pushed" in line for line in anchor["not_verified_by_tool"])

    report = chain.report(chain.reveal(), anchor)
    assert report["verdict"] == "sealed-order-anchored"
    assert report["timing"]["ordering_evidence"] == "anchor-content-verified"

    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(bc.BlindControlError, match="uncommitted changes"):
        bc.anchor_git(path, repo)


# -- CLI ----------------------------------------------------------------------


def test_cli_help_needs_no_arguments_or_network(capsys):
    with pytest.raises(SystemExit) as exit_info:
        bc.main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in ("validate", "inventory", "seal", "commit", "anchor", "reveal", "report"):
        assert command in out


def test_cli_validate_require_pinned_fails_closed_on_the_nist_manifest(capsys):
    assert bc.main(["validate", "--manifest", str(NIST_MANIFEST)]) == 0
    assert bc.main(["validate", "--manifest", str(NIST_MANIFEST), "--require-pinned"]) == 1
    assert "unpinned" in capsys.readouterr().err
    assert bc.main(["validate", "--manifest", str(NIST_MANIFEST), "--require-sealed"]) == 1


def test_cli_end_to_end_chain_is_create_only_and_keeps_the_salt_private(tmp_path, monkeypatch, capsys):
    chain = Chain(tmp_path / "fixture")
    work = tmp_path / "work"
    work.mkdir()
    ticks = iter(f"2026-10-05T10:00:{n:02d}+00:00" for n in range(60))
    monkeypatch.setattr(bc, "utc_now", lambda: next(ticks))

    pinned = work / "pinned.json"
    pinned.write_text(json.dumps(chain.pinned))
    seal_args = [
        "seal", "--manifest", str(pinned), "--truth-root", str(chain.truth),
        "--seal-out", str(work / "seal.json"),
        "--manifest-out", str(work / "sealed.json"),
        "--salt-out", str(work / "salt.txt"),
    ]
    assert bc.main(seal_args) == 0
    assert stat.S_IMODE((work / "salt.txt").stat().st_mode) == 0o600
    assert bc.main(seal_args) == 1  # create-only: second run refuses, no new salt
    assert "refusing to overwrite" in capsys.readouterr().err

    commit_args = [
        "commit", "--manifest", str(work / "sealed.json"),
        "--predictions", str(chain.preds), "--detector-spec", str(chain.spec),
        "--pipeline-id", "geometry-v0", "--out", str(work / "commitment.json"),
    ]
    assert bc.main(commit_args) == 0
    assert bc.main(commit_args) == 1
    assert bc.main(["anchor", "--commitment", str(work / "commitment.json"),
                    "--external-ref", "rfc3161:token", "--external-time",
                    "2026-10-05T10:00:02+00:00", "--out", str(work / "anchor.json")]) == 0
    assert bc.main(["reveal", "--manifest", str(work / "sealed.json"),
                    "--commitment", str(work / "commitment.json"),
                    "--predictions", str(chain.preds), "--truth-root", str(chain.truth),
                    "--salt-file", str(work / "salt.txt"),
                    "--attested-by", "A. Reviewer", "--attest-truth-unseen",
                    "--out", str(work / "reveal.json")]) == 0
    assert bc.main(["report", "--manifest", str(work / "sealed.json"),
                    "--commitment", str(work / "commitment.json"),
                    "--reveal", str(work / "reveal.json"),
                    "--anchor", str(work / "anchor.json"),
                    "--out", str(work / "report.json")]) == 0
    report = json.loads((work / "report.json").read_text())
    assert report["verdict"] == "sealed-order-anchored"
    assert (work / "salt.txt").read_text().strip() not in json.dumps(report)


def test_cli_reveal_refuses_without_writing_when_predictions_moved(tmp_path, monkeypatch):
    chain = Chain(tmp_path / "fixture")
    work = tmp_path / "work"
    work.mkdir()
    (work / "sealed.json").write_text(json.dumps(chain.manifest))
    (work / "commitment.json").write_bytes(chain.commitment_path.read_bytes())
    (work / "salt.txt").write_text(chain.salt)
    (chain.preds / "surface" / "mesh.txt").write_bytes(b"edited")
    monkeypatch.setattr(bc, "utc_now", at(T_REVEAL))
    code = bc.main(["reveal", "--manifest", str(work / "sealed.json"),
                    "--commitment", str(work / "commitment.json"),
                    "--predictions", str(chain.preds), "--truth-root", str(chain.truth),
                    "--salt-file", str(work / "salt.txt"), "--out", str(work / "reveal.json")])
    assert code == 1
    assert not (work / "reveal.json").exists()


def test_cli_attestation_flags_must_come_together(tmp_path, capsys):
    code = bc.main(["reveal", "--manifest", "m", "--commitment", "c", "--predictions", "p",
                    "--truth-root", "t", "--salt-file", "s", "--attest-truth-unseen",
                    "--out", str(tmp_path / "r.json")])
    assert code == 1
    assert "requires --attested-by" in capsys.readouterr().err


# -- malformed input fails closed ---------------------------------------------


def test_malformed_commitment_fields_raise_instead_of_crashing(chain):
    for field, value in (
        ("pipeline", "geometry-v0"),
        ("pipeline", {"id": "p"}),
        ("pipeline", {"id": "p", "config_sha256": "nothex"}),
        ("development_truth_used", "dev-calibration-strip"),
        ("development_truth_used", [3]),
        ("benchmark_id", "bad id with spaces"),
    ):
        forged = _rehash_commitment(dict(chain.commitment, **{field: value}))
        with pytest.raises(bc.BlindControlError):
            chain.report(None, commitment=forged)


def test_commitment_for_another_benchmark_or_volume_is_not_blind(chain):
    for field in ("benchmark_id", "volume_id"):
        forged = _rehash_commitment(dict(chain.commitment, **{field: "some-other-thing"}))
        report = chain.report(None, commitment=forged)
        assert report["verdict"] == "not-blind"
        assert any("different benchmark or volume" in v for v in report["violations"])


def test_nan_in_a_manifest_is_a_contract_error_not_a_crash(tmp_path):
    path = tmp_path / "m.json"
    text = NIST_MANIFEST.read_text().replace('"slice_count": 620', '"slice_count": NaN')
    path.write_text(text)
    assert bc.main(["validate", "--manifest", str(path)]) == 1


def test_cli_missing_files_exit_cleanly(tmp_path, capsys):
    assert bc.main(["validate", "--manifest", str(tmp_path / "absent.json")]) == 1
    chain = Chain(tmp_path / "fixture")
    work = tmp_path / "work"
    work.mkdir()
    (work / "sealed.json").write_text(json.dumps(chain.manifest))
    (work / "commitment.json").write_bytes(chain.commitment_path.read_bytes())
    code = bc.main(["reveal", "--manifest", str(work / "sealed.json"),
                    "--commitment", str(work / "commitment.json"),
                    "--predictions", str(chain.preds), "--truth-root", str(chain.truth),
                    "--salt-file", str(work / "no-salt.txt"), "--out", str(work / "r.json")])
    assert code == 1
    assert "error:" in capsys.readouterr().err
    assert not (work / "r.json").exists()
