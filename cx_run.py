"""cx_run.py -- complexity census (item 1) and per-instance runtime (item 2).

WHERE IT RUNS. Copy this file into ``testing_ground/decoder/`` (next to
``dist_run.py``) and run it from ``testing_ground/``, exactly like dist_run:

    python -m decoder.cx_run --smoke            # ~2 min, checks the setup
    python -m decoder.cx_run --list             # the plan, runs nothing
    python -m decoder.cx_run --workers 8        # item 1, then item 2, then the control

Imports: ``decoder.{bench_decoder, main_decoder, sampling}``,
``main_baseline.config`` and numpy (networkx and qecsim come in through the
decoder). It refuses to run unless the three decoder files are byte-identical
to the product (SHA-256 in ``EXPECTED_SHA256``); ``--force`` overrides.

THREE PHASES, one after the other. Resumable: every finished part is its own
file, and a re-run with the same arguments skips it.

  stats    ITEM 1, our decoder only (no reference Blossom). The 115 buckets of
           the LER campaign (d 5..17, p 0.02..0.18; d 15/17 from p 0.04),
           trials 0 .. n-1 (``--n``, default 100,000), T = 40, early stopping
           on. Same sampler and seeds as the campaign (``sample_xz``, trial =
           seed). Each sector is decoded by the bench twin
           (``bench_decoder.decode`` = the product with two seams, identical
           arithmetic) with pass-through recorders on its functions: they
           read arguments and outputs, nothing is re-implemented. One row per
           sector with s >= 2 holding every quantity of the cost table (t, q,
           m, r, mutual pairs, singletons, clusters, odd clusters, N0, N1,
           spanning trees by origin, P, released pairs, r2, k2, |F|, donor
           reads, cluster sizes, ...). Every ``--lock-every``-th sector is also
           decoded by the product ``main_decoder.decode`` and the two
           matchings are compared. Times are NOT recorded here, so use every
           core.

  timing   ITEM 2, ours vs Blossom per instance. d 5..17 x p 0.05 / 0.10 / 0.15,
           the first N trials of each bucket (``TIMING_PLAN``: 100,000 where
           Blossom is cheap, down to 5,000 at d17/p0.15). Every sector with
           s > 2: the product decode and one Blossom on all of K_s
           (``_solve_cluster(W, arange(s))``, the Blossom arm of the LER
           campaign, same networkx matcher as S7), timed back to back with
           ``perf_counter``. Which goes first alternates with the parity of
           trial + sector; the garbage collector is off in these workers and
           runs between sectors, never inside a timed call. Then one more
           decode by the bench twin with stage timers (S1+S2, S3+S4, S5, S6, S7
           summed and S7's largest cluster). It is not part of the comparison,
           and its matching must equal the product's. Fewer workers
           (``--timing-workers``, default ``--workers // 2``), because
           per-instance times inflate when every core is busy.

  control  The first ``--control-k`` sectors (s > 2) of every timing bucket,
           re-timed in ONE worker process with nothing else running: how much
           the parallel timing phase inflated each arm.

OUTPUT (zip the whole folder and bring it back): ``decoder/results/cx/``

    provenance.json                       hashes, versions, machine, arguments
    stats/d{d}_p{p}/part_{lo}_{hi}.npz    one row per sector + "meta" (JSON:
                                          counters, cluster-size histograms)
    timing/d{d}_p{p}/part_{lo}_{hi}.npz   one row per timed sector + "meta"
    control/d{d}_p{p}.npz                 the single-process re-timing

``np.load(f)["meta"].item()`` is a JSON string. Sector 0 = z, 1 = x.

COST on the calibration laptop (i5-1135G7, 4 cores / 8 threads); the run
prints its own ETA after every part:

    stats    ~17 CPU-h  -> ~4 h   at --workers 8
    timing   ~16 CPU-h  -> ~4.5 h at 4 timing workers
    control  a few minutes
    output   ~0.5 GB, almost all of it stats/

CHECKS printed at the end of each phase (all must be 0): product-lock
mismatches, S3 leg-attribution mismatches, S6 ``exhausted``; gate conflicts
are expected to be 0 as well. Validated before shipping: item 1 reproduces
experiment A (complexity_runtime, 43 fields on 16,000 sectors) and the
campaign's S1-S6 replay histograms (decoder/results/dist) exactly; item 2
reproduces the campaign's exact / co-optimal / sub-optimal counts on d9/p0.15.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")          # inherited by the worker processes

import numpy as np                          # noqa: E402

from decoder import bench_decoder as BD     # noqa: E402
from decoder import main_decoder as MD      # noqa: E402
from decoder import sampling as SMP         # noqa: E402
from main_baseline.config import CACHE_DIR  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results" / "cx"
T_BP = 40                                   # the campaign's budget, not T_COMMIT = 80
DS = (5, 7, 9, 11, 13, 15, 17)

EXPECTED_SHA256 = {
    "main_decoder.py": "eb2f6409e16ef0c3be871740ae2e7d5913e5df1d601585404ad5ea74735f5fb9",
    "bench_decoder.py": "a9da43e67993c1049cd3c6f69b7eb5ee3b049ec0a9c2886e0359eecd40012b42",
    "sampling.py": "9e6f8fb38040280a7e325e402237e435eca9a59729f3e538f48590cca7a1acf9",
}

# Item 2 (option B1): trials per bucket, fixed before the run so the sample is
# a reproducible prefix of item 1's instances. 100,000 where one bucket costs
# under ~1.5 CPU-h on the calibration laptop (i5-1135G7), fewer where Blossom
# on all of K_s is expensive.
TIMING_PLAN = {
    (5, 0.05): 100_000, (5, 0.10): 100_000, (5, 0.15): 100_000,
    (7, 0.05): 100_000, (7, 0.10): 100_000, (7, 0.15): 100_000,
    (9, 0.05): 100_000, (9, 0.10): 100_000, (9, 0.15): 100_000,
    (11, 0.05): 100_000, (11, 0.10): 100_000, (11, 0.15): 50_000,
    (13, 0.05): 100_000, (13, 0.10): 50_000, (13, 0.15): 20_000,
    (15, 0.05): 100_000, (15, 0.10): 25_000, (15, 0.15): 10_000,
    (17, 0.05): 50_000, (17, 0.10): 12_000, (17, 0.15): 5_000,
}


def ler_grid():
    """The 115 (d, p) buckets of the LER campaign, p descending."""
    return [(d, round(k / 100, 2)) for d in DS
            for k in range(18, (4 if d >= 15 else 2) - 1, -1)]


# ---------------------------------------------------------------------------
# cost model -- ONLY for --list, chunk sizes and the ETA; never affects data.
# Mean s per decoded sector in the LER campaign (p = 0.02 .. 0.18), and
# single-core costs measured on the calibration laptop.
# ---------------------------------------------------------------------------
_MEAN_S_TABLE = """
5  1.3 1.9 2.5 3.0 3.5 4.1 4.5 5.0 5.4 5.9 6.3 6.7 7.0 7.4 7.7 8.0 8.3
7  2.5 3.7 4.8 5.9 6.9 7.9 8.9 9.8 10.7 11.5 12.3 13.1 13.8 14.5 15.1 15.7 16.3
9  4.2 6.1 8.0 9.8 11.5 13.1 14.7 16.2 17.7 19.0 20.3 21.6 22.8 23.9 25.0 26.0 27.0
11 6.2 9.1 11.9 14.6 17.2 19.6 22.0 24.2 26.4 28.4 30.4 32.2 34.0 35.7 37.3 38.9 40.3
13 8.7 12.7 16.6 20.4 24.0 27.4 30.7 33.8 36.8 39.7 42.4 45.0 47.5 49.9 52.1 54.3 56.3
15 - - 22.1 27.1 31.9 36.5 40.9 45.0 49.0 52.8 56.5 60.0 63.3 66.4 69.4 72.3 75.0
17 - - 28.4 34.8 41.0 46.9 52.5 57.8 63.0 67.9 72.6 77.0 81.3 85.3 89.2 92.8 96.3
"""
_MEAN_S = {}
for _line in _MEAN_S_TABLE.strip().splitlines():
    _d, *_vals = _line.split()
    for _k, _x in enumerate(_vals):
        if _x != "-":
            _MEAN_S[(int(_d), round((_k + 2) / 100, 2))] = float(_x)
_SAMPLE_MS = {5: 0.12, 7: 0.25, 9: 0.5, 11: 0.9, 13: 1.5, 15: 2.2, 17: 3.0}


def _est_ms(phase, d, p):
    """Estimated single-core ms per trial on the calibration laptop: sampling
    plus two sectors, ours ~ 0.02 s^1.33 ms (fitted to the stats phase itself,
    d 5..17), Blossom on K_s ~ 1.4e-3 s^2.86 ms (probe, d 9..17)."""
    s = _MEAN_S.get((d, round(p, 2)), 2.0 * d * d * p)
    ours = 0.02 * s ** 1.33
    if phase == "stats":
        return _SAMPLE_MS.get(d, 3.0) + 2 * 1.05 * ours
    return _SAMPLE_MS.get(d, 3.0) + 2 * (1.4e-3 * s ** 2.86 + 2 * ours)


# ---------------------------------------------------------------------------
# pass-through recorders on the bench twin (same technique as
# complexity_runtime/census.py: replace a module-global name, call the
# original, look at arguments and output). Nothing here feeds the decoder.
# ---------------------------------------------------------------------------

class _Rec:
    def __init__(self):
        self.on = False
        self.ctx: list = []
        self.cur: dict | None = None


REC = _Rec()
_ORIG: dict = {}
_LEVEL: str | None = None
_pc = time.perf_counter


def _make(name, orig, is_ctx, post, timed):
    def wrapped(*a, **k):
        R = REC
        if not R.on:
            return orig(*a, **k)
        ctx = R.ctx[-1] if R.ctx else "decode"
        if is_ctx:
            R.ctx.append(name)
        t0 = _pc() if timed else 0.0
        try:
            out = orig(*a, **k)
        finally:
            dt = (_pc() - t0) if timed else 0.0
            if is_ctx:
                R.ctx.pop()
        post(R.cur, ctx, a, k, out, dt)
        return out
    wrapped.__wrapped__ = orig
    wrapped.__name__ = name
    return wrapped


# ---- item 1 hooks ("full") -------------------------------------------------

def _f_bp(c, ctx, a, k, out, dt):
    kept, _avg, R, xc, n_rounds, stop = out
    es = stop is not None
    c["t"] = int(n_rounds)
    c["es"] = int(es)
    c["m"] = int(kept.size)
    c["r"] = int(R.size)
    # q = committed edges entering the final gate; when early stopping fired
    # M^t was already the perfect matching, so q = m
    c["q"] = int(kept.size) if es else int(np.count_nonzero(xc))
    if es:
        c["es_leg"] = 1 if c["_cpm"] else 2      # leg of the poll that fired


def _f_cpm(c, ctx, a, k, out, dt):
    c["n_polls"] += 1
    c["_cpm"] = out is not None


def _f_cxc(c, ctx, a, k, out, dt):
    c["_n_cxc"] += 1


def _f_gate(c, ctx, a, k, out, dt):
    if int(np.count_nonzero(a[0])) > int(out[0].size):
        c["gate_conflict"] += 1


_TWO = np.array([2])


def _f_fp(c, ctx, a, k, out, dt):
    s, avg, R, kept = a[0], a[1], a[2], a[3]
    released, avgM, lab0, lab1, _tree = out
    if R.size < 2 or not kept.size:
        return                                   # S3 did not run
    c["s3"] = 1
    c["released"] = len(released)
    if lab0 is not None:
        sz0 = np.bincount(lab0)
        sz1 = np.bincount(lab1)
        c["n_pair"] = int(np.count_nonzero(sz0 == 2))
        c["n_single"] = int(np.count_nonzero(sz0 == 1))
        c["k"] = int(sz1.size)
        c["n_odd"] = int(np.count_nonzero(sz1 & 1))
        c["cmax_R"] = int(sz1.max())
        c["_cR"] = sz1
    else:                                        # |R| = 2: one mutual pair, one cluster
        c["n_pair"], c["k"], c["cmax_R"] = 1, 1, 2
        c["_cR"] = _TWO
    c["_fp"] = (int(s), avg, R, kept, avgM, lab0)


def _f_price(c, ctx, a, k, out, dt):
    c["fired"] = 1


def _f_two(c, ctx, a, k, out, dt):
    c["N0"] = int(out[0].shape[0])
    c["N1"] = int(out[3].shape[0]) if out[3] is not None else 0


def _f_probe(c, ctx, a, k, out, dt):
    c["probe_hits"] = len(out)


def _f_route(c, ctx, a, k, out, dt):
    c["route_hits"] = len(out)


def _f_mst(c, ctx, a, k, out, dt):
    kk = int(a[1])
    if ctx == "_reshuffle":
        c["s6_tree"] = 1
        return
    if ctx == "fp_release":
        c["tr_test"] = 1                         # T_R of the odd-cluster test
    elif ctx == "_level01_probe":
        if kk == c["N0"] + 2:
            c["tree_pair"] += 1                  # one per mutual pair passing
        else:
            c["tree_single"] += 1                # T_0, at most one
    elif ctx == "_route_analysis":
        if kk == c["N1"]:
            c["tree_route"] += 1                 # T_1
        else:
            c["tree_res"] += 1                   # T_R rebuilt in the search
    else:
        return
    c["trees_s3"] += 1
    c["tree_ksum_s3"] += kk
    if kk > c["tree_kmax_s3"]:
        c["tree_kmax_s3"] = kk


def _f_bneck(c, ctx, a, k, out, dt):
    n = len(a[1])
    if ctx == "fp_release":
        c["reads_test"] += 1                     # C(n_odd, 2) when the odd test runs
    elif ctx == "_level01_probe":
        if n == c["N0"] + 2:
            c["reads_pair"] += 1
        else:
            c["reads_single"] += 1
    elif ctx == "_route_analysis":
        if n == c["N1"]:
            c["P"] += 1                          # priced odd-cluster pairs
        else:
            c["reads_bres"] += 1                 # b_R read in T_R


def _f_tjoin(c, ctx, a, k, out, dt):
    if ctx == "_route_analysis":
        c["F_route"] = len(out)


def _f_runs(c, ctx, a, k, out, dt):
    if ctx == "_route_analysis":
        c["runs_route"] = len(out)


def _f_clu(c, ctx, a, k, out, dt):
    if ctx != "decode":
        return                                   # S3's clustering: read off fp_release
    sz0 = np.bincount(out[1])
    c["reclustered"] = 1
    c["n_pair2"] = int(np.count_nonzero(sz0 == 2))
    c["n_single2"] = int(np.count_nonzero(sz0 == 1))


def _f_resh(c, ctx, a, k, out, dt):
    labels1 = a[0]
    tree = k["tree"] if "tree" in k else (a[2] if len(a) > 2 else None)
    lab, info = out
    c["k2"] = int(labels1.max()) + 1
    c["n_odd2"] = int(info["n_odd"])
    c["branched"] = int(info["abstained"])
    c["exhausted"] = int(info["exhausted"])
    hops = info["hops"]
    c["runs"] = len(hops)
    c["F"] = sum(hops) + len(hops)
    c["run_max"] = (max(hops) + 1) if hops else 0
    c["s6_graph"] = int(tree is None)
    sz = np.bincount(lab)
    c["_c7"] = sz[sz > 0]


def _f_topk(c, ctx, a, k, out, dt):
    c["_donor2"] += int(a[0].size) * int(a[1].size)   # twice per F-edge


_FULL = {
    "bp_commit": (True, _f_bp),
    "_complete_pm": (False, _f_cpm),
    "_commit_xc": (False, _f_cxc),
    "_gate": (False, _f_gate),
    "fp_release": (True, _f_fp),
    "_price_release": (True, _f_price),
    "_two_level": (False, _f_two),
    "_level01_probe": (True, _f_probe),
    "_route_analysis": (True, _f_route),
    "_mst_adj": (False, _f_mst),
    "_bneck": (False, _f_bneck),
    "_tjoin": (False, _f_tjoin),
    "_bridge_runs": (False, _f_runs),
    "_clustering": (False, _f_clu),
    "_reshuffle": (True, _f_resh),
    "_cluster_topk": (False, _f_topk),
}


# ---- item 2 hooks ("stage", timed) -----------------------------------------

def _s_bp(c, ctx, a, k, out, dt):
    kept, _avg, R, _xc, n_rounds, stop = out
    c["t_s12"] = dt
    c["t"] = int(n_rounds)
    c["es"] = int(stop is not None)
    c["m"] = int(kept.size)
    c["r"] = int(R.size)


def _s_fp(c, ctx, a, k, out, dt):
    c["t_s34"] = dt
    c["released"] = len(out[0])


def _s_price(c, ctx, a, k, out, dt):
    c["fired"] = 1
    c["t_price"] = dt


def _s_clu(c, ctx, a, k, out, dt):
    if ctx == "decode":
        c["t_s5"] = dt


def _s_resh(c, ctx, a, k, out, dt):
    c["t_s6"] = dt
    sz = np.bincount(out[0])
    sz = sz[sz > 0]
    c["k2"] = int(a[0].max()) + 1
    c["maxc"] = int(sz.max())
    c["n_blossom"] = int(np.count_nonzero(sz > 2))


def _s_solve(c, ctx, a, k, out, dt):
    c["t_s7_seq"] += dt
    if dt > c["t_s7_max"]:
        c["t_s7_max"] = dt


_STAGE = {
    "bp_commit": (True, _s_bp),
    "fp_release": (True, _s_fp),
    "_price_release": (True, _s_price),
    "_clustering": (False, _s_clu),
    "_reshuffle": (True, _s_resh),
    "_solve_cluster": (False, _s_solve),
}


def _install(level: str) -> None:
    global _LEVEL
    if _LEVEL == level:
        return
    for n, orig in _ORIG.items():
        setattr(BD, n, orig)
    _ORIG.clear()
    spec = _FULL if level == "full" else _STAGE
    for n, (is_ctx, post) in spec.items():
        orig = getattr(BD, n)
        _ORIG[n] = orig
        setattr(BD, n, _make(n, orig, is_ctx, post, timed=(level == "stage")))
    _LEVEL = level


def _gate_leg(s, avg, R, kept, avgM, lab0, fired, tau=MD.TAU) -> int:
    """Which S3 test fired: 0 none, 1 |R| = 2, 2 mutual pair, 3 singleton,
    4 odd clusters. Verbatim from complexity_runtime/census.py (attribution
    only, re-derived from the seam's own inputs; cross-checked against the
    observed fire, ``leg_mismatch`` must stay 0)."""
    if R.size < 2 or not kept.size:
        return 0
    if R.size == 2:
        return 1 if fired else 0
    eu, ev = MD.edge_index(s)
    C = np.concatenate((eu[kept], ev[kept]))
    i0 = np.minimum(R[:, None], C[None, :])
    j0 = np.maximum(R[:, None], C[None, :])
    blk = avg[(i0 * (2 * s - i0 - 1)) // 2 + (j0 - i0 - 1)]
    cmax = blk.max(axis=1)
    rowmax = avgM.max(axis=1)
    sizes0 = np.bincount(lab0)
    for g in np.flatnonzero(sizes0 == 2):
        da, db = (int(x) for x in np.flatnonzero(lab0 == g))
        if min(cmax[da], cmax[db]) - avgM[da, db] >= tau - 1e-12:
            return 2
    if sizes0.size >= 2:
        sing = sizes0[lab0] == 1
        if sing.any() and (cmax[sing] - rowmax[sing] >= tau - 1e-12).any():
            return 3
    return 4 if fired else 0


# ---------------------------------------------------------------------------
# the per-sector records
# ---------------------------------------------------------------------------

U1, U2, U4 = np.uint8, np.uint16, np.uint32
STATS_FIELDS = [
    # identity
    ("trial", U4), ("sector", U1), ("s", U2),
    # S1 / S2
    ("t", U1), ("es", U1), ("es_leg", U1), ("n_polls", U1), ("n_full_polls", U1),
    ("q", U2), ("m", U2), ("gate_conflict", U1), ("r", U2),
    # S3 tests (clustering of R, the tests)
    ("s3", U1), ("n_pair", U2), ("n_single", U2), ("k", U2), ("n_odd", U2),
    ("cmax_R", U2), ("tr_test", U1), ("reads_test", U2), ("leg", U1), ("fired", U1),
    # S3 searches (only when a test fired)
    ("N0", U2), ("N1", U2), ("tree_single", U1), ("tree_pair", U2),
    ("tree_route", U1), ("tree_res", U1), ("reads_single", U2), ("reads_pair", U2),
    ("P", U2), ("reads_bres", U2), ("F_route", U2), ("runs_route", U2),
    ("trees_s3", U2), ("tree_kmax_s3", U2), ("tree_ksum_s3", U4),
    ("probe_hits", U2), ("route_hits", U2), ("released", U2),
    # S4 / S5
    ("r2", U2), ("reclustered", U1), ("n_pair2", U2), ("n_single2", U2),
    ("k2", U2), ("n_odd2", U2),
    # S6
    ("s6_graph", U1), ("s6_tree", U1), ("F", U2), ("runs", U2), ("run_max", U2),
    ("branched", U1), ("exhausted", U1), ("donor_reads", U4),
    # S7 (cluster sizes after S6)
    ("n_clusters", U2), ("maxc", U2), ("c2nd", U2), ("sum_c3", U4), ("n_blossom", U2),
]
_STATS_ZERO = {f: 0 for f, _ in STATS_FIELDS}

F8, F4 = np.float64, np.float32
TIMING_FIELDS = [
    ("trial", U4), ("sector", U1), ("s", U2), ("first", U1),
    ("t_ours", F8), ("t_blossom", F8), ("t_bd", F8),
    ("t_s12", F8), ("t_s34", F8), ("t_price", F8), ("t_s5", F8), ("t_s6", F8),
    ("t_s7_seq", F8), ("t_s7_max", F8),
    ("t", U1), ("es", U1), ("m", U2), ("r", U2), ("fired", U1), ("released", U2),
    ("r2", U2), ("k2", U2), ("maxc", U2), ("n_blossom", U2),
    ("verdict", U1), ("gap", F4), ("lock", U1),
]
_TIMING_ZERO = {f: 0 for f, _ in TIMING_FIELDS}
CONTROL_FIELDS = [("trial", U4), ("sector", U1), ("s", U2), ("first", U1),
                  ("t_ours", F8), ("t_blossom", F8)]


def _to_arrays(cols, fields):
    out = {}
    for f, dt in fields:
        v = cols[f]
        if np.issubdtype(dt, np.integer):
            x = np.asarray(v, dtype=np.int64)
            if x.size and (x.min() < 0 or x.max() > np.iinfo(dt).max):
                raise ValueError(f"field {f} does not fit {np.dtype(dt).name}: "
                                 f"[{x.min()}, {x.max()}]")
            out[f] = x.astype(dt)
        else:
            out[f] = np.asarray(v, dtype=dt)
    return out


def _new_stats_cur():
    c = dict(_STATS_ZERO)
    c.update(_cpm=False, _n_cxc=0, _donor2=0, _cR=None, _c7=None, _fp=None)
    return c


def _finish_stats(c, cnt, hR, h7):
    c["n_full_polls"] = c["_n_cxc"] - (0 if c["es"] else 1)
    c["donor_reads"] = c["_donor2"] // 2
    if c["_cR"] is not None:
        hR.update(c["_cR"].tolist())
    r2 = c["r"] + 2 * c["released"]
    c["r2"] = r2
    if r2 == 2:                                  # forced pair: no S5-S7 work
        c["k2"], c["n_clusters"], c["maxc"], c["sum_c3"] = 1, 1, 2, 8
        c["n_pair2"], c["n_single2"] = 1, 0
        h7[2] += 1
    elif r2 > 2:
        if not c["reclustered"]:                 # S3's clustering was reused
            c["n_pair2"], c["n_single2"] = c["n_pair"], c["n_single"]
        sz = c["_c7"]
        c["n_clusters"] = int(sz.size)
        c["maxc"] = int(sz.max())
        c["c2nd"] = int(np.partition(sz, -2)[-2]) if sz.size >= 2 else 0
        c["sum_c3"] = int((sz.astype(np.int64) ** 3).sum())
        c["n_blossom"] = int(np.count_nonzero(sz > 2))
        h7.update(sz.tolist())
    if c["_fp"] is not None:
        s_, avg, R, kept, avgM, lab0 = c["_fp"]
        c["leg"] = _gate_leg(s_, avg, R, kept, avgM, lab0, bool(c["fired"]))
        if (c["leg"] > 0) != bool(c["fired"]):
            cnt["leg_mismatch"] += 1
    cnt["gate_conflict"] += c["gate_conflict"]
    cnt["exhausted"] += c["exhausted"]


# ---------------------------------------------------------------------------
# worker tasks
# ---------------------------------------------------------------------------

def _init_stats():
    _install("full")


def _init_timing():
    gc.disable()
    _install("stage")
    _warmup()


def _warmup():
    """Pay the one-off costs (lazy networkx import, index caches) before
    anything is timed."""
    import networkx  # noqa: F401  (the lazy import inside _solve_cluster)
    rng = np.random.default_rng(0)
    W = rng.integers(1, 10, size=(24, 24)).astype(np.float64)
    W = (W + W.T) / 2.0
    np.fill_diagonal(W, 0.0)
    for _ in range(2):
        MD.decode(W, 24, T=T_BP)
        MD._solve_cluster(W, np.arange(24))
        BD.decode(W, 24, T=T_BP)                 # REC.on is False: pass-through


def _stats_task(job):
    d, p, lo, hi, T, cache_dir, lock_every = job
    _install("full")
    cache_dir = Path(cache_dir)
    cols = {f: [] for f, _ in STATS_FIELDS}
    cnt, hR, h7 = Counter(), Counter(), Counter()
    t_start = time.time()
    for trial in range(lo, hi):
        cnt["trials"] += 1
        rec = SMP.sample_xz(d, p, trial, cache_dir)
        if rec is None:
            cnt["empty"] += 1
            continue
        for si, sec in enumerate(("z", "x")):
            sub = rec[sec]
            s = int(sub["s"])
            if s == 0:
                continue
            cnt["sectors"] += 1
            if s == 2:                           # decode() short-circuits: no BP
                cnt["forced"] += 1
                c = dict(_STATS_ZERO)
                c.update(trial=trial, sector=si, s=2)
                for f, _ in STATS_FIELDS:
                    cols[f].append(c[f])
                continue
            cnt["decoded"] += 1
            W = sub["W"]
            c = _new_stats_cur()
            REC.cur, REC.on = c, True
            REC.ctx.clear()
            try:
                match = BD.decode(W, s, T=T)
            finally:
                REC.on, REC.cur = False, None
            c.update(trial=trial, sector=si, s=s)
            _finish_stats(c, cnt, hR, h7)
            for f, _ in STATS_FIELDS:
                cols[f].append(c[f])
            if lock_every and cnt["decoded"] % lock_every == 0:
                cnt["lock_checked"] += 1
                if MD.decode(W, s, T=T) != match:
                    cnt["lock_mismatch"] += 1
    meta = {"phase": "stats", "d": d, "p": p, "lo": lo, "hi": hi, "T": T,
            "counts": dict(cnt),
            "hist_cluster_R": {str(x): v for x, v in sorted(hR.items())},
            "hist_cluster_S7": {str(x): v for x, v in sorted(h7.items())},
            "worker_s": round(time.time() - t_start, 2), "pid": os.getpid()}
    return _to_arrays(cols, STATS_FIELDS), meta


def _cost(W, pairs):
    return float(sum(W[u, v] for (u, v) in pairs))


def _time_pair(W, s, T, first):
    """(ours matching, t_ours, Blossom matching, t_blossom), back to back."""
    if first == 0:
        t0 = _pc()
        mo = MD.decode(W, s, T=T)
        t_o = _pc() - t0
        t0 = _pc()
        mb = MD._solve_cluster(np.asarray(W, dtype=np.float64), np.arange(s))
        t_b = _pc() - t0
    else:
        t0 = _pc()
        mb = MD._solve_cluster(np.asarray(W, dtype=np.float64), np.arange(s))
        t_b = _pc() - t0
        t0 = _pc()
        mo = MD.decode(W, s, T=T)
        t_o = _pc() - t0
    return mo, t_o, mb, t_b


_GC_EVERY = 50


def _timing_task(job):
    d, p, lo, hi, T, cache_dir = job
    _install("stage")
    gc.disable()
    cache_dir = Path(cache_dir)
    cols = {f: [] for f, _ in TIMING_FIELDS}
    cnt = Counter()
    t_start = time.time()
    for trial in range(lo, hi):
        cnt["trials"] += 1
        rec = SMP.sample_xz(d, p, trial, cache_dir)
        if rec is None:
            cnt["empty"] += 1
            continue
        for si, sec in enumerate(("z", "x")):
            sub = rec[sec]
            s = int(sub["s"])
            if s == 0:
                continue
            cnt["sectors"] += 1
            if s == 2:
                cnt["forced"] += 1
                continue
            W = sub["W"]
            first = (trial + si) & 1
            mo, t_o, mb, t_b = _time_pair(W, s, T, first)
            c = dict(_TIMING_ZERO)
            REC.cur, REC.on = c, True
            REC.ctx.clear()
            t0 = _pc()
            try:
                mbd = BD.decode(W, s, T=T)
            finally:
                t_bd = _pc() - t0
                REC.on, REC.cur = False, None
            gap = _cost(W, mo) - _cost(W, mb)
            verdict = 0 if gap <= 1e-9 else (1 if gap <= 0.5 else 2)
            r2 = c["r"] + 2 * c["released"]
            if r2 == 2:
                c["k2"], c["maxc"] = 1, 2
            c.update(trial=trial, sector=si, s=s, first=first, t_ours=t_o,
                     t_blossom=t_b, t_bd=t_bd, r2=r2, verdict=verdict,
                     gap=gap, lock=int(mbd == mo))
            for f, _ in TIMING_FIELDS:
                cols[f].append(c[f])
            cnt["timed"] += 1
            cnt["lock_mismatch"] += int(mbd != mo)
            cnt[("exact", "coopt", "subopt")[verdict]] += 1
            cnt["sum_t_ours_us"] += int(round(1e6 * t_o))
            cnt["sum_t_blossom_us"] += int(round(1e6 * t_b))
            if cnt["timed"] % _GC_EVERY == 0:
                gc.collect()
    gc.collect()
    meta = {"phase": "timing", "d": d, "p": p, "lo": lo, "hi": hi, "T": T,
            "counts": dict(cnt), "gc": "off inside timed calls",
            "worker_s": round(time.time() - t_start, 2), "pid": os.getpid()}
    return _to_arrays(cols, TIMING_FIELDS), meta


def _control_task(job):
    d, p, K, T, cache_dir = job
    _install("stage")                            # REC stays off: product + Blossom only
    gc.disable()
    cache_dir = Path(cache_dir)
    cols = {f: [] for f, _ in CONTROL_FIELDS}
    n, trial = 0, 0
    while n < K:
        rec = SMP.sample_xz(d, p, trial, cache_dir)
        if rec is not None:
            for si, sec in enumerate(("z", "x")):
                sub = rec[sec]
                s = int(sub["s"])
                if s <= 2:
                    continue
                first = (trial + si) & 1
                _mo, t_o, _mb, t_b = _time_pair(sub["W"], s, T, first)
                for f, v in (("trial", trial), ("sector", si), ("s", s),
                             ("first", first), ("t_ours", t_o), ("t_blossom", t_b)):
                    cols[f].append(v)
                n += 1
                if n % _GC_EVERY == 0:
                    gc.collect()
                if n >= K:
                    break
        trial += 1
    gc.collect()
    meta = {"phase": "control", "d": d, "p": p, "K": K, "T": T,
            "trials_read": trial, "pid": os.getpid()}
    return _to_arrays(cols, CONTROL_FIELDS), meta


# ---------------------------------------------------------------------------
# parent: plan, pools, part files, summaries
# ---------------------------------------------------------------------------

def _save(path: Path, arrays: dict, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez_compressed(fh, meta=np.array(json.dumps(meta)), **arrays)
    os.replace(tmp, path)                        # a part file is complete or absent


def _read_meta(path: Path) -> dict:
    with np.load(path) as z:
        return json.loads(z["meta"].item())


def _stats_path(out, d, p, lo, hi):
    return out / "stats" / f"d{d}_p{p:.2f}" / f"part_{lo:06d}_{hi:06d}.npz"


def _timing_path(out, d, p, lo, hi):
    return out / "timing" / f"d{d}_p{p:.2f}" / f"part_{lo:06d}_{hi:06d}.npz"


def _control_path(out, d, p):
    return out / "control" / f"d{d}_p{p:.2f}.npz"


def _run_pool(phase, jobs, paths, weights, fn, init, workers):
    """Run the jobs whose part file is missing; write each part as it lands."""
    todo = [i for i, pth in enumerate(paths) if not pth.exists()]
    w_tot = sum(weights)
    w_done0 = w_tot - sum(weights[i] for i in todo)
    print(f"\n### {phase}: {len(jobs)} parts, {len(jobs) - len(todo)} already done, "
          f"{len(todo)} to run on {workers} worker(s)", flush=True)
    if not todo:
        return
    t0 = time.time()
    w_new = 0.0
    ex = ProcessPoolExecutor(max_workers=workers, initializer=init)
    try:
        futs = {ex.submit(fn, jobs[i]): i for i in todo}
        for n_done, f in enumerate(as_completed(futs), 1):
            i = futs[f]
            arrays, meta = f.result()
            _save(paths[i], arrays, meta)
            w_new += weights[i]
            el = time.time() - t0
            eta = el * (w_tot - w_done0 - w_new) / max(w_new, 1e-9)
            job = jobs[i]
            print(f"  [{phase}] d={job[0]} p={job[1]:.2f} "
                  f"{Path(paths[i]).stem}  {n_done}/{len(todo)}  "
                  f"elapsed {el / 3600:.2f} h  eta {eta / 3600:.2f} h", flush=True)
    except BaseException:
        ex.shutdown(wait=True, cancel_futures=True)
        raise
    ex.shutdown(wait=True)


def _summary(phase, paths) -> dict:
    tot = Counter()
    for pth in paths:
        if pth.exists():
            tot.update(_read_meta(pth)["counts"])
    tot = dict(tot)
    if phase == "stats":
        print(f"\n=== stats summary: {tot.get('trials', 0):,} trials, "
              f"{tot.get('sectors', 0):,} sectors, {tot.get('decoded', 0):,} decoded, "
              f"{tot.get('forced', 0):,} forced (s = 2)")
        print(f"    product lock: {tot.get('lock_mismatch', 0)} mismatches in "
              f"{tot.get('lock_checked', 0):,} checked sectors (must be 0)")
        print(f"    leg mismatches {tot.get('leg_mismatch', 0)} (must be 0), "
              f"gate conflicts {tot.get('gate_conflict', 0)}, "
              f"S6 exhausted {tot.get('exhausted', 0)} (must be 0)", flush=True)
    elif phase == "timing":
        print(f"\n=== timing summary: {tot.get('timed', 0):,} timed sectors "
              f"({tot.get('forced', 0):,} with s = 2 not timed)")
        print(f"    stage decode == product: {tot.get('lock_mismatch', 0)} mismatches "
              f"(must be 0)")
        print(f"    ours vs Blossom: exact {tot.get('exact', 0):,}, co-optimal "
              f"{tot.get('coopt', 0):,}, sub-optimal {tot.get('subopt', 0):,}")
        print(f"    total time: ours {tot.get('sum_t_ours_us', 0) / 3.6e9:.2f} h, "
              f"Blossom {tot.get('sum_t_blossom_us', 0) / 3.6e9:.2f} h", flush=True)
    return tot


def _file_sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _decoder_hashes() -> dict:
    base = Path(MD.__file__).resolve().parent
    for mod in (BD, SMP):
        if Path(mod.__file__).resolve().parent != base:
            raise RuntimeError(f"{mod.__name__} loaded from {mod.__file__}, "
                               f"not from {base}")
    return {name: _file_sha(base / name) for name in EXPECTED_SHA256}


def _machine() -> dict:
    info = {"python": sys.version.split()[0], "numpy": np.__version__,
            "platform": platform.platform(), "processor": platform.processor(),
            "cpu_count": os.cpu_count(), "node": platform.node()}
    for mod in ("networkx", "qecsim", "scipy"):
        try:
            info[mod] = getattr(__import__(mod), "__version__", "?")
        except ImportError:
            info[mod] = None
    return info


def _log_provenance(out: Path, entry: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fp = out / "provenance.json"
    log = json.loads(fp.read_text()) if fp.exists() else []
    log.append(entry)
    fp.write_text(json.dumps(log, indent=2, default=str))


def _filter(buckets, ds, ps):
    return [(d, p) for d, p in buckets
            if (ds is None or d in ds) and (ps is None or round(p, 2) in ps)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=("all", "stats", "timing", "control"),
                    default="all")
    ap.add_argument("--workers", type=int, default=8, help="stats phase")
    ap.add_argument("--timing-workers", type=int, default=None,
                    help="timing phase (default: workers // 2)")
    ap.add_argument("--n", type=int, default=100_000, help="stats trials per bucket")
    ap.add_argument("--timing-n", type=int, default=None,
                    help="override every TIMING_PLAN count (tests only)")
    ap.add_argument("--control-k", type=int, default=50,
                    help="sectors re-timed per timing bucket")
    ap.add_argument("--T", type=int, default=T_BP)
    ap.add_argument("--stats-chunk", type=int, default=5000,
                    help="trials per stats part file")
    ap.add_argument("--lock-every", type=int, default=100,
                    help="compare with main_decoder.decode every N decoded sectors")
    ap.add_argument("--d", default=None, help="restrict to these d, e.g. 13,17")
    ap.add_argument("--p", default=None, help="restrict to these p, e.g. 0.10")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--cache-dir", default=str(CACHE_DIR))
    ap.add_argument("--smoke", action="store_true",
                    help="tiny run of all three phases into results/cx_smoke")
    ap.add_argument("--list", action="store_true", help="print the plan, run nothing")
    ap.add_argument("--force", action="store_true",
                    help="run even if the decoder files differ from the product")
    a = ap.parse_args()

    hashes = _decoder_hashes()
    bad = [n for n, h in hashes.items() if h != EXPECTED_SHA256[n]]
    if bad:
        msg = (f"decoder files differ from the product: {bad}. The results would "
               f"not describe the thesis decoder.")
        if not a.force:
            sys.exit("REFUSED: " + msg + " (--force to run anyway)")
        print("WARNING: " + msg, flush=True)

    ds = None if a.d is None else {int(x) for x in a.d.split(",") if x}
    ps = None if a.p is None else {round(float(x), 2) for x in a.p.split(",") if x}
    out = Path(a.out_dir)
    cache = Path(a.cache_dir)
    workers = max(1, a.workers)
    t_workers = max(1, a.timing_workers or workers // 2)
    stats_b = _filter(ler_grid(), ds, ps)
    plan = {k: v for k, v in TIMING_PLAN.items() if k in set(_filter(TIMING_PLAN, ds, ps))}
    n_stats, chunk, lock_every, K = a.n, a.stats_chunk, a.lock_every, a.control_k
    if a.timing_n is not None:
        plan = {k: a.timing_n for k in plan}
    if a.smoke:
        stats_b = [(9, 0.10), (13, 0.18)]
        n_stats, chunk, lock_every, K = 400, 200, 10, 5
        plan = {(9, 0.10): 100, (13, 0.15): 40}
        out = out.parent / "cx_smoke"

    def t_chunk(d, p):
        return max(100, min(5000, int(120_000 / _est_ms("timing", d, p)) // 100 * 100))

    stats_jobs = [(d, p, lo, min(lo + chunk, n_stats), a.T, str(cache), lock_every)
                  for d, p in stats_b for lo in range(0, n_stats, chunk)]
    timing_jobs = [(d, p, lo, min(lo + t_chunk(d, p), n), a.T, str(cache))
                   for (d, p), n in plan.items() for lo in range(0, n, t_chunk(d, p))]
    control_jobs = [(d, p, K, a.T, str(cache)) for d, p in plan]

    cpu_s = sum((j[3] - j[2]) * _est_ms("stats", j[0], j[1]) for j in stats_jobs) / 3.6e6
    cpu_t = sum((j[3] - j[2]) * _est_ms("timing", j[0], j[1]) for j in timing_jobs) / 3.6e6
    print(f"decoder files: {'product (SHA-256 OK)' if not bad else 'NOT the product'}; "
          f"output -> {out}")
    print(f"stats : {len(stats_b)} buckets x {n_stats:,} trials, {len(stats_jobs)} parts, "
          f"~{cpu_s:.1f} CPU-h (i5-1135G7 estimate), {workers} workers")
    print(f"timing: {len(plan)} buckets, {sum(plan.values()):,} trials, "
          f"{len(timing_jobs)} parts, ~{cpu_t:.1f} CPU-h (same estimate), "
          f"{t_workers} workers")
    print(f"control: {len(control_jobs)} buckets x {K} sectors, one process")
    if a.list:
        for (d, p), n in plan.items():
            print(f"   timing d={d:>2} p={p:.2f}: {n:>7,} trials, part size "
                  f"{t_chunk(d, p):,}, ~{n * _est_ms('timing', d, p) / 3.6e6:.2f} CPU-h")
        return

    for d in sorted({b[0] for b in stats_b} | {b[0] for b in plan}):
        SMP.geometry_xz(d, cache)       # write the weight cache before any worker exists

    _log_provenance(out, {"event": "start", "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "argv": sys.argv, "args": vars(a), "phase": a.phase,
                          "script_sha256": _file_sha(__file__),
                          "decoder_sha256": hashes, "machine": _machine(),
                          "stats_buckets": stats_b, "n_stats": n_stats,
                          "timing_plan": {f"{d}|{p:.2f}": n for (d, p), n in plan.items()},
                          "workers": workers, "timing_workers": t_workers,
                          "control_k": K, "lock_every": lock_every})
    t0 = time.time()

    if a.phase in ("all", "stats"):
        paths = [_stats_path(out, *j[:4]) for j in stats_jobs]
        _run_pool("stats", stats_jobs, paths,
                  [(j[3] - j[2]) * _est_ms("stats", j[0], j[1]) for j in stats_jobs],
                  _stats_task, _init_stats, workers)
        summ = _summary("stats", paths)
        _log_provenance(out, {"event": "stats done",
                              "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "summary": summ})

    if a.phase in ("all", "timing"):
        paths = [_timing_path(out, *j[:4]) for j in timing_jobs]
        _run_pool("timing", timing_jobs, paths,
                  [(j[3] - j[2]) * _est_ms("timing", j[0], j[1]) for j in timing_jobs],
                  _timing_task, _init_timing, t_workers)
        summ = _summary("timing", paths)
        _log_provenance(out, {"event": "timing done",
                              "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "summary": summ})

    if a.phase in ("all", "control"):
        paths = [_control_path(out, d, p) for d, p in plan]
        _run_pool("control", control_jobs, paths,
                  [K * _est_ms("timing", j[0], j[1]) for j in control_jobs],
                  _control_task, _init_timing, 1)
        _log_provenance(out, {"event": "control done",
                              "time": time.strftime("%Y-%m-%d %H:%M:%S")})

    print(f"\nall done in {(time.time() - t0) / 3600:.2f} h -> {out}\n"
          f"zip that folder and bring it back.", flush=True)


if __name__ == "__main__":
    main()
