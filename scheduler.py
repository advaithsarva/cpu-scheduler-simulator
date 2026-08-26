"""CPU scheduling algorithms, and the one rule they all have to obey.

THE INVARIANT
-------------
Every algorithm returns a *timeline*: a list of ``(pid, start, end)`` slices,
sorted by ``start``.  For that timeline to mean anything:

    1. every process gets exactly ``burst`` units of CPU, no more, no less
    2. no slice starts before its process arrived
    3. no two slices overlap
    4. ``start < end`` for every slice

``validate_timeline`` checks all four and every algorithm is run through it in
``test_scheduler.py``.  This is the invariant because it is the bug that makes
a scheduler simulator useless: the Gantt chart still draws, the average-wait
number still prints, and it is quietly wrong.  A preemptive algorithm that
loses half a time unit on every switch looks completely normal on screen.

Time is integer.  Arrival and burst times are whole units, the clock steps in
whole units, and nothing here produces a fraction.  That is a deliberate
restriction: it makes the invariant exactly checkable instead of
approximately checkable.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Process:
    """One process to schedule.

    ``priority`` is only read by ``priority_scheduling``; lower number means
    more important, which is the Unix convention and the one every OS
    textbook uses.
    """

    pid: str
    arrival: int
    burst: int
    priority: int = 0

    def __post_init__(self):
        if self.burst <= 0:
            raise ValueError(f"{self.pid}: burst must be positive, got {self.burst}")
        if self.arrival < 0:
            raise ValueError(f"{self.pid}: arrival must be >= 0, got {self.arrival}")


# --------------------------------------------------------------------------
# the invariant, as code
# --------------------------------------------------------------------------

def validate_timeline(processes, timeline):
    """Raise ValueError if the timeline breaks the invariant.

    Called by the tests against every algorithm.  It is cheap enough to also
    call in anger, so ``cli.py`` calls it on every run.
    """
    by_pid = {p.pid: p for p in processes}

    served = {p.pid: 0 for p in processes}
    previous_end = 0
    for pid, start, end in timeline:
        if pid not in by_pid:
            raise ValueError(f"timeline contains unknown pid {pid!r}")
        if start >= end:
            raise ValueError(f"{pid}: empty or reversed slice ({start}, {end})")
        if start < previous_end:
            raise ValueError(
                f"{pid}: slice starts at {start} but the CPU is busy until {previous_end}"
            )
        if start < by_pid[pid].arrival:
            raise ValueError(
                f"{pid}: scheduled at {start} but does not arrive until {by_pid[pid].arrival}"
            )
        served[pid] += end - start
        previous_end = end

    for pid, got in served.items():
        want = by_pid[pid].burst
        if got != want:
            raise ValueError(f"{pid}: got {got} units of CPU, needs exactly {want}")


def _merge(slices):
    """Join touching slices that belong to the same process.

    The preemptive algorithms below step one unit at a time, so they emit
    ``(A,0,1) (A,1,2) (A,2,3)``.  A reader wants ``(A,0,3)``.  Merging here
    means the algorithms stay simple and the Gantt chart stays readable.
    """
    merged = []
    for pid, start, end in slices:
        if merged and merged[-1][0] == pid and merged[-1][2] == start:
            merged[-1] = (pid, merged[-1][1], end)
        else:
            merged.append((pid, start, end))
    return merged


# --------------------------------------------------------------------------
# the algorithms
# --------------------------------------------------------------------------

def fcfs(processes):
    """First come, first served.  Runs each process to completion in arrival
    order, ties broken by pid so the result is deterministic."""
    timeline = []
    clock = 0
    for p in sorted(processes, key=lambda p: (p.arrival, p.pid)):
        start = max(clock, p.arrival)          # CPU idles if nobody has arrived
        timeline.append((p.pid, start, start + p.burst))
        clock = start + p.burst
    return _merge(timeline)


def sjf(processes):
    """Shortest job first, non-preemptive.

    A running process is never interrupted; the choice is only made when the
    CPU falls idle.  That is what separates it from ``srtf`` below.
    """
    pending = sorted(processes, key=lambda p: (p.arrival, p.pid))
    timeline = []
    clock = 0

    while pending:
        ready = [p for p in pending if p.arrival <= clock]
        if not ready:
            clock = min(p.arrival for p in pending)   # jump to the next arrival
            continue
        chosen = min(ready, key=lambda p: (p.burst, p.arrival, p.pid))
        pending.remove(chosen)
        timeline.append((chosen.pid, clock, clock + chosen.burst))
        clock += chosen.burst

    return _merge(timeline)


def srtf(processes):
    """Shortest remaining time first — preemptive SJF.

    Steps the clock one unit at a time and re-picks the winner every step.
    That is O(total_burst x n_processes), which is fine for the hundreds of
    processes this simulator is for and obviously correct, which matters more.

    ponytail: unit-stepping, not event-driven.  An event-driven version only
    pays off above ~10k total time units; swap it in then and keep
    validate_timeline as the check that the rewrite is equivalent.
    """
    left = {p.pid: p.burst for p in processes}
    by_pid = {p.pid: p for p in processes}
    timeline = []
    clock = 0

    while any(v > 0 for v in left.values()):
        ready = [
            pid for pid, v in left.items()
            if v > 0 and by_pid[pid].arrival <= clock
        ]
        if not ready:
            clock = min(
                by_pid[pid].arrival for pid, v in left.items() if v > 0
            )
            continue
        chosen = min(ready, key=lambda pid: (left[pid], by_pid[pid].arrival, pid))
        timeline.append((chosen, clock, clock + 1))
        left[chosen] -= 1
        clock += 1

    return _merge(timeline)


def round_robin(processes, quantum=4):
    """Round robin with a fixed time slice.

    The subtle part is the order of the two queue operations at the end of a
    slice: processes that arrive *during* the slice are enqueued before the
    process that just ran is put back.  Doing it the other way round gives a
    process that never yields its turn, which is a real and commonly shipped
    bug -- and one that validate_timeline does *not* catch, because the
    resulting timeline is still perfectly valid.  It is only the fairness that
    is wrong.  ``test_round_robin_enqueues_arrivals_before_the_preempted``
    covers it.
    """
    if quantum <= 0:
        raise ValueError(f"quantum must be positive, got {quantum}")

    arrivals = sorted(processes, key=lambda p: (p.arrival, p.pid))
    left = {p.pid: p.burst for p in processes}
    queue = []
    timeline = []
    clock = 0
    next_arrival = 0

    def admit(up_to):
        nonlocal next_arrival
        while next_arrival < len(arrivals) and arrivals[next_arrival].arrival <= up_to:
            queue.append(arrivals[next_arrival].pid)
            next_arrival += 1

    admit(clock)
    while any(v > 0 for v in left.values()):
        if not queue:
            clock = arrivals[next_arrival].arrival     # idle until someone shows up
            admit(clock)
            continue

        pid = queue.pop(0)
        slice_len = min(quantum, left[pid])
        timeline.append((pid, clock, clock + slice_len))
        left[pid] -= slice_len
        clock += slice_len

        admit(clock)                # arrivals during the slice go in first ...
        if left[pid] > 0:
            queue.append(pid)       # ... then the process that was preempted

    return _merge(timeline)


def priority_scheduling(processes):
    """Non-preemptive priority.  Lower number wins; equal priorities fall back
    to arrival order, then pid, so it is deterministic."""
    pending = list(processes)
    timeline = []
    clock = 0

    while pending:
        ready = [p for p in pending if p.arrival <= clock]
        if not ready:
            clock = min(p.arrival for p in pending)
            continue
        chosen = min(ready, key=lambda p: (p.priority, p.arrival, p.pid))
        pending.remove(chosen)
        timeline.append((chosen.pid, clock, clock + chosen.burst))
        clock += chosen.burst

    return _merge(timeline)


ALGORITHMS = {
    "fcfs": fcfs,
    "sjf": sjf,
    "srtf": srtf,
    "rr": round_robin,
    "priority": priority_scheduling,
}


def run(name, processes, quantum=4):
    """Run one algorithm by name and check the invariant before returning."""
    if name not in ALGORITHMS:
        raise ValueError(
            f"unknown algorithm {name!r}; choose from {', '.join(sorted(ALGORITHMS))}"
        )
    if name == "rr":
        timeline = round_robin(processes, quantum)
    else:
        timeline = ALGORITHMS[name](processes)
    validate_timeline(processes, timeline)
    return timeline


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

def stats(processes, timeline):
    """Per-process and summary numbers for one timeline.

    waiting = turnaround - burst is the definition used everywhere; it counts
    every unit the process existed but did not hold the CPU, including time
    lost to preemption.
    """
    first_start = {}
    last_end = {}
    for pid, start, end in timeline:
        first_start.setdefault(pid, start)
        last_end[pid] = end

    per_process = []
    for p in sorted(processes, key=lambda p: p.pid):
        completion = last_end[p.pid]
        turnaround = completion - p.arrival
        per_process.append(
            {
                "pid": p.pid,
                "arrival": p.arrival,
                "burst": p.burst,
                "priority": p.priority,
                "completion": completion,
                "turnaround": turnaround,
                "waiting": turnaround - p.burst,
                "response": first_start[p.pid] - p.arrival,
            }
        )

    makespan = max(last_end.values())
    busy = sum(end - start for _, start, end in timeline)
    n = len(per_process)

    return {
        "per_process": per_process,
        "avg_waiting": round(sum(r["waiting"] for r in per_process) / n, 3),
        "avg_turnaround": round(sum(r["turnaround"] for r in per_process) / n, 3),
        "avg_response": round(sum(r["response"] for r in per_process) / n, 3),
        "makespan": makespan,
        "cpu_utilization": round(busy / makespan, 4),
        "context_switches": max(0, len(timeline) - 1),
    }


def compare(processes, quantum=4):
    """Run every algorithm on the same workload and return name -> stats."""
    out = {}
    for name in ALGORITHMS:
        timeline = run(name, processes, quantum)
        out[name] = stats(processes, timeline)
    return out


def recommend(processes, quantum_choices=(1, 2, 4, 8), metric="avg_waiting"):
    """Pick the algorithm (and round-robin quantum) that minimises `metric`.

    This is the honest answer to "where is the intelligence?" for this project:
    the simulator is cheap enough that searching the whole space beats any
    heuristic guess, so it searches.  ``bench.py`` measures it against the
    fixed default an operator would otherwise pick.

    Returns the winner plus every candidate it considered, so the caller can
    show its work rather than being asked to trust it.
    """
    candidates = []
    for name in ALGORITHMS:
        if name == "rr":
            for q in quantum_choices:
                candidates.append((f"rr(q={q})", stats(processes, run("rr", processes, q)), name, q))
        else:
            candidates.append((name, stats(processes, run(name, processes)), name, None))

    # ties broken by fewer context switches, then by name: a real scheduler
    # prefers the cheaper option when the wait time is identical.
    candidates.sort(key=lambda c: (c[1][metric], c[1]["context_switches"], c[0]))
    label, best, algorithm, quantum = candidates[0]

    return {
        "metric": metric,
        "choice": label,
        "algorithm": algorithm,
        "quantum": quantum,
        "score": best[metric],
        "considered": [
            {"choice": c[0], metric: c[1][metric], "context_switches": c[1]["context_switches"]}
            for c in candidates
        ],
    }
