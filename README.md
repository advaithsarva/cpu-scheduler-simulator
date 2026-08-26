# CPU Scheduler Simulator

Feed it a set of processes with arrival and burst times; it runs FCFS, SJF,
SRTF, Round Robin and Priority scheduling over the same workload, draws the
Gantt chart, and gives you the waiting, turnaround and response times side by
side.

Pure Python standard library. No install step, no dependencies, no build.

**Searching all five algorithms and four round-robin quanta cuts average
waiting time 40.9–48.9% against the round-robin-with-quantum-4 default, over
1500 seeded random workloads, and never once lost to it.** Full numbers and
method in [RESULTS.md](RESULTS.md).

---

## The rule the whole thing turns on

> **Every algorithm returns a timeline of `(pid, start, end)` slices in which
> each process receives exactly `burst` units of CPU, no slice begins before
> its process arrives, and no two slices overlap.**

`validate_timeline()` in `scheduler.py` checks all four conditions, and every
algorithm is run through it on two fixed workloads plus 200 seeded random
ones. This is the invariant because it is the failure that makes a scheduler
simulator worthless: a broken timeline still draws a plausible chart and still
prints a plausible average. Nothing looks wrong. A preemptive algorithm that
drops half a unit on each context switch produces a chart no human eye would
question.

Time is integer throughout. That is a deliberate restriction — it makes the
invariant exactly checkable rather than approximately checkable.

---

## Running it

Python 3.10 or newer. Nothing to install.

```bash
python cli.py workloads/classic.json                  # all five, side by side
python cli.py workloads/bursty.json --algo rr -q 2    # one algorithm
python cli.py workloads/bursty.json --recommend       # pick the best one
python cli.py workloads/classic.json --algo srtf --json > plan.json
cat workload.json | python cli.py -                   # or read stdin
```

Output of the comparison run:

```
=== summary ===
algorithm     avg wait  avg turn  avg resp  switches
fcfs              8.75     15.25      8.75         3
sjf               7.75     14.25      7.75         3
srtf               6.5      13.0      4.25         4
rr               11.75     18.25       4.5         7
priority          7.75     14.25      7.75         3
```

### Workload format

A JSON list, or an object with `processes` and an optional `quantum`:

```json
{
  "quantum": 4,
  "processes": [
    {"pid": "P1", "arrival": 0, "burst": 8, "priority": 3},
    {"pid": "P2", "arrival": 1, "burst": 4, "priority": 1}
  ]
}
```

`pid` defaults to `P1, P2, …` and `priority` to `0`. Lower priority number
means more important, per the Unix convention. Three samples are in
`workloads/`.

### The Gantt chart

`cli.py` draws an ASCII chart in the terminal. For a proper one, open
`viewer.html` in a browser and paste in the output of `--algo … --json`. It is
a single file with no dependencies and no build step, and it only *renders* —
it never schedules anything itself, because a second implementation of these
algorithms would drift away from the tested one.

---

## Driving it from other software

`--json` is the machine interface: one JSON document in on a path or stdin,
one JSON document out on stdout, and nothing else on stdout when you use it.
Exit code is 0 on success, 1 if scheduling failed, 2 if the workload could not
be read.

```bash
echo '[{"arrival":0,"burst":5},{"arrival":1,"burst":2}]' | python cli.py - --recommend --json
```

```json
{
  "metric": "avg_waiting",
  "choice": "srtf",
  "algorithm": "srtf",
  "quantum": null,
  "score": 1.0,
  "considered": [ ... every candidate, so it shows its work ... ]
}
```

That is this project's answer to "where is the intelligence?" — it is the tool,
not the model. No credential, no network call, no latency, no accuracy claim
that cannot be reproduced. `--recommend` searches the whole space of five
algorithms and four quanta, which is cheap enough here (median 0.5–0.8 ms) that
searching genuinely beats guessing, and `bench.py` measures by how much.

---

## Tests

```bash
python test_scheduler.py     # 15/15, about 0.4 s
```

Plain asserts, no pytest, no network. The suite is in two halves:

**The invariant**, checked against all five algorithms — including
`test_invariant_catches_a_deliberately_broken_timeline`, which hands
`validate_timeline` a timeline that short-changes every process and one that
runs a process before it arrives, and fails if either is accepted. Without
that test the other fourteen are decoration.

**The arithmetic**, one test per mistake that is easy to make:

| Test | What it catches |
|---|---|
| `fcfs matches the textbook numbers` | 8.75 average wait on the Silberschatz example — a figure from outside this repo |
| `srtf actually preempts` | SRTF quietly degrading into non-preemptive SJF; P1 must be split in two |
| `rr admits arrivals before the preempted` | the round-robin queue-ordering bug (below) |
| `rr with a huge quantum is fcfs` | a quantum longer than every burst must preempt nothing |
| `the cpu idles instead of time travelling` | starting work at t=0 when nothing arrives until t=5, handing out five free units |
| `waiting time is never negative` | a process credited with more CPU than it asked for |
| `response time is not turnaround time` | two different numbers, easily conflated |
| `a bad workload raises instead of clamping` | zero burst, negative arrival, quantum 0, unknown algorithm |
| `recommend never loses to the default` | the Phase 3.5 feature's one promise |
| `output is deterministic` | ties broken by pid, not by set or dict order |

### The one bug the invariant cannot catch

In round robin, a process that arrives *during* a time slice must be put on
the queue **before** the process that was just preempted goes back on it. Get
that backwards and one process keeps stealing its own turn.

The resulting timeline is still completely valid — every process gets its
exact burst, nothing overlaps, nothing runs early — so `validate_timeline`
passes it without complaint. Only the fairness is wrong, and only
`test_round_robin_enqueues_arrivals_before_the_preempted` sees it. It pins the
exact slice order `A, B, A, B, A` for a workload built so that B arrives at
precisely the tick A's first slice ends.

That test is here because an invariant, however good, only covers the
properties you thought to state.

---

## What is not here

- **No preemptive priority and no aging.** Non-preemptive priority is
  implemented and starves low-priority work forever, which is honest and
  visible in the output rather than hidden behind a half-built fix.
- **No I/O bursts.** Every process is pure CPU. Adding I/O means a blocked
  state and a second queue, which changes every algorithm.
- **No multi-core.** One CPU. The timeline invariant assumes one runnable
  slice at a time and would need rewriting for more.
- **`srtf` steps one time unit at a time**, so it is O(total_burst × n). Fine
  into the hundreds of processes and obviously correct, which matters more
  here. Above roughly 10,000 time units, make it event-driven — and keep
  `validate_timeline` as the proof the rewrite is equivalent.
