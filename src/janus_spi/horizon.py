from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
from scipy.constants import G, c, hbar, k as k_B
from sklearn.linear_model import SGDRegressor


SOLAR_MASS_KG = 1.98847e30


def hawking_temperature_schwarzschild(mass_kg: np.ndarray | float) -> np.ndarray:
    """Hawking temperature for a non-rotating, uncharged black hole.

    T_H = hbar c^3 / (8 pi G M k_B)

    This is a theoretical/synthetic teacher relation, not an observed astrophysical label.
    """
    mass = np.asarray(mass_kg, dtype=float)
    if np.any(mass <= 0):
        raise ValueError("mass_kg must be positive")
    return hbar * c**3 / (8.0 * np.pi * G * mass * k_B)


def schwarzschild_horizon_area(mass_kg: np.ndarray | float) -> np.ndarray:
    """Classical Schwarzschild horizon area A = 16 pi (GM/c^2)^2."""
    mass = np.asarray(mass_kg, dtype=float)
    if np.any(mass <= 0):
        raise ValueError("mass_kg must be positive")
    rg = G * mass / c**2
    return 16.0 * np.pi * rg**2


def kerr_horizon_area(mass_kg: np.ndarray | float, chi: np.ndarray | float) -> np.ndarray:
    """Classical Kerr horizon area for dimensionless spin chi in [-1, 1].

    A = 8 pi (GM/c^2)^2 (1 + sqrt(1-chi^2)).
    """
    mass = np.asarray(mass_kg, dtype=float)
    spin = np.asarray(chi, dtype=float)
    if np.any(mass <= 0):
        raise ValueError("mass_kg must be positive")
    if np.any(np.abs(spin) > 1.0):
        raise ValueError("Kerr dimensionless spin requires abs(chi) <= 1")
    rg = G * mass / c**2
    return 8.0 * np.pi * rg**2 * (1.0 + np.sqrt(1.0 - spin**2))


def area_theorem_delta(
    mass1_kg: float,
    chi1: float,
    mass2_kg: float,
    chi2: float,
    final_mass_kg: float,
    final_chi: float,
) -> Dict[str, float | bool]:
    """Classical area bookkeeping for a candidate binary-black-hole merger.

    Real-data use must propagate posterior uncertainty; this scalar helper is mainly for
    synthetic/unit tests and must not coerce observations into theorem compliance.
    """
    a1 = float(kerr_horizon_area(mass1_kg, chi1))
    a2 = float(kerr_horizon_area(mass2_kg, chi2))
    af = float(kerr_horizon_area(final_mass_kg, final_chi))
    delta = af - (a1 + a2)
    return {
        "area_initial_1_m2": a1,
        "area_initial_2_m2": a2,
        "area_final_m2": af,
        "delta_area_m2": delta,
        "nondecrease": bool(delta >= 0.0),
    }


def synthetic_hawking_dataset(
    n: int = 4096,
    mass_min_solar: float = 1.0,
    mass_max_solar: float = 1.0e10,
    relative_temperature_noise: float = 0.02,
    seed: int = 117,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, object]]:
    """Generate a frozen synthetic teacher set across a log-uniform mass range.

    X is log10(T/K), y is log10(M/kg). Noise is applied only to temperature.
    """
    if n < 8:
        raise ValueError("n must be >= 8")
    if not (0.0 <= relative_temperature_noise < 1.0):
        raise ValueError("relative_temperature_noise must be in [0,1)")
    rng = np.random.default_rng(seed)
    log_m_solar = rng.uniform(np.log10(mass_min_solar), np.log10(mass_max_solar), size=n)
    mass_kg = (10.0**log_m_solar) * SOLAR_MASS_KG
    temperature = hawking_temperature_schwarzschild(mass_kg)
    if relative_temperature_noise:
        temperature = temperature * (1.0 + rng.normal(0.0, relative_temperature_noise, size=n))
        temperature = np.maximum(temperature, np.finfo(float).tiny)
    X = np.log10(temperature).reshape(-1, 1)
    y = np.log10(mass_kg)
    manifest = {
        "generator": "synthetic_hawking_dataset.v1",
        "n": n,
        "mass_min_solar": mass_min_solar,
        "mass_max_solar": mass_max_solar,
        "relative_temperature_noise": relative_temperature_noise,
        "seed": seed,
        "claim_ceiling": "THEORY_SURROGATE_ONLY",
    }
    manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    return X, y, manifest


@dataclass
class HawkingSyntheticSurrogate:
    """Tiny incremental surrogate used only to prove H1 learning mechanics."""

    random_state: int = 117

    def __post_init__(self) -> None:
        self.model = SGDRegressor(
            loss="squared_error",
            penalty="l2",
            alpha=1e-6,
            learning_rate="adaptive",
            eta0=1e-3,
            random_state=self.random_state,
        )
        self.fitted = False
        self.version = 0

    @staticmethod
    def _x(log_temperature: np.ndarray) -> np.ndarray:
        # Center around the rough astrophysical scale to keep SGD numerically tame.
        return np.asarray(log_temperature, dtype=float).reshape(-1, 1) + 8.0

    @staticmethod
    def _y(log_mass_kg: np.ndarray) -> np.ndarray:
        return np.asarray(log_mass_kg, dtype=float).ravel() - 30.0

    def partial_fit(self, X_log_temperature: np.ndarray, y_log_mass_kg: np.ndarray) -> None:
        self.model.partial_fit(self._x(X_log_temperature), self._y(y_log_mass_kg))
        self.fitted = True
        self.version += 1

    def predict_log_mass_kg(self, X_log_temperature: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise ValueError("surrogate has not been trained")
        return self.model.predict(self._x(X_log_temperature)) + 30.0
