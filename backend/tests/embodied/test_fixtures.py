"""Tests for the synthetic LeRobotDataset fixture builder."""
from __future__ import annotations

from tests.embodied import fixtures


def test_fixture_builds_and_loads(tmp_path):
    fixtures._self_test_fixture_loads(tmp_path)
