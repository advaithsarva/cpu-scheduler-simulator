# CPU Scheduler Simulator

Give it a set of processes with arrival and burst times, and it runs FCFS, SJF, SRTF, Round Robin, and Priority scheduling against the same workload. It then draws the Gantt chart and reports waiting, turnaround, and response times side by side.

Pure Python standard library. No installation, dependencies, or build step.

**Searching all five algorithms and four Round Robin quanta reduces average waiting time by 40.9–48.9% compared with the round-robin-with-quantum-4 default, across 1,500 seeded random workloads, without losing to the default on any of them.** The full measurements and methodology are in `RESULTS.md`.

---

## The rule the whole simulator depends on

> **Every algorithm returns a timeline of `(pid, start, end)` slices where each process receives exactly its requested `burst` time, no slice starts before the process arrives, and no two slices overlap.**

`scheduler.py` uses `validate_timeline()` to check these conditions. Every algorithm is tested against two fixed workloads and 200 seeded random workloads.

This invariant matters because a broken scheduler can still produce a Gantt chart that looks completely reasonable and averages that look plausible. For example, a preemptive scheduler that accidentally loses half a unit during every context switch could still produce output that looks correct at a glance.

Time is represented using integers throughout. That is deliberate: it makes the invariant exactly checkable rather than dependent on floating-point tolerances.

---

## Running it

Python 3.10 or newer. Nothing to install.

```bash id="e0oq7j"
python cli.py workloads/classic.json                  # all five, side by side
python cli.py workloads/bursty.json --algo rr -q 2   # one algorithm
python cli.py workloads/bursty.json --recommend       # pick the best one
python cli.py workloads/classic.json --algo srtf --json > plan.json

cat workload.json | python cli.py -                   # or read stdin
```

A comparison run produces:

```text id="s5u7d1"
=== summary ===
algorithm     avg wait  avg turn  avg resp  switches

fcfs              8.75     15.25      8.75         3
sjf               7.75     14.25      7.75         3
srtf               6.5      13.0      4.25         4
rr                11.75     18.25       4.5         7
priority           7.75     14.25      7.75         3
```

### Workload format

The input can be a JSON list or an object containing `processes` and an optional `quantum`:

```json id="5y8d1m"
{
  "quantum": 4,
  "processes": [
    {"pid": "P1", "arrival": 0, "burst": 8, "priority": 3},
    {"pid": "P2", "arrival": 1, "burst": 4, "priority": 1}
  ]
}
```

`pid` defaults to `P1`, `P2`, and so on. `priority` defaults to `0`. Lower priority numbers mean higher priority, following the Unix convention.

Three sample workloads are included in `workloads/`.

### The Gantt chart

`cli.py` prints an ASCII Gantt chart directly in the terminal.

For a more visual version, open `viewer.html` in a browser and paste in the output from `--algo ... --json`. It is a single dependency-free HTML file with no build step.

The viewer only renders the schedule. It does not implement any scheduling algorithms itself. Keeping scheduling in one place avoids having a second implementation slowly diverge from the tested one.

---

## Driving it from other software

`--json` is the machine interface: one JSON document goes in from a file or stdin, and one JSON document comes out on stdout. When using this mode, nothing else is written to stdout.

Exit codes are:

* `0` — scheduling succeeded
* `1` — scheduling failed
* `2` — the workload could not be read

For example:

```bash id="xj6e9s"
echo '[{"arrival":0,"burst":5},{"arrival":1,"burst":2}]' | python cli.py - --recommend --json
```

```json id="a2e7kr"
{
  "metric": "avg_waiting",
  "choice": "srtf",
  "algorithm": "srtf",
  "quantum": null,
  "score": 1.0,
  "considered": [
    "... every candidate, so the decision can be inspected ..."
  ]
}
```

This is where the decision-making lives. There is no model, credential, network request, or external service involved.

`--recommend` simply searches the available scheduling choices: five algorithms plus Round Robin with four different quanta. For the workload sizes used here, that search is cheap enough to make simulation preferable to guessing. The median search takes roughly **0.5–0.8 ms**, and `bench.py` measures the resulting improvement.

---

## Tests

```bash id="z0n3qu"
python test_scheduler.py     # 15/15, about 0.4 s
```

The tests use plain assertions. There is no pytest, network access, or external test data.

The suite has two main parts.

### The invariant

The timeline invariant is checked against all five algorithms. One particularly important test is `test_invariant_catches_a_deliberately_broken_timeline`.

It gives `validate_timeline()` two invalid schedules:

1. One that short-changes every process.
2. One that schedules a process before its arrival time.

The test fails if either invalid timeline is accepted. Without it, the other tests would depend on a checker that had never been shown to catch the errors it is supposed to detect.

### The arithmetic

The remaining tests target individual scheduler mistakes:

| Test                                        | What it catches                                                                                    |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `fcfs matches the textbook numbers`         | 8.75 average waiting time on the Silberschatz example, using a figure from outside this repository |
| `srtf actually preempts`                    | SRTF accidentally behaving like non-preemptive SJF; P1 must be split into two slices               |
| `rr admits arrivals before the preempted`   | The Round Robin queue-ordering bug described below                                                 |
| `rr with a huge quantum is fcfs`            | A quantum longer than every burst should cause no preemption                                       |
| `the cpu idles instead of time travelling`  | Starting execution at t=0 when the first process arrives at t=5                                    |
| `waiting time is never negative`            | Giving a process more CPU time than its requested burst                                            |
| `response time is not turnaround time`      | Accidentally treating the two metrics as the same value                                            |
| `a bad workload raises instead of clamping` | Invalid burst/arrival values, quantum 0, and unknown algorithms                                    |
| `recommend never loses to the default`      | The main guarantee of the recommendation feature                                                   |
| `output is deterministic`                   | Ties must be resolved by PID rather than depending on set or dictionary ordering                   |

### The bug the invariant cannot catch

Round Robin has a subtle ordering rule that the timeline invariant cannot detect.

If a new process arrives **during** the current time slice, it must enter the ready queue **before** the process that was just preempted is added back to the queue.

If that ordering is reversed, a process can effectively take its own turn again before another process gets one.

The resulting timeline can still be completely valid: every process gets its full burst, no slices overlap, and nothing runs before its arrival. `validate_timeline()` therefore has no reason to reject it.

Only `test_round_robin_enqueues_arrivals_before_the_preempted` catches the fairness problem. It checks for the exact `A, B, A, B, A` slice order using a workload where B arrives exactly when A's first slice ends.

This is a useful limitation of invariants in general: they can only verify properties that have actually been stated.

---

## What is not here

* **No preemptive priority scheduling and no aging.** Non-preemptive priority scheduling is implemented. It can starve lower-priority work, and that behavior remains visible rather than being hidden behind an incomplete aging implementation.

* **No I/O bursts.** Every process is CPU-only. Adding I/O would introduce blocked processes and another queue, changing the behavior of all five algorithms.

* **No multicore scheduling.** The simulator models one CPU. The current timeline invariant assumes that only one runnable slice exists at a time and would need to be changed for multiple cores.

* **SRTF advances one time unit at a time.** Its complexity is `O(total_burst × n)`. That is acceptable for the simulator's intended workload sizes and keeps the implementation straightforward to verify. For workloads exceeding roughly 10,000 time units, an event-driven implementation would make more sense. `validate_timeline()` should remain in place as the check that the optimized implementation produces an equivalent schedule.
