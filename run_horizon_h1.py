from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.horizon import HawkingSyntheticSurrogate, synthetic_hawking_dataset


def sha256_json(obj: object) -> str:
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    train_X, train_y, train_manifest = synthetic_hawking_dataset(n=4096, seed=117)
    valid_X, valid_y, valid_manifest = synthetic_hawking_dataset(n=1024, seed=119)
    hold_X, hold_y, hold_manifest = synthetic_hawking_dataset(n=1024, seed=121)

    model = HawkingSyntheticSurrogate(random_state=117)
    for _ in range(30):
        model.partial_fit(train_X, train_y)

    valid_pred = model.predict_log_mass_kg(valid_X)
    valid_mae = float(mean_absolute_error(valid_y, valid_pred))

    # Freeze the decision rule before evaluating the final holdout in this script.
    gate = {
        "gate_id": "H1_HAWKING_SYNTHETIC_TEACHER",
        "metric": "MAE_LOG10_MASS_KG",
        "max_mae": 0.20,
        "negative_control": "SHUFFLED_TRAIN_LABELS_MUST_BE_WORSE_THAN_MODEL",
        "claim_ceiling": "THEORY_SURROGATE_ONLY",
    }
    gate_hash = sha256_json(gate)

    hold_pred = model.predict_log_mass_kg(hold_X)
    hold_mae = float(mean_absolute_error(hold_y, hold_pred))

    rng = np.random.default_rng(117)
    shuffled = HawkingSyntheticSurrogate(random_state=117)
    shuffled_y = np.array(train_y, copy=True)
    rng.shuffle(shuffled_y)
    for _ in range(30):
        shuffled.partial_fit(train_X, shuffled_y)
    negative_mae = float(mean_absolute_error(hold_y, shuffled.predict_log_mass_kg(hold_X)))

    status = "VERIFIED_RETURN" if hold_mae <= gate["max_mae"] and negative_mae > hold_mae else "REJECT"
    receipt = {
        "schema_id": "janus.horizon.h1.receipt.v1",
        "gate": gate,
        "gate_sha256": gate_hash,
        "train_manifest": train_manifest,
        "validation_manifest": valid_manifest,
        "holdout_manifest": hold_manifest,
        "model": {
            "class": "HawkingSyntheticSurrogate",
            "version": model.version,
            "random_state": model.random_state,
        },
        "validation_mae_log10_mass_kg": valid_mae,
        "holdout_mae_log10_mass_kg": hold_mae,
        "negative_control_mae_log10_mass_kg": negative_mae,
        "status": status,
        "scientific_boundary": [
            "SYNTHETIC_TEACHER_ONLY",
            "HAWKING_RADIATION_NOT_DIRECT_ASTROPHYSICAL_LABEL",
            "PASS_DOES_NOT_ESTABLISH_NEW_BLACK_HOLE_PHYSICS",
        ],
    }

    out_dir = Path("state") / "horizon_receipts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "H1_HAWKING_SYNTHETIC_TEACHER.latest.json"
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
