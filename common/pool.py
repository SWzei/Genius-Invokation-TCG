"""Process-pool map that recycles workers without ``max_tasks_per_child``.

Engine replays leak memory, so long jobs recycle their worker processes. On Python
3.12.3 (the project venv) ``ProcessPoolExecutor(max_tasks_per_child=...)`` can deadlock
when it replaces a retired worker (CPython gh-115634): the job then sleeps forever with
no worker processes. ``recycled_map`` gets the same effect safely by running the tasks in
batches, each batch in a fresh executor.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Iterable, Iterator


def recycled_map(fn: Callable[[Any], Any], tasks: Iterable[Any], *, workers: int = 2,
                 tasks_per_child: int = 4) -> Iterator[Any]:
    """Like ``pool.map(fn, tasks)`` (results in task order, streamed batch by batch);
    each worker process handles at most about ``tasks_per_child`` tasks."""
    workers = max(1, int(workers))
    batch = workers * max(1, int(tasks_per_child))
    items = list(tasks)
    for start in range(0, len(items), batch):
        with ProcessPoolExecutor(max_workers=workers) as pool:
            yield from pool.map(fn, items[start:start + batch])
