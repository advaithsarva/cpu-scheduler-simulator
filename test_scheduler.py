"""Plain asserts, no pytest, no network.  Runs in well under a second.

    python test_scheduler.py

Every test is named after something that can actually go wrong in a scheduler
simulator.  The first group is the invariant -- run against all five
algorithms, because an invariant that only one implementation is checked
against is not an invariant.  The second group is the arithmetic every
textbook gets right and every implementation gets subtly wrong.
"""

import random
import sys

import scheduler
from scheduler import Process

# The worked example from the Silberschatz scheduling chapter, so the expected
# numbers below come from a source outside this repo.
CLASSIC = [
    Process("P1", arrival=0, burst=8),
    Process("P2", arrival=1, burst=4),
    Process("P3", arrival=2, burst=9),
    Process("P4", arrival=3, burst=5),
]

STAGGERED = [
    Process("A", arrival=0, burst=3, priority=2),
    Process("B", arrival=2, burst=6, priority=1),
    Process("C", arrival=4, burst=4, priority=3),
    Process("D", arrival=6, burst=5, priority=1),
    Process("E", arrival=8, burst=2, priority=4),
]

results = []


def check(name, fn):
    try:
        fn()
    except AssertionError as exc:
        results.append((name, False, str(exc)))
    except Exception as exc:                       # a crash is also a failure
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
    else:
        results.append((name, True, ""))


# --------------------------------------------------------------------------
# the invariant, checked on every algorithm
# --------------------------------------------------------------------------

def test_every_algorithm_holds_the_invariant():
    """THE test.  Each process gets exactly its burst, never runs before it
    arrives, and slices never overlap.  A scheduler that breaks this still
    draws a plausible chart and prints a plausible average -- which is why it
    is checked first and checked on all five."""
    for workload in (CLASSIC, STAGGERED):
        for name in scheduler.ALGORITHMS:
            timeline = scheduler.run(name, workload, quantum=3)
            scheduler.validate_timeline(workload, timeline)   # raises on failure
            served = sum(e - s for _, s, e in timeline)
            want = sum(p.burst for p in workload)
            assert served == want, f"{name}: CPU served {served} units, workload needs {want}"


def test_invariant_catches_a_deliberately_broken_timeline():
    """Proof the check is load bearing.  If validate_timeline accepts these,
    every test above it is decoration."""
    good = scheduler.run("fcfs", CLASSIC)

    broken = [(pid, s, e - 1) for pid, s, e in good if e - 1 > s]
    try:
        scheduler.validate_timeline(CLASSIC, broken)
        raise AssertionError("a timeline that short-changes every process was accepted")
    except ValueError:
        pass

    early = [("P2", 0, 4)] + [t for t in good if t[0] != "P2"]
    try:
        scheduler.validate_timeline(CLASSIC, early)
        raise AssertionError("P2 running at t=0 when it arrives at t=1 was accepted")
    except ValueError:
        pass


def test_invariant_holds_on_random_workloads():
    """Fuzz it.  Seeded, so a failure is reproducible."""
    rng = random.Random(42)
    for trial in range(200):
        n = rng.randint(1, 8)
        workload = [
            Process(f"P{i}", arrival=rng.randint(0, 15), burst=rng.randint(1, 9),
                    priority=rng.randint(0, 4))
            for i in range(n)
        ]
        for name in scheduler.ALGORITHMS:
            timeline = scheduler.run(name, workload, quantum=rng.choice([1, 2, 4, 7]))
            scheduler.validate_timeline(workload, timeline)
            assert timeline, f"trial {trial}: {name} produced an empty timeline"


# --------------------------------------------------------------------------
# per-algorithm behaviour
# --------------------------------------------------------------------------

def test_fcfs_matches_the_textbook_numbers():
    """Hand-computed from CLASSIC: P1 0-8, P2 8-12, P3 12-21, P4 21-26.
    Waits are 0, 7, 10, 18 -> average 8.75."""
    s = scheduler.stats(CLASSIC, scheduler.run("fcfs", CLASSIC))
    assert s["avg_waiting"] == 8.75, f"expected 8.75, got {s['avg_waiting']}"
    assert s["makespan"] == 26, f"expected makespan 26, got {s['makespan']}"


def test_srtf_beats_sjf_when_a_short_job_arrives_late():
    """The whole reason preemption exists.  P2 (burst 4) arrives at t=1 while
    P1 (burst 8) is running; SRTF must interrupt P1, plain SJF must not.  If
    these two ever come out equal, srtf has silently stopped preempting."""
    sjf_wait = scheduler.stats(CLASSIC, scheduler.run("sjf", CLASSIC))["avg_waiting"]
    srtf_wait = scheduler.stats(CLASSIC, scheduler.run("srtf", CLASSIC))["avg_waiting"]
    assert srtf_wait < sjf_wait, f"srtf {srtf_wait} did not beat sjf {sjf_wait}"


def test_srtf_actually_preempts():
    """Stronger than the average above: P1 must appear as two separate slices."""
    timeline = scheduler.run("srtf", CLASSIC)
    p1_slices = [t for t in timeline if t[0] == "P1"]
    assert len(p1_slices) == 2, f"P1 should be split in two by preemption, got {len(p1_slices)}"


def test_round_robin_enqueues_arrivals_before_the_preempted():
    """The classic round-robin ordering bug.  With quantum 2 and B arriving at
    t=2 -- exactly when A's first slice ends -- B must be admitted before A
    goes back on the queue, so the order is A, B, A.  Getting this backwards
    produces A, A, B: a valid timeline with wrong fairness, so
    validate_timeline cannot catch it and only this test can."""
    workload = [Process("A", 0, 6), Process("B", 2, 4)]
    order = [pid for pid, _, _ in scheduler.run("rr", workload, quantum=2)]
    assert order == ["A", "B", "A", "B", "A"], f"got {order}"


def test_round_robin_with_a_huge_quantum_is_fcfs():
    """A quantum longer than any burst means nothing is ever preempted."""
    rr = scheduler.stats(STAGGERED, scheduler.run("rr", STAGGERED, quantum=1000))
    fcfs = scheduler.stats(STAGGERED, scheduler.run("fcfs", STAGGERED))
    assert rr["avg_waiting"] == fcfs["avg_waiting"], f"{rr['avg_waiting']} != {fcfs['avg_waiting']}"


def test_priority_runs_the_important_job_first():
    """B and D are priority 1, C is 3, E is 4.  After A finishes at t=3 the
    two priority-1 jobs must go before the higher numbers."""
    order = [pid for pid, _, _ in scheduler.run("priority", STAGGERED)]
    assert order.index("B") < order.index("C"), f"C ran before B: {order}"
    assert order.index("D") < order.index("E"), f"E ran before D: {order}"


# --------------------------------------------------------------------------
# statistics and idle handling
# --------------------------------------------------------------------------

def test_the_cpu_idles_instead_of_time_travelling():
    """Nothing arrives until t=5, so the first slice starts at 5 and
    utilisation is below 1.0.  The tempting bug is to start at t=0 and quietly
    hand the process five free units."""
    workload = [Process("A", arrival=5, burst=4)]
    timeline = scheduler.run("fcfs", workload)
    assert timeline[0][1] == 5, f"started at {timeline[0][1]}, should idle until 5"
    s = scheduler.stats(workload, timeline)
    assert s["avg_waiting"] == 0, f"a process that never waits should have wait 0, got {s['avg_waiting']}"
    assert s["cpu_utilization"] == 0.4444, f"expected 4/9 busy, got {s['cpu_utilization']}"


def test_waiting_time_is_never_negative():
    """waiting = turnaround - burst.  A negative value means the timeline gave
    a process more CPU than it asked for, or credited it before arrival."""
    rng = random.Random(7)
    for _ in range(100):
        workload = [
            Process(f"P{i}", arrival=rng.randint(0, 10), burst=rng.randint(1, 6))
            for i in range(rng.randint(1, 6))
        ]
        for name in scheduler.ALGORITHMS:
            s = scheduler.stats(workload, scheduler.run(name, workload, quantum=2))
            for row in s["per_process"]:
                assert row["waiting"] >= 0, f"{name}: {row['pid']} waited {row['waiting']}"
                assert row["response"] >= 0, f"{name}: {row['pid']} responded at {row['response']}"


def test_response_time_is_not_turnaround_time():
    """Two different numbers that are easy to conflate.  Under round robin a
    process is answered early and finishes late, so response must be strictly
    smaller than turnaround for at least one process."""
    s = scheduler.stats(STAGGERED, scheduler.run("rr", STAGGERED, quantum=2))
    assert any(r["response"] < r["turnaround"] for r in s["per_process"]), \
        "response and turnaround are identical for every process; one of them is wrong"


def test_a_bad_workload_raises_instead_of_being_clamped():
    """Never clamp a parameter to make an impossible request possible -- that
    is how a bug becomes a silent one."""
    for bad in (lambda: Process("X", 0, 0), lambda: Process("X", 0, -3), lambda: Process("X", -1, 4)):
        try:
            bad()
            raise AssertionError("an impossible process was accepted")
        except ValueError:
            pass

    try:
        scheduler.run("rr", CLASSIC, quantum=0)
        raise AssertionError("quantum 0 was accepted; it would loop forever")
    except ValueError:
        pass

    try:
        scheduler.run("shortest-hair-first", CLASSIC)
        raise AssertionError("an unknown algorithm name was accepted")
    except ValueError:
        pass


def test_recommend_never_loses_to_the_default():
    """The Phase 3.5 feature's one promise: searching the space is never worse
    than the fixed default it replaces.  If this fails, the recommender is
    decoration and should be deleted."""
    rng = random.Random(1234)
    for _ in range(100):
        workload = [
            Process(f"P{i}", arrival=rng.randint(0, 12), burst=rng.randint(1, 9))
            for i in range(rng.randint(2, 7))
        ]
        picked = scheduler.recommend(workload)
        default = scheduler.stats(workload, scheduler.run("rr", workload, 4))["avg_waiting"]
        assert picked["score"] <= default + 1e-9, \
            f"recommender scored {picked['score']}, plain rr(q=4) scored {default}"


def test_output_is_deterministic():
    """Same input, same output, every run.  Ties are broken by pid rather than
    by dict or set order, so a second process cannot change the answer for the
    first."""
    for name in scheduler.ALGORITHMS:
        first = scheduler.run(name, STAGGERED, quantum=3)
        for _ in range(5):
            assert scheduler.run(name, STAGGERED, quantum=3) == first, f"{name} is not deterministic"


TESTS = [
    ("invariant holds on every algorithm", test_every_algorithm_holds_the_invariant),
    ("invariant catches a broken timeline", test_invariant_catches_a_deliberately_broken_timeline),
    ("invariant holds on 200 random workloads", test_invariant_holds_on_random_workloads),
    ("fcfs matches the textbook numbers", test_fcfs_matches_the_textbook_numbers),
    ("srtf beats sjf on a late short job", test_srtf_beats_sjf_when_a_short_job_arrives_late),
    ("srtf actually preempts", test_srtf_actually_preempts),
    ("rr admits arrivals before the preempted", test_round_robin_enqueues_arrivals_before_the_preempted),
    ("rr with a huge quantum is fcfs", test_round_robin_with_a_huge_quantum_is_fcfs),
    ("priority runs the important job first", test_priority_runs_the_important_job_first),
    ("the cpu idles instead of time travelling", test_the_cpu_idles_instead_of_time_travelling),
    ("waiting time is never negative", test_waiting_time_is_never_negative),
    ("response time is not turnaround time", test_response_time_is_not_turnaround_time),
    ("a bad workload raises instead of clamping", test_a_bad_workload_raises_instead_of_being_clamped),
    ("recommend never loses to the default", test_recommend_never_loses_to_the_default),
    ("output is deterministic", test_output_is_deterministic),
]


def main():
    for name, fn in TESTS:
        check(name, fn)

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, err in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"      {err}")
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
