"""Shared behavioral contract for state repositories (JSON file and Postgres).

Each contract function takes a zero-arg ``make_repo`` factory returning a FRESH
repository view over the SAME underlying store (file path or DSN). The JSON
tests (test_repository_robustness.py) prove the contract against today's
behavior; the Postgres tests (test_pg_repository.py) reuse it verbatim — both
backends must satisfy every function.

The assertions are ported from the existing repository tests
(test_repository_robustness.py / test_embodied_platform.py), not invented.
"""
from __future__ import annotations

from api.embodied_platform.repository import empty_state


def contract_roundtrip(make_repo):
    """A mutate persists, returns the mutator's value, and a fresh view reads it back."""
    repo = make_repo()

    def add(state):
        state["datasets"].append({"id": "ds_c1", "name": "contract"})
        return "rv"

    assert repo.mutate(add) == "rv"
    assert any(d["id"] == "ds_c1" for d in make_repo().read()["datasets"])


def contract_mutate_return_passthrough(make_repo):
    """mutate() passes the mutator's return value through unchanged (ported from
    the parallel-writes test, where each writer's index round-trips through
    mutate)."""
    repo = make_repo()
    sentinel = {"token": "passthrough"}
    assert repo.mutate(lambda state: sentinel) is sentinel
    assert repo.mutate(lambda state: None) is None


def contract_unknown_key_dropped(make_repo):
    """Recognized-key whitelist: a key outside COLLECTIONS + system_settings
    written by a mutator must not survive a fresh read (JsonRepository's
    _read_unlocked only carries over recognized keys)."""
    repo = make_repo()

    def sneak(state):
        state["not_a_collection"] = [{"id": "evil"}]

    repo.mutate(sneak)
    state = make_repo().read()
    assert "not_a_collection" not in state
    assert sorted(state) == sorted(empty_state())


def contract_non_list_coerced(make_repo):
    """Ported from the '{"datasets":5}' corrupt-shape case in
    test_corrupt_state_file_degrades_to_empty_state_not_500: a present-but-
    non-list collection must read back as [] so a corrupt shape cannot make
    every read endpoint 500 while iterating."""
    repo = make_repo()

    def corrupt(state):
        state["datasets"] = 5

    repo.mutate(corrupt)
    assert make_repo().read()["datasets"] == []


def contract_sequential_mutates_compose(make_repo):
    """Mutate isolation: each mutate observes the previous mutate's committed
    effect (read-modify-write over the full state), so sequential mutates on
    fresh views compose instead of overwriting each other."""

    def add(dataset_id):
        def _mutate(state):
            state["datasets"].append({"id": dataset_id, "name": dataset_id})
            return len(state["datasets"])

        return _mutate

    assert make_repo().mutate(add("ds_seq_1")) == 1
    assert make_repo().mutate(add("ds_seq_2")) == 2
    assert [d["id"] for d in make_repo().read()["datasets"]] == ["ds_seq_1", "ds_seq_2"]


def contract_empty_state_defaults(make_repo):
    """A fresh store reads as empty_state(): every collection [] and
    system_settings at schema defaults — never a KeyError or missing key."""
    assert make_repo().read() == empty_state()


ALL_CONTRACTS = [
    contract_roundtrip,
    contract_mutate_return_passthrough,
    contract_unknown_key_dropped,
    contract_non_list_coerced,
    contract_sequential_mutates_compose,
    contract_empty_state_defaults,
]
