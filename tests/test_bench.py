"""Benchmark package (``bench``, PLAN D30): suites, report, scenarios, runner.

Fast tests need no engine game: suite structure and pinning, the report's
exclusion / pairing rules, quiz scoring, the scenario summary. Slow tests play
real games: one cell per kind of subject, the resumable runner, and a replay of
the shipped scenario set against the installed engine.
"""

from __future__ import annotations

import json
import os

import pytest

from bench.report import build_report, render_markdown
from bench.suite import BENCH_SEED_BASE, SUITE_DIR, Cell, build_suite, load_suite, subject_applies

POOL_SUITE = {
    "suite": {"name": "t", "seeds": 2},
    "groups": [{
        "name": "g", "decks": ["natlan_battleship", "unyielding_geo"],
        "opponents": [
            {"level": "L0", "name": "rand", "policy": "legal_random", "deck": "mirror"},
            {"level": "L2", "name": "exp", "policy": "expert:<deck>", "deck": "superconduct_aggro"},
        ],
    }],
}


# --------------------------------------------------------------------------- #
# suites
# --------------------------------------------------------------------------- #
def test_cells_are_a_paired_grid_on_reserved_seeds():
    suite = build_suite(POOL_SUITE)
    assert len(suite.cells) == 2 * 2 * 2 * 2                 # decks x opponents x seeds x sides
    assert len({c.key for c in suite.cells}) == len(suite.cells)
    assert all(c.seed >= BENCH_SEED_BASE for c in suite.cells)      # never seed 0, never a collection seed
    by_matchup: dict[tuple, set] = {}
    for cell in suite.cells:
        by_matchup.setdefault((cell.deck, cell.rep), set()).add(cell.seed)
        assert cell.opponent_policy in ("legal_random", "expert:superconduct_aggro")
        assert cell.opponent_deck == (cell.deck if cell.opponent == "rand" else "superconduct_aggro")
    assert all(len(seeds) == 1 for seeds in by_matchup.values())   # one deal per (deck, replicate): opponents share it
    assert len({next(iter(s)) for s in by_matchup.values()}) == 4  # and decks / replicates do not share deals
    assert {c.side for c in suite.cells} == {0, 1}
    assert suite.fingerprint == build_suite(POOL_SUITE).fingerprint
    changed = json.loads(json.dumps(POOL_SUITE))
    changed["groups"][0]["opponents"][1]["deck"] = "double_geo_navia"
    assert build_suite(changed).fingerprint != suite.fingerprint
    duplicate = json.loads(json.dumps(POOL_SUITE))
    duplicate["groups"][0]["opponents"][1]["name"] = "rand"
    with pytest.raises(ValueError, match="duplicate"):
        build_suite(duplicate)


@pytest.mark.parametrize("name,cells", [("lite", 56), ("core", 480), ("home", 16)])
def test_shipped_suites_load_from_their_lock_without_tournament_data(name, cells, monkeypatch):
    monkeypatch.delenv("GITCG_DATA_RELEASE", raising=False)
    suite = load_suite(name)
    assert suite.source == f"{name}.lock.json" and len(suite.cells) == cells
    recorded = json.loads((SUITE_DIR / f"{name}.lock.json").read_text(encoding="utf-8"))["fingerprint"]
    assert suite.fingerprint == recorded
    assert all(c.seed >= BENCH_SEED_BASE for c in suite.cells)
    humans = [c for c in suite.cells if c.deck_kind == "human"]
    for cell in humans:
        entry = suite.decks[cell.deck]
        assert len(entry["characters"]) == 3 and len(entry["cards"]) == 30 and entry["split"] == "test"
        assert cell.opponent_deck in suite.decks and cell.opponent_deck != cell.deck
        assert not subject_applies("expert:<deck>", cell)        # no script for a deck nobody scripted
        assert subject_applies("heuristic", cell) and subject_applies("llm:mock", cell)
    if name != "home":
        assert humans and {c.version for c in humans} >= {"", "v6.3.0"}     # native rules and latest rules
        natives = {suite.decks[c.deck]["native_version"] for c in humans if c.version}
        assert natives == {c.version for c in humans if c.version}
    tampered = dict(recorded_lock := json.loads((SUITE_DIR / f"{name}.lock.json").read_text(encoding="utf-8")))
    tampered["cells"] = recorded_lock["cells"][:-1]
    from bench.suite import suite_from_lock

    with pytest.raises(ValueError, match="fingerprint"):
        suite_from_lock(tampered, source="tampered")


def test_suites_and_scenarios_never_share_a_seed():
    from bench.scenarios import SCENARIO_SEED_BASE, load_set

    seeds: dict[str, set[int]] = {name: {c.seed for c in load_suite(name).cells} for name in ("lite", "core", "home")}
    scenario_seeds = {int(s["seed"]) for s in load_set("v1")["sources"]}
    assert min(scenario_seeds) >= SCENARIO_SEED_BASE
    assert not scenario_seeds & set().union(*seeds.values())
    assert not seeds["home"] & (seeds["lite"] | seeds["core"])


@pytest.mark.skipif(not os.environ.get("GITCG_DATA_RELEASE"), reason="GITCG_DATA_RELEASE not set")
@pytest.mark.parametrize("name", ["lite", "home"])
def test_lock_matches_what_the_suite_file_resolves_to(name):
    assert load_suite(name, use_lock=False).fingerprint == load_suite(name).fingerprint


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def _row(subject: str, cell: Cell, score, **extra):
    return {"subject": subject, "cell": cell.key, **cell.as_dict(), "score": score, "error": None,
            "truncated": False, "rounds": 6, "engine_fallbacks": 0, "wall_seconds": 1.0, **extra}


def _llm_summary(asked: int, first_legal: int, used: int) -> dict:
    return {"asked": asked, "first_reply_legal": first_legal, "llm_rate": used / asked,
            "by_source": {"llm": used, "fallback": asked - used, "forced": 3},
            "errors": {"api:timeout": asked - used} if used < asked else {},
            "first_errors": {"choice 9 is not one of the listed options": asked - first_legal} if first_legal < asked else {},
            "by_request": {"action": {"asked": asked, "first_legal": first_legal, "used": used}},
            "decision_seconds": {"p50": 2.0, "p90": 5.0, "max": 9.0, "sum": 2.0 * asked},
            "usage": {"calls": asked + 1, "errors": asked - used, "prompt_tokens": 1000 * asked,
                      "completion_tokens": 100 * asked, "total_seconds": 2.0 * asked, "cost": 0.01 * asked,
                      "retries": 1, "reasoning_tokens": 60 * asked, "cached_tokens": 10 * asked}}


def test_report_pairs_on_cells_and_excludes_games_the_subject_did_not_play():
    suite = build_suite(POOL_SUITE)
    cells = suite.cells
    rows = [_row("base", c, 1.0 if i % 2 == 0 else 0.0) for i, c in enumerate(cells)]
    model_scores = [1.0] * len(cells)
    for i, cell in enumerate(cells):
        rows.append(_row("llm:x", cell, model_scores[i], llm=_llm_summary(50, 49, 50), degraded=False))
    # one game where the model mostly did not answer (its fallback played), one that crashed
    rows[len(cells) + 1] = _row("llm:x", cells[1], 1.0, llm=_llm_summary(50, 10, 10), degraded=True)
    rows[len(cells) + 3] = {**_row("llm:x", cells[3], None), "error": "boom"}
    # a retried cell: the later row replaces the earlier one
    rows.append(_row("base", cells[0], 0.0))
    report = build_report(suite, rows, ["base", "llm:x"])
    base, model = report["subjects"]["base"], report["subjects"]["llm:x"]
    assert base["games"] == 16 and base["win_rate"]["n"] == 16 and base["win_rate"]["rate"] == pytest.approx(7 / 16)
    assert model["games"] == 16 and model["valid_games"] == 14
    assert model["degraded_games"] == 1 and model["invalid_games"] == 1
    assert model["win_rate"]["n"] == 14 and model["win_rate"]["rate"] == 1.0
    assert set(model["by_level"]) == {"L0", "L2"} and set(model["by_side"]) == {"0", "1"}
    paired = report["paired_vs_reference"]["llm:x"]
    assert report["reference"] == "base" and paired["n_pairs"] == 14      # only cells valid for both
    # base lost cells 0 (the retry), 1, 3, 5, ... 15; cells 1 and 3 are not shared, so the model is
    # better on 7 of the 14 shared cells and equal on the other 7
    assert paired["better"] == 7 and paired["worse"] == 0 and paired["same"] == 7
    assert paired["delta"] == pytest.approx(0.5, abs=1e-4)
    assert paired["sign_test_p"] == pytest.approx(2 / 2 ** 7, abs=1e-4)
    stats = model["model"]
    assert stats["decisions_asked"] == 15 * 50                             # the crashed game has no summary
    assert stats["first_reply_legal_rate"] == pytest.approx((14 * 49 + 10) / 750, abs=1e-4)
    assert stats["answer_used_rate"] == pytest.approx((14 * 50 + 10) / 750, abs=1e-4)
    assert stats["errors"] == {"api:timeout": 40} and stats["cost_per_game"] == pytest.approx(0.5)
    assert stats["reasoning_tokens"] == 15 * 50 * 60
    text = render_markdown({**report, "tag": "t"})
    assert "Paired difference vs `base`" in text and "degraded 1" in text and "first reply legal" in text
    # rows of cells that are not in this suite are ignored
    other = Cell("zz", "natlan_battleship", "rand", "L0", "legal_random", "natlan_battleship", "", 99, 0)
    assert build_report(suite, rows + [_row("base", other, 1.0)], ["base"])["subjects"]["base"]["games"] == 16


def test_runner_refuses_to_resume_against_a_changed_suite(tmp_path, monkeypatch):
    from bench.run import main

    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GITCG_REPORTS_DIR", str(tmp_path / "reports"))
    run_dir = tmp_path / "data" / "bench" / "x"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps({"fingerprint": "0000", "subjects": ["heuristic"]}))
    with pytest.raises(SystemExit, match="new --tag"):
        main(["--suite", "home", "--tag", "x", "--report-only"])
    assert main(["--suite", "home", "--tag", "fresh", "--report-only"]) == 0          # empty run: empty report
    report = json.loads((tmp_path / "reports" / "bench" / "fresh.json").read_text(encoding="utf-8"))
    assert report["subjects"] == {} and report["suite"]["cells"] == 16


# --------------------------------------------------------------------------- #
# scenarios
# --------------------------------------------------------------------------- #
def test_quiz_scoring_is_exact_and_the_hidden_probe_only_accepts_unknown():
    from bench.scenarios import _quiz_score

    key = {"my_active": "玛薇卡", "my_active_hp": 7, "opp_active_hp": 5, "my_dice": 4, "my_hand": 7,
           "opp_hand": 7, "round": 3, "opp_has_card": "unknown", "_probe_card": "交给我吧！"}
    good = {"my_active": "【玛薇卡】", "my_active_hp": "7", "opp_active_hp": 5, "my_dice": 4, "my_hand": 7,
            "opp_hand": 7, "round": 3, "opp_has_card": "Unknown"}
    assert all(_quiz_score(key, good).values()) and "_probe_card" not in _quiz_score(key, good)
    bad = {**good, "my_active_hp": 6, "opp_has_card": "yes", "round": "three"}
    scores = _quiz_score(key, bad)
    assert [k for k, v in scores.items() if not v] == ["my_active_hp", "round", "opp_has_card"]
    assert not any(_quiz_score(key, None).values())                      # no parseable answer: all wrong
    assert "opp_has_card" not in _quiz_score({k: v for k, v in key.items() if k != "opp_has_card"}, good)


def test_scenario_summary_keeps_quality_agreement_and_generators_apart():
    from bench.scenarios import render_markdown as render, summarise

    scenario_set = {"name": "t", "source_games": 1, "counts": {"lethal": 2, "agreement": 2, "quiz": 1},
                    "lethal_chance_level": 0.25, "sources": [{"pilots": ["expert:a", "expert:b"]}],
                    "scenarios": [{"id": "lethal-0", "kind": "lethal", "is_final_decision": True},
                                  {"id": "lethal-1", "kind": "lethal", "is_final_decision": False},
                                  {"id": "agreement-2", "kind": "agreement"}, {"id": "agreement-3", "kind": "agreement"},
                                  {"id": "quiz-4", "kind": "quiz"}]}
    rows = [
        {"subject": "heuristic", "id": "lethal-0", "kind": "lethal", "correct": True, "chance": 0.25},
        {"subject": "heuristic", "id": "lethal-1", "kind": "lethal", "correct": False, "chance": 0.25},
        {"subject": "heuristic", "id": "agreement-2", "kind": "agreement", "agree": True},
        {"subject": "heuristic", "id": "agreement-3", "kind": "agreement", "failed": "worker failed"},
        {"subject": "llm:m", "id": "lethal-0", "kind": "lethal", "correct": False, "chance": 0.25,
         "first_reply_legal": True, "source": "llm", "latency_seconds": 2.0, "prompt_tokens": 900,
         "completion_tokens": 80, "cost": 0.002},
        # a later row for the same (subject, scenario) replaces the earlier one
        {"subject": "llm:m", "id": "lethal-0", "kind": "lethal", "correct": True, "chance": 0.25,
         "first_reply_legal": True, "source": "llm", "latency_seconds": 2.0, "prompt_tokens": 900,
         "completion_tokens": 80, "cost": 0.002},
        {"subject": "llm:m", "id": "lethal-1", "kind": "lethal", "correct": True, "chance": 0.25,
         "first_reply_legal": False, "source": "fallback", "latency_seconds": 4.0},
        {"subject": "llm:m", "id": "quiz-4", "kind": "quiz", "ok": True, "probe_answer": "no",
         "scores": {"my_active": True, "my_dice": False, "opp_has_card": False}, "latency_seconds": 1.0},
        {"subject": "expert:<deck>", "id": "lethal-0", "kind": "lethal", "correct": True, "chance": 0.25},
    ]
    report = summarise(rows, ["heuristic", "llm:m", "expert:<deck>", "absent"], scenario_set)
    table = report["subjects"]
    assert "absent" not in table and "sources" not in report["set"] and "scenarios" not in report["set"]
    assert table["heuristic"]["lethal"]["rate"] == 0.5 and table["heuristic"]["lethal_chance"] == 0.25
    assert table["heuristic"]["expert_agreement"]["n"] == 1 and table["heuristic"]["failed"] == 1
    assert table["heuristic"]["lethal_by_position"]["final"]["rate"] == 1.0
    assert table["heuristic"]["lethal_by_position"]["earlier"]["rate"] == 0.0
    assert "quiz" not in table["heuristic"] and "model" not in table["heuristic"]
    model = table["llm:m"]
    assert model["lethal"] == {"n": 2, "rate": 1.0, "ci95": model["lethal"]["ci95"]}
    assert model["quiz"]["state_reading"]["n"] == 2 and model["quiz"]["state_reading"]["rate"] == 0.5
    assert model["quiz"]["hidden_info_probe"]["rate"] == 0.0 and model["quiz"]["probe_answers"] == {"no": 1}
    assert model["model"]["decisions_asked"] == 2 and model["model"]["first_reply_legal_rate"] == 0.5
    assert model["model"]["answer_used_rate"] == 0.5
    assert table["expert:<deck>"]["is_generator"] and not model["is_generator"]
    # paired on the scenarios both answered: heuristic 1/2, model 2/2
    paired = report["paired_lethal"]["llm:m"]
    assert (paired["vs"], paired["n"], paired["better"], paired["worse"]) == ("heuristic", 2, 1, 0)
    text = render(report)
    assert "(generator)" in text and "expert agreement" in text and "similarity to the scripted pilot" in text


# --------------------------------------------------------------------------- #
# slow: real games
# --------------------------------------------------------------------------- #
def _cell(suite_name: str, **match) -> tuple[dict, dict]:
    suite = load_suite(suite_name)
    cell = next(c for c in suite.cells if all(getattr(c, k) == v for k, v in match.items()))
    return cell.as_dict(), suite.decks


@pytest.mark.slow
def test_one_cell_per_kind_of_subject_and_the_degraded_flag():
    from bench.play import play_cell

    cell, decks = _cell("lite", group="ladder-pool", opponent="legal_random@mirror", side=0, rep=0)
    answered = play_cell("llm:mock:first", cell, decks)
    assert answered["score"] in (0.0, 0.5, 1.0) and answered["error"] is None and answered["engine_fallbacks"] == 0
    assert answered["degraded"] is False and answered["fatal"] is None
    assert answered["llm"]["asked"] > 10 and answered["llm"]["first_reply_legal"] == answered["llm"]["asked"]
    # a model that never answers: the game is played by the fallback and must be flagged, not counted
    silent = play_cell("llm:mock:error", cell, decks)
    assert silent["score"] is not None and silent["engine_fallbacks"] == 0
    assert silent["degraded"] is True and silent["llm"]["llm_rate"] == 0.0
    assert silent["llm"]["first_reply_legal"] == 0 and silent["llm"]["first_errors"] == {"api:network": silent["llm"]["asked"]}
    # same cell, same seeds: a scripted subject is deterministic
    first, again = play_cell("heuristic", cell, decks), play_cell("heuristic", cell, decks)
    assert (first["winner"], first["rounds"], first["decisions"]) == (again["winner"], again["rounds"], again["decisions"])
    assert "degraded" in first and first["degraded"] is False and first["llm"] == {}
    # a cell that cannot be played is a row, not a crash
    broken = play_cell("no_such_policy", cell, decks)
    assert broken["score"] is None and broken["error"]


@pytest.mark.slow
def test_held_out_human_deck_under_its_native_rules_version():
    from bench.play import play_cell

    cell, decks = _cell("lite", group="heldout-native", opponent="heuristic@human", side=1, rep=0)
    assert cell["version"] == "v6.3.0" and cell["deck"].startswith("human:")
    row = play_cell("heuristic", cell, decks)
    assert row["error"] is None and row["score"] in (0.0, 0.5, 1.0) and row["engine_fallbacks"] == 0


def test_compare_pairs_runs_made_under_different_tags_and_refuses_other_suites(tmp_path, monkeypatch, capsys):
    from bench.compare import main

    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GITCG_REPORTS_DIR", str(tmp_path / "reports"))
    suite = load_suite("home")

    def write(tag: str, subject: str, cells, score, fingerprint=suite.fingerprint):
        root = tmp_path / "data" / "bench" / tag
        root.mkdir(parents=True)
        (root / "meta.json").write_text(json.dumps({"suite": {"name": "home"}, "fingerprint": fingerprint}),
                                        encoding="utf-8")
        rows = [dict(c.as_dict(), subject=subject, cell=c.key, score=score(i), error=None, truncated=False,
                     degraded=False, engine_fallbacks=0) for i, c in enumerate(cells)]
        (root / "games.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    write("model", "llm:mock:first", suite.cells[:6], lambda i: 1.0)             # the model played 6 cells
    write("refs", "heuristic", suite.cells, lambda i: float(i % 2))              # the reference played all 16
    assert main(["--tags", "model", "refs", "--reference", "llm:mock:first", "--common-cells", "--out", "cmp"]) == 0
    report = json.loads((tmp_path / "reports" / "bench" / "cmp.json").read_text(encoding="utf-8"))
    assert report["subjects"]["heuristic"]["games"] == 6                          # only the model's cells
    paired = report["paired_vs_reference"]["heuristic"]
    assert (paired["n_pairs"], paired["better"], paired["worse"]) == (6, 0, 3) and paired["delta"] == -0.5
    assert "heuristic" in capsys.readouterr().out
    write("other", "legal_random", suite.cells[:2], lambda i: 0.0, fingerprint="deadbeef")
    with pytest.raises(SystemExit, match="not comparable"):
        main(["--tags", "model", "other", "--out", "bad"])


@pytest.mark.slow
def test_runner_plays_resumes_and_reports(tmp_path, monkeypatch):
    from bench.run import main

    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GITCG_REPORTS_DIR", str(tmp_path / "reports"))
    args = ["--suite", "home", "--tag", "t", "--max-cells", "2", "--workers", "2"]
    assert main(args + ["--subjects", "legal_random", "llm:mock:random"]) == 0
    games = tmp_path / "data" / "bench" / "t" / "games.jsonl"
    rows = [json.loads(line) for line in games.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4 and {r["subject"] for r in rows} == {"legal_random", "llm:mock:random"}
    assert all(r["score"] is not None and r["seed"] >= BENCH_SEED_BASE for r in rows)
    calls = tmp_path / "data" / "bench" / "t" / "calls.jsonl"
    logged = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    assert logged and all("prompt" not in entry and entry["profile"] == "mock:random" for entry in logged)
    # resuming plays nothing new; adding a subject plays only its cells
    assert main(args + ["--subjects", "legal_random", "heuristic"]) == 0
    rows = [json.loads(line) for line in games.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 6
    report = json.loads((tmp_path / "reports" / "bench" / "t.json").read_text(encoding="utf-8"))
    assert list(report["subjects"]) == ["legal_random", "llm:mock:random", "heuristic"]
    assert report["subjects"]["llm:mock:random"]["model"]["first_reply_legal_rate"] == 1.0
    assert report["paired_vs_reference"]["heuristic"]["n_pairs"] == 2
    # the call budget stops the run before the next game starts
    assert main(["--suite", "home", "--tag", "t", "--max-cells", "4", "--workers", "1", "--max-calls", "1",
                 "--subjects", "llm:mock:random"]) == 0
    report = json.loads((tmp_path / "reports" / "bench" / "t.json").read_text(encoding="utf-8"))
    assert "max_calls reached" in report["stopped"]
    assert len(games.read_text(encoding="utf-8").splitlines()) == 6


@pytest.mark.slow
def test_shipped_scenarios_replay_on_this_engine_and_the_lethal_answers_hold():
    """The set stores how to reach each decision; the engine must still lead there,
    and playing a recorded winning option must still win on the spot."""
    from bench.scenarios import boundaries, context_at, load_set, option_response, option_wins_now

    scenario_set = load_set("v1")
    lethal = [s for s in scenario_set["scenarios"] if s["kind"] == "lethal" and s["n_options"] > len(s["winning"])]
    scenario = next(s for s in lethal if not s["is_final_decision"])       # the generator did not have to take it
    source = scenario_set["sources"][scenario["source"]]
    built = context_at(source, scenario["seat"], scenario["ordinal"])
    assert len(built.context.legal_low_level_codes) == scenario["n_options"]
    assert int(built.context.acting_player) == scenario["seat"]
    points = boundaries(source)
    wins = [i for i in range(scenario["n_options"])
            if option_wins_now(source, points, scenario["seat"], scenario["ordinal"], option_response(built, i))]
    assert wins == scenario["winning"]
    # the prompt for that decision is built from the seat's view and lists every option
    from agents.llm_policy import build_messages
    from reps.describe import DecisionDescriber

    messages, protocol, listed = build_messages(built.context, DecisionDescriber())
    assert protocol == "index" and listed == scenario["n_options"]
    assert f"[{scenario['n_options'] - 1}]" in messages[-1]["content"]


def test_report_paths_are_repo_relative(tmp_path):
    from bench.report import display_path
    from common.paths import REPO_ROOT

    assert display_path(REPO_ROOT / "data" / "bench" / "t" / "games.jsonl") == "data/bench/t/games.jsonl"
    outside = tmp_path / "games.jsonl"
    assert display_path(outside) == str(outside)
