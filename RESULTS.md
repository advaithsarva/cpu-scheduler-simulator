# Results

Every number below came from a command run on this machine: Windows 11, Python 3.12.1, standard library only. All workloads are seeded, so running the same commands again produces the same results.

---

## 1. The test suite

```bash
python test_scheduler.py
```

**15 / 15 passed** in 0.4 seconds. There is no pytest, no network access, and no disk-based test fixtures.

Three of the 15 tests check the core invariant across all five algorithms: two fixed workloads plus 200 seeded random workloads (`Random(42)`). The random workloads use 1–8 processes, arrivals from 0–15, bursts from 1–9, and quanta from `{1, 2, 4, 7}`. That gives **1,000 algorithm runs per test-suite execution**, with every run checked slice by slice.

`test_invariant_catches_a_deliberately_broken_timeline` is the important one. It gives `validate_timeline` two deliberately corrupted timelines and expects both to be rejected:

| Corruption                                          | What it simulates                                  |
| --------------------------------------------------- | -------------------------------------------------- |
| Every slice shortened by one unit                   | A scheduler losing time during each context switch |
| `P2` scheduled at t=0 even though it arrives at t=1 | A process running before it actually exists        |

Without this test, the rest of the suite would be relying on a checker that had never been shown to catch an invalid schedule.

---

## 2. The classic workload: all five algorithms

```bash
python cli.py workloads/classic.json
```

The workload comes from the worked example in the Silberschatz scheduling chapter: four processes with arrivals at 0, 1, 2, and 3, and bursts of 8, 4, 9, and 5. The expected figures therefore come from outside this repository.

| Algorithm             | Avg waiting | Avg turnaround | Avg response | Context switches |
| --------------------- | ----------: | -------------: | -----------: | ---------------: |
| FCFS                  |        8.75 |          15.25 |         8.75 |                3 |
| SJF (non-preemptive)  |        7.75 |          14.25 |         7.75 |                3 |
| **SRTF (preemptive)** |    **6.50** |      **13.00** |     **4.25** |                4 |
| Round Robin (q=4)     |       11.75 |          18.25 |         4.50 |                7 |
| Priority              |        7.75 |          14.25 |         7.75 |                3 |

SRTF performs best on all three timing metrics here, at the cost of one additional context switch.

Round robin has the highest average waiting time but the second-best average response time. That is expected: optimizing round robin purely around average waiting time makes it look worse than it is for interactive responsiveness. Both metrics are reported so that trade-off is visible.

Priority and SJF happen to tie on this workload because the priority ordering matches the shortest-job ordering. That is a property of this particular fixture, not of the algorithms themselves.

---

## 3. Idle time is still part of the timeline

```bash
python cli.py workloads/idle-gap.json --algo fcfs
```

Nothing arrives until t=5, followed by another idle period between t=9 and t=20.

| Figure                |     Value |
| --------------------- | --------: |
| First slice starts at |       t=5 |
| Makespan              |        25 |
| Busy                  |   9 units |
| **CPU utilisation**   | **36.0%** |
| Avg waiting           |     0.667 |

A tempting implementation bug is to start the first process at t=0. That effectively gives the process five units of free CPU time, pushes utilization to 100%, and makes the waiting-time figures artificially low.

`test_the_cpu_idles_instead_of_time_travelling` catches the same problem on a smaller workload by checking for the expected 0.4444 utilization.

---

## 4. The recommender compared with the default

```bash
python bench.py          # 500 workloads per shape, seed 42
python bench.py --json   # same numbers, machine-readable
```

**Baseline:** round robin with quantum 4, which is a reasonable default when no workload-specific information is available.

**Candidate:** `scheduler.recommend()`. It simulates all five algorithms plus round robin with quanta 1, 2, 4, and 8, then selects the schedule with the lowest average waiting time.

The benchmark contains 1,500 seeded workloads across three workload shapes:

| Shape   | Baseline avg wait | Searched avg wait | Reduction | Better | Same | **Worse** | Median search |
| ------- | ----------------: | ----------------: | --------: | -----: | ---: | --------: | ------------: |
| uniform |            14.363 |             8.483 | **40.9%** |    482 |   18 |     **0** |      0.512 ms |
| bursty  |             9.952 |             5.090 | **48.9%** |    417 |   83 |     **0** |      0.561 ms |
| batch   |            45.609 |            23.616 | **48.2%** |    499 |    1 |     **0** |      0.783 ms |

The **Worse column is zero for every workload shape**. That is the useful guarantee here: the search cannot choose something worse than the baseline because the baseline is itself included among the candidates.

`test_recommend_never_loses_to_the_default` checks the same property on another 100 workloads. A regression therefore fails the test suite instead of silently increasing waiting time.

The workload shapes generated by `bench.py` are:

* **uniform** — 3–10 processes, arrivals 0–20, bursts 4–8
* **bursty** — same process and arrival ranges, but 25% of processes receive bursts of 15–30 while the rest receive bursts of 1–4
* **batch** — every process arrives at t=0, with bursts from 1–25

### What the recommender actually picked

| Shape   | Choices                                                                      |
| ------- | ---------------------------------------------------------------------------- |
| uniform | `sjf` ×307, `srtf` ×108, `fcfs` ×85                                          |
| bursty  | `srtf` ×343, `fcfs` ×83, `sjf` ×63, `rr(q=2)` ×6, `rr(q=1)` ×4, `rr(q=4)` ×1 |
| batch   | `sjf` ×481, `fcfs` ×19                                                       |

The baseline almost never wins. Round robin with quantum 4 was selected **once out of 1,500 workloads**. Round robin with any quantum was selected only 11 times, all in the bursty workload shape.

There are two important caveats.

### Caveat 1: the metric favors SJF

The recommender is optimizing **average waiting time**, and that naturally favors SJF. SJF is optimal for average waiting time on a fixed set of jobs, so the experiment is partly asking which candidate behaves most like SJF for the given workload.

The same 1,500 workloads produce a very different ranking when scored on `avg_response`:

| Metric         | What wins                     | Baseline `rr(q=4)` |  Searched |
| -------------- | ----------------------------- | -----------------: | --------: |
| `avg_waiting`  | `sjf` 851, `srtf` 451         |              23.31 |     12.40 |
| `avg_response` | **`rr(q=1)` 1369**, `srtf` 71 |              6.836 | **1.774** |

Round robin is therefore not “bad.” It loses under the waiting-time objective because average waiting time is not what round robin is primarily designed to optimize. On average response time, round robin wins **91% of the same workloads**.

The response-time experiment can be reproduced with:

```bash
python bench.py --metric avg_response
```

### Caveat 2: FCFS selections are ties

When every process arrives together and has the same burst length, all five algorithms can produce the same waiting time. `recommend()` breaks those ties using the schedule with fewer context switches, which makes FCFS the winner.

That is intentional: if two schedules provide the same waiting time, there is a reason to prefer the one with less scheduling overhead.

### Cost

The median time to evaluate nine candidates is roughly **0.5–0.8 ms** for workloads containing 3–10 processes, using one CPU core and no parallelism.

The search is `O(candidates × total_burst × processes)`. In other words, its cost grows with the workload size rather than becoming significantly more expensive simply because more algorithms are available.

For the workloads used by this simulator, evaluating the alternatives is cheap enough that making the decision by simulation is preferable to committing to a default blindly.

---

## 5. Where these results do not apply

**These are simulated processes, not measured real workloads.** Every burst time is known exactly in advance. A real operating-system scheduler does not know the future CPU burst of a process, which is one reason production schedulers do not simply run SJF or SRTF with perfect information. They estimate future behavior from past execution and can be wrong.

A 48.9% reduction in average waiting time against an actual workload with estimated burst lengths would therefore be a different result, and this project does not measure it.

**There is no I/O, blocking, or multicore scheduling.** Every process is CPU-bound and runs on a single core. Adding I/O bursts would introduce blocked processes and additional queues, changing the behavior and accounting of all five algorithms.

**Priority scheduling can starve processes.** `workloads/bursty.json` contains four priority-1 processes, so a priority-5 process placed behind them can wait for all four. There is no aging mechanism in the implementation.

That behavior is left visible in the results rather than hidden by an additional policy, because starvation is one of the important trade-offs to observe when comparing priority scheduling.
