"""Measure the recommender against the fixed default it replaces.

    python bench.py                 # 500 seeded random workloads
    python bench.py --trials 2000
    python bench.py --json

The baseline is what an operator actually does: pick round robin, set the
quantum to 4, move on.  The question this answers is whether searching the
five algorithms and four quanta is worth the CPU it costs -- and by how much.
Every number in RESULTS.md comes from this file.
"""

import argparse
import json
import random
import statistics
import time

import scheduler
from scheduler import Process

BASELINE = ("rr", 4)          # what you get without thinking about it


def random_workload(rng, kind):
    """Three workload shapes, because the answer differs between them.

    uniform  - bursts all roughly the same length
    bursty   - a few long jobs among many short ones (the interactive case)
    batch    - everything arrives at t=0 (the overnight-job case)
    """
    n = rng.randint(3, 10)
    if kind == "uniform":
        return [Process(f"P{i}", rng.randint(0, 20), rng.randint(4, 8)) for i in range(n)]
    if kind == "bursty":
        return [
            Process(f"P{i}", rng.randint(0, 20),
                    rng.randint(15, 30) if rng.random() < 0.25 else rng.randint(1, 4))
            for i in range(n)
        ]
    return [Process(f"P{i}", 0, rng.randint(1, 25)) for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    report = {"seed": args.seed, "trials_per_shape": args.trials, "shapes": {}}

    for kind in ("uniform", "bursty", "batch"):
        base_waits, best_waits, chosen, latencies = [], [], {}, []

        for _ in range(args.trials):
            workload = random_workload(rng, kind)

            base = scheduler.stats(
                workload, scheduler.run(BASELINE[0], workload, BASELINE[1])
            )["avg_waiting"]

            t0 = time.perf_counter()
            picked = scheduler.recommend(workload)
            latencies.append((time.perf_counter() - t0) * 1000)

            base_waits.append(base)
            best_waits.append(picked["score"])
            chosen[picked["choice"]] = chosen.get(picked["choice"], 0) + 1

        mean_base = statistics.mean(base_waits)
        mean_best = statistics.mean(best_waits)
        wins = sum(1 for b, p in zip(base_waits, best_waits) if p < b - 1e-9)
        ties = sum(1 for b, p in zip(base_waits, best_waits) if abs(p - b) <= 1e-9)

        report["shapes"][kind] = {
            "baseline_avg_wait": round(mean_base, 3),
            "recommended_avg_wait": round(mean_best, 3),
            "reduction_pct": round((mean_base - mean_best) / mean_base * 100, 1) if mean_base else 0.0,
            "workloads_improved": wins,
            "workloads_unchanged": ties,
            "workloads_worsened": args.trials - wins - ties,
            "median_search_ms": round(statistics.median(latencies), 3),
            "picks": dict(sorted(chosen.items(), key=lambda kv: -kv[1])),
        }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"seed {args.seed}, {args.trials} workloads per shape")
    print(f"baseline: {BASELINE[0]} with quantum {BASELINE[1]}\n")
    print(f"{'shape':<10}{'baseline':>10}{'searched':>10}{'cut':>8}{'better':>8}{'same':>7}{'worse':>7}{'ms':>8}")
    for kind, r in report["shapes"].items():
        print(
            f"{kind:<10}{r['baseline_avg_wait']:>10}{r['recommended_avg_wait']:>10}"
            f"{r['reduction_pct']:>7}%{r['workloads_improved']:>8}"
            f"{r['workloads_unchanged']:>7}{r['workloads_worsened']:>7}{r['median_search_ms']:>8}"
        )

    print("\nwhat it picked:")
    for kind, r in report["shapes"].items():
        top = "  ".join(f"{k} x{v}" for k, v in list(r["picks"].items())[:5])
        print(f"  {kind:<9}{top}")


if __name__ == "__main__":
    main()
