"""Independent exhaustive finite-shell oracle and local CPU timing, not FFT timing."""
import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np

from scrollq.e8_codec import BOOK, nearest


def exhaustive(x, radius):
    return np.concatenate([np.sum((a[:, None] - BOOK[None] * radius) ** 2, axis=2).argmin(1)
                           for a in np.array_split(x, max(1, len(x) // 128))])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    x = np.random.default_rng(712).normal(size=(32768, 8))
    times = {}
    results = {}
    for name, kernel in (("closed_form", nearest), ("coordinate_distance_oracle", exhaustive)):
        kernel(x[:256], 0.73)
        elapsed = []
        for _ in range(3):
            start = time.perf_counter()
            results[name] = kernel(x, 0.73)
            elapsed.append(time.perf_counter() - start)
        times[name] = float(np.median(elapsed))
    disagreements = int(np.count_nonzero(results["closed_form"] != results["coordinate_distance_oracle"]))
    if disagreements:
        raise ValueError("closed-form search disagrees with coordinate oracle")
    report = {"vectors": len(x), "dimensions": 8, "seed": 712, "radius": 0.73,
              "disagreements": disagreements, "median_seconds_three_runs": times,
              "local_cpu_speed_ratio": times["coordinate_distance_oracle"] / times["closed_form"],
              "input_sha256": hashlib.sha256(x.tobytes()).hexdigest(),
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "machine": platform.machine()},
              "scope": "This finite-shell CPU nearest-codeword kernel vs brute force; not GPU, FFT, neural inference, or Sussman's asymptotic algorithm."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
