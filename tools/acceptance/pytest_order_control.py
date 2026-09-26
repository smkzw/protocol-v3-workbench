"""Zero-dependency pytest ordering plugin for A11 order-pollution work.

Loaded with ``-p pytest_order_control`` (put tools/acceptance on PYTHONPATH).
Options:
- ``--order-reverse``  reverse collection order;
- ``--order-seed=N``   shuffle collection order with a fixed seed
                       (random.Random(N).shuffle — deterministic per seed).

A seeded shuffle only proves stability for THAT seed, not for all
permutations; record the seed whenever used.
"""
from __future__ import annotations


def pytest_addoption(parser):
    group = parser.getgroup("gate")
    group.addoption("--order-reverse", action="store_true", default=False,
                    help="A11: run collected tests in reverse order")
    group.addoption("--order-seed", type=int, default=None,
                    help="A11: shuffle collection order with this fixed seed")


def pytest_collection_modifyitems(session, config, items):
    seed = config.getoption("order_seed")
    if seed is not None:
        import random
        random.Random(seed).shuffle(items)
    if config.getoption("order_reverse"):
        items.reverse()
