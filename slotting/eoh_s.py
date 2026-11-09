"""EoH-S: a tiny evolutionary search over slotting heuristics (k <= 3).

Part B of #4947.  A candidate is one point of the `core.assign_weighted` family

    priority(i) = -(w_i^p * m3_i^q * group_mass_i^r)

so a "heuristic" is the triple (p, q, r).  Candidates are scored on training
windows from a *different* synthetic seed; a candidate is KEEP only when adding
it to the incumbent greedy portfolio improves the portfolio's per-window best
cost by a strictly positive margin (leave-one-out).  Proposals and the
KEEP/DROP decision are returned as an audit list (written to the run JSON).
"""
import random

import core

BOUNDS = dict(p=(0.2, 3.0), q=(-1.0, 2.0), r=(-1.0, 2.0))
KEEP_MAX = 3


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def propose(rng, base=None, scale=0.5):
    if base is None:
        return dict(p=round(rng.uniform(*BOUNDS["p"]), 3),
                    q=round(rng.uniform(*BOUNDS["q"]), 3),
                    r=round(rng.uniform(*BOUNDS["r"]), 3))
    out = {}
    for k, (lo, hi) in BOUNDS.items():
        out[k] = round(_clamp(base[k] + rng.gauss(0.0, scale), lo, hi), 3)
    return out


def assign(params, weights, data):
    return core.assign_weighted(weights, data, params["p"], params["q"], params["r"])


def evaluate(params, train):
    """Mean relative cost against the greedy turnover incumbent over train windows.

    train: list of (data, weights, Cost-on-plan-sample).
    """
    rel = []
    for data, weights, c in train:
        ref = c.total(core.assign_turnover(weights, data))
        if not ref:
            continue
        rel.append((c.total(assign(params, weights, data)) - ref) / ref)
    return sum(rel) / max(1, len(rel))


def margin(params, train):
    """Leave-one-out gain of the candidate over the incumbent greedy portfolio."""
    gains = []
    for data, weights, c in train:
        incumbents = [c.total(core.assign_turnover(weights, data)),
                      c.total(core.assign_abc(weights, data)),
                      c.total(core.assign_affinity(weights, data))]
        base = min(incumbents)
        if not base:
            continue
        with_c = min(base, c.total(assign(params, weights, data)))
        gains.append((base - with_c) / base)
    return sum(gains) / max(1, len(gains))


def evolve(train, seed, gens=6, pop=10, keep_max=KEEP_MAX, log=None):
    """Return (kept, audit); kept is [(params, margin)] with margin > 0."""
    rng = random.Random(seed)
    first = [propose(rng) for _ in range(pop)]
    scored = sorted(((evaluate(c, train), c) for c in first), key=lambda t: t[0])
    audit = []
    for g in range(gens):
        parents = [c for _, c in scored[:max(2, pop // 3)]]
        fresh = [propose(rng, c) for c in parents for _ in range(3)]
        fresh += [propose(rng) for _ in range(max(1, pop // 3))]
        scored = sorted(scored[:2] + [(evaluate(c, train), c) for c in fresh], key=lambda t: t[0])[:pop]
        best_rel, best = scored[0]
        audit.append(dict(kind="proposal", gen=g + 1, p=best["p"], q=best["q"], r=best["r"],
                          rel=round(best_rel, 5), margin="", status="candidate"))
        if log:
            log(audit[-1])

    kept = []
    for rel, params in scored:
        if len(kept) >= keep_max:
            break
        m = margin(params, train)
        status = "KEEP" if m > 0 else "DROP"
        audit.append(dict(kind="leave-one-out", gen="loo", p=params["p"], q=params["q"], r=params["r"],
                          rel=round(rel, 5), margin=round(m, 5), status=status))
        if log:
            log(audit[-1])
        if m > 0:
            kept.append((params, round(m, 5)))
    return kept, audit
