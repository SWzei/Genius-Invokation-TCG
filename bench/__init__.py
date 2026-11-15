"""Benchmark: suites of paired games + engine-verified decision scenarios.

See ``docs/howto/benchmark.md``. Strength *certification* of a pure policy stays
with ``scripts.eval_protocol`` (``docs/EVAL_PROTOCOL.md``); this package measures
any policy spec -- including LLM players -- on a fixed, versioned set of cells and
reports legality, latency and cost next to the win rates.
"""
