"""Command line front end: JSON in, JSON or an ASCII Gantt chart out.

    python cli.py workloads/mixed.json                  # compare all five
    python cli.py workloads/mixed.json --algo rr -q 2   # one algorithm
    python cli.py workloads/mixed.json --recommend      # pick the best one
    python cli.py workloads/mixed.json --json           # machine readable
    cat workload.json | python cli.py -                 # read stdin

The ``--json`` form is the documented interface for anything that wants to
drive this project without a human in the loop: it reads one JSON document on
a path or stdin and writes one JSON document to stdout, and it is the only
thing on stdout when it does.
"""

import argparse
import json
import sys

import scheduler
from scheduler import Process

BLOCKS = "#=+*o~%@&$"      # one fill character per process, cycled


def load_workload(path):
    """Read a workload from a file path, or from stdin when path is '-'.

    Accepts either a bare list of processes or ``{"processes": [...],
    "quantum": n}`` so a saved comparison can be fed straight back in.
    """
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    data = json.loads(text)
    if isinstance(data, dict):
        rows, quantum = data.get("processes", []), data.get("quantum")
    else:
        rows, quantum = data, None

    if not rows:
        raise ValueError("workload is empty; expected at least one process")

    processes = []
    seen = set()
    for i, row in enumerate(rows):
        pid = str(row.get("pid", f"P{i + 1}"))
        if pid in seen:
            raise ValueError(f"duplicate pid {pid!r}; pids identify a process and must be unique")
        seen.add(pid)
        processes.append(
            Process(
                pid=pid,
                arrival=int(row["arrival"]),
                burst=int(row["burst"]),
                priority=int(row.get("priority", 0)),
            )
        )
    return processes, quantum


def gantt(timeline, width=100):
    """Draw the timeline as an ASCII bar with a time ruler underneath.

    Scaled to fit `width` columns.  Every slice gets at least one column, so a
    one-unit slice on a long timeline still shows up rather than vanishing --
    a disappearing slice reads as a scheduler bug when it is only a rounding
    artefact of the drawing code.
    """
    span = max(end for _, _, end in timeline)
    scale = min(1.0, width / span) if span else 1.0

    fills = {}
    bar, ruler, cursor = [], [], 0
    for pid, start, end in timeline:
        if pid not in fills:
            fills[pid] = BLOCKS[len(fills) % len(BLOCKS)]

        gap = max(0, round(start * scale) - cursor)
        bar.append("." * gap)                      # CPU idle
        ruler.append(" " * gap)
        cursor += gap

        cells = max(1, round((end - start) * scale))
        bar.append(fills[pid] * cells)
        label = str(start)
        ruler.append(label[:cells].ljust(cells) if cells >= len(label) else " " * cells)
        cursor += cells

    legend = "  ".join(f"{fills[p]} {p}" for p in fills)
    return "".join(bar) + "\n" + "".join(ruler) + f"\n\n{legend}\n(idle = '.', ends at t={span})"


def print_stats(name, result):
    print(f"\n=== {name} ===")
    print(f"{'pid':<6}{'arr':>5}{'burst':>7}{'compl':>7}{'turn':>7}{'wait':>7}{'resp':>7}")
    for r in result["per_process"]:
        print(
            f"{r['pid']:<6}{r['arrival']:>5}{r['burst']:>7}{r['completion']:>7}"
            f"{r['turnaround']:>7}{r['waiting']:>7}{r['response']:>7}"
        )
    print(
        f"avg wait {result['avg_waiting']}   avg turnaround {result['avg_turnaround']}   "
        f"avg response {result['avg_response']}   makespan {result['makespan']}   "
        f"cpu {result['cpu_utilization'] * 100:.1f}%   switches {result['context_switches']}"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workload", help="path to a workload JSON file, or - for stdin")
    ap.add_argument("--algo", choices=sorted(scheduler.ALGORITHMS), help="run one algorithm")
    ap.add_argument("-q", "--quantum", type=int, help="round robin time slice (default 4, or the workload's)")
    ap.add_argument("--recommend", action="store_true", help="pick the algorithm with the lowest average wait")
    ap.add_argument("--metric", default="avg_waiting", help="metric --recommend minimises")
    ap.add_argument("--json", action="store_true", help="write JSON to stdout and nothing else")
    args = ap.parse_args(argv)

    try:
        processes, file_quantum = load_workload(args.workload)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"could not read workload: {exc}", file=sys.stderr)
        return 2

    # -q wins over the workload file, which wins over the default.
    quantum = args.quantum or file_quantum or 4

    try:
        if args.recommend:
            payload = scheduler.recommend(processes, metric=args.metric)
        elif args.algo:
            timeline = scheduler.run(args.algo, processes, quantum)
            payload = {
                "algorithm": args.algo,
                "quantum": quantum if args.algo == "rr" else None,
                "timeline": [{"pid": p, "start": s, "end": e} for p, s, e in timeline],
                **scheduler.stats(processes, timeline),
            }
        else:
            payload = {"quantum": quantum, "results": scheduler.compare(processes, quantum)}
    except ValueError as exc:
        print(f"scheduling failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
        return 0

    if args.recommend:
        print(f"best by {payload['metric']}: {payload['choice']}  (score {payload['score']})\n")
        print(f"{'choice':<12}{payload['metric']:>12}{'switches':>10}")
        for row in payload["considered"]:
            print(f"{row['choice']:<12}{row[payload['metric']]:>12}{row['context_switches']:>10}")
    elif args.algo:
        timeline = [(t["pid"], t["start"], t["end"]) for t in payload["timeline"]]
        print(gantt(timeline))
        print_stats(payload["algorithm"], payload)
    else:
        for name, result in payload["results"].items():
            timeline = scheduler.run(name, processes, quantum)
            print(gantt(timeline))
            print_stats(name, result)
        print("\n=== summary ===")
        print(f"{'algorithm':<12}{'avg wait':>10}{'avg turn':>10}{'avg resp':>10}{'switches':>10}")
        for name, r in payload["results"].items():
            print(
                f"{name:<12}{r['avg_waiting']:>10}{r['avg_turnaround']:>10}"
                f"{r['avg_response']:>10}{r['context_switches']:>10}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
