import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from janus_spi.horizon import (
    SOLAR_MASS_KG,
    area_theorem_delta,
    hawking_temperature_schwarzschild,
    kerr_horizon_area,
    schwarzschild_horizon_area,
    synthetic_hawking_dataset,
)


def test_hawking_temperature_decreases_with_mass():
    masses = np.array([1.0, 10.0, 100.0]) * SOLAR_MASS_KG
    t = hawking_temperature_schwarzschild(masses)
    assert t[0] > t[1] > t[2]
    assert np.all(t > 0)


def test_kerr_zero_spin_matches_schwarzschild_area():
    mass = 10.0 * SOLAR_MASS_KG
    a_s = float(schwarzschild_horizon_area(mass))
    a_k = float(kerr_horizon_area(mass, 0.0))
    assert np.isclose(a_s, a_k, rtol=1e-12)


def test_extremal_spin_has_smaller_area_at_fixed_mass():
    mass = 10.0 * SOLAR_MASS_KG
    assert float(kerr_horizon_area(mass, 0.999)) < float(kerr_horizon_area(mass, 0.0))


def test_area_helper_returns_explicit_non_decrease_boolean():
    result = area_theorem_delta(
        30 * SOLAR_MASS_KG,
        0.0,
        30 * SOLAR_MASS_KG,
        0.0,
        58 * SOLAR_MASS_KG,
        0.7,
    )
    assert "delta_area_m2" in result
    assert isinstance(result["nondecrease"], bool)


def test_synthetic_dataset_is_reproducible_by_seed():
    x1, y1, m1 = synthetic_hawking_dataset(n=64, seed=117)
    x2, y2, m2 = synthetic_hawking_dataset(n=64, seed=117)
    assert np.array_equal(x1, x2)
    assert np.array_equal(y1, y2)
    assert m1["manifest_sha256"] == m2["manifest_sha256"]
