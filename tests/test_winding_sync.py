import json

import numpy as np
import pytest

from scrollq.winding_sync import (
    Graph,
    SyncError,
    clean_truth,
    digest,
    main,
    node_accuracy,
    positive_control,
    run_campaign,
    solve_bfs,
    solve_l1,
    synthetic_graph,
)


def _graph(edges, nodes=None):
    doc = {"schema_version": 1, "edges": [
        {"edge_id": f"e{k}", "i": i, "j": j, "d": d}
        for k, (i, j, d) in enumerate(edges)]}
    if nodes:
        doc["nodes"] = nodes
    return Graph.from_document(doc)


def test_positive_control_passes():
    ctl = positive_control()
    assert ctl["passed"], ctl


def test_l1_outvotes_one_wrong_edge_that_bfs_trusts():
    # a-b is wrong (+1); the two-hop path a-c-b and a-d-b both say d_ab = 0.
    g = _graph([("a", "b", 1), ("a", "c", 0), ("c", "b", 0),
                ("a", "d", 0), ("d", "b", 0)])
    wb, _ = solve_bfs(g)
    wl, info = solve_l1(g)
    ia, ib = g.index["a"], g.index["b"]
    assert wb[ia] - wb[ib] == 1  # BFS takes the first (wrong) tree edge
    assert wl[ia] - wl[ib] == 0
    assert info["edges_with_residual"] == 1
    assert info["max_integrality_gap"] <= 1e-6


def test_l1_solution_is_integral_and_gauge_fixed_per_component():
    g = _graph([("a", "b", 3), ("b", "c", -2), ("x", "y", 5)])
    w, _ = solve_l1(g)
    assert w.dtype.kind == "i"
    assert w[g.index["a"]] == 0 and w[g.index["x"]] == 0
    assert g.n_components == 2


def test_bridges_and_cyclomatic_number():
    g = _graph([("a", "b", 0), ("b", "c", 0), ("c", "a", 0), ("c", "d", 1)])
    assert g.bridges() == {g.edges.index(next(
        e for e in g.edges if {e["i"], e["j"]} == {"c", "d"}))}
    assert g.cyclomatic == 1


def test_parallel_edges_are_not_bridges():
    g = _graph([("a", "b", 0), ("a", "b", 0)])
    assert g.bridges() == set()


def test_node_accuracy_ignores_global_gauge():
    g = _graph([("a", "b", 1), ("b", "c", 1)])
    t = np.array([2, 1, 0])
    assert node_accuracy(g, t + 7, t) == 1.0
    assert node_accuracy(g, np.array([2, 1, 5]), t) == pytest.approx(2 / 3)


@pytest.mark.parametrize("bad, match", [
    ({"edge_id": "e", "i": "a", "j": "a", "d": 0}, "self-loop"),
    ({"edge_id": "e", "i": "a", "j": "b", "d": 0.5}, "integer"),
    ({"edge_id": "e", "i": "a", "j": "b", "d": 1, "weight": 0}, "weight"),
    ({"edge_id": "e", "i": "a", "j": "b", "d": 1, "ink_prob": 0.4}, "ink"),
])
def test_graph_defects_fail_closed(bad, match):
    with pytest.raises(SyncError, match=match):
        Graph.from_document({"schema_version": 1, "edges": [bad]})


def test_ink_check_matches_words_not_substrings():
    g = Graph.from_document({"schema_version": 1, "edges": [
        {"edge_id": "e", "i": "a", "j": "b", "d": 1}],
        "provenance": {"linked_seeds": 3, "shrink": True}})
    assert len(g.edges) == 1
    with pytest.raises(SyncError, match="ink"):
        Graph.from_document({"schema_version": 1, "edges": [
            {"edge_id": "e", "i": "a", "j": "b", "d": 1}],
            "provenance": {"has_ink": True}})


def test_inconsistent_clean_graph_is_unverified():
    g = {"schema_version": 1, "edges": [
        {"edge_id": "e1", "i": "a", "j": "b", "d": 1},
        {"edge_id": "e2", "i": "b", "j": "c", "d": 1},
        {"edge_id": "e3", "i": "a", "j": "c", "d": 0}]}
    assert clean_truth(Graph.from_document(g))["consistent"] is False
    spec = {"schema_version": 1, "campaign_id": "x",
            "graph_sha256": digest(Graph.from_document(g).to_document()),
            "graph_source": "test", "rates": [0.1], "replicates": 1}
    assert run_campaign(spec, g)["verdict"] == "UNVERIFIED"


def _spec(graph, **kw):
    sha = digest(Graph.from_document(graph).to_document())
    return {"schema_version": 1, "campaign_id": "t", "graph_sha256": sha,
            "graph_source": "synthetic test", "rates": [0.05, 0.1],
            "magnitudes": [1, 2], "replicates": 3, "seed": 5, **kw}


def test_campaign_promotes_on_redundant_graph_and_reproduces_clean():
    graph = synthetic_graph(150, 3.0, 1)
    r = run_campaign(_spec(graph), graph)
    assert r["verdict"] == "PROMOTE"
    assert r["clean_reproduction"]["l1"]["node_accuracy"] == 1.0
    assert r["ink_consulted"] is False


def test_campaign_on_tree_has_no_redundancy():
    graph = synthetic_graph(60, 59 / 60, 1)
    r = run_campaign(_spec(graph), graph)
    assert r["verdict"] == "NO_REDUNDANCY"
    for c in r["cells"]:
        if c["status"] == "measured":
            assert c["l1_minus_bfs"] == 0.0


def test_campaign_refuses_graph_not_bound_by_spec():
    graph = synthetic_graph(50, 2.0, 1)
    spec = _spec(graph)
    graph["edges"][0]["d"] += 1
    with pytest.raises(SyncError, match="does not match"):
        run_campaign(spec, graph)


def test_campaign_is_deterministic():
    graph = synthetic_graph(80, 2.5, 2)
    a = run_campaign(_spec(graph), graph)
    b = run_campaign(_spec(graph), graph)
    assert a == b


def test_cli_solve_and_campaign(tmp_path):
    g = tmp_path / "g.json"
    assert main(["synthetic", "--nodes", "60", "--edges-per-node", "2.5",
                 "--out", str(g)]) == 0
    assert main(["solve", "--graph", str(g), "--out",
                 str(tmp_path / "w.json")]) == 0
    w = json.loads((tmp_path / "w.json").read_text())
    assert w["method"] == "l1" and len(w["windings"]) == 60
    (tmp_path / "s.json").write_text(json.dumps(_spec(json.loads(
        g.read_text()))))
    out = tmp_path / "r.json"
    assert main(["campaign", "--spec", str(tmp_path / "s.json"), "--graph",
                 str(g), "--out", str(out)]) == 0
    assert main(["campaign", "--spec", str(tmp_path / "s.json"), "--graph",
                 str(g), "--out", str(out)]) == 2  # create-only
    assert main(["self-test"]) == 0
