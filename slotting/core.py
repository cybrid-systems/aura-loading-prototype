"""Synthetic warehouse slotting: cost model, constructors, local search.

Part B of #4947.  Synthetic data only (see gen_slotting.py).

Travel of one order is the classic single-pass estimate

    travel(order) = 2 * max(x) + (max(x) - min(x))

over the horizontal pick coordinates x of the SKUs in the order; a window cost
is the mean over the window's orders.  Evaluating a swap only changes the
orders that contain one of the two SKUs, so `Cost` keeps a SKU -> order index
and a per-order sorted-x cache to score moves incrementally.  Callers keep the
cache in sync by using the `apply_*` helpers (or `sync`).
"""
import json
import random
import statistics


def load(path):
    with open(path) as f:
        return json.load(f)


def fits(slot, sku):
    """Hard constraints: hazmat isolation, no heavy SKU on the top level, capacity."""
    if sku["hazmat"] != (slot["aisle"] == 5):
        return False
    if sku["kg"] > 25 and slot["level"] == 2:
        return False
    if sku["m3"] > slot["cap_m3"] or sku["kg"] > slot["cap_kg"]:
        return False
    return True


def violations(assign, data):
    """Hard-constraint violations of an assignment (0 == feasible)."""
    slots, skus = data["slots"], data["skus"]
    bad = 0
    for i, s in enumerate(assign):
        if s < 0 or not fits(slots[s], skus[i]):
            bad += 1
    return bad


class Cost:
    """Mean order travel for one window, with incremental swap/shift deltas."""

    def __init__(self, data, orders):
        self.data = data
        self.slots = data["slots"]
        self.orders = [sorted(set(o)) for o in orders]
        self.n = len(data["skus"])
        self.x = [s["x"] for s in self.slots]
        self.by_sku = [[] for _ in range(self.n)]
        for oi, ids in enumerate(self.orders):
            for i in ids:
                self.by_sku[i].append(oi)
        self._ord = None

    # ---- full evaluation -------------------------------------------------
    @staticmethod
    def order_cost(xs):
        return 2.0 * xs[-1] + (xs[-1] - xs[0]) if xs else 0.0

    def total(self, assign):
        xs = self.x
        tot = 0.0
        for ids in self.orders:
            u = sorted({xs[assign[i]] for i in ids if assign[i] >= 0})
            if u:
                tot += 2.0 * u[-1] + (u[-1] - u[0])
        return tot / max(1, len(self.orders))

    def order_costs(self, assign):
        xs = self.x
        out = []
        for ids in self.orders:
            u = sorted({xs[assign[i]] for i in ids if assign[i] >= 0})
            out.append(self.order_cost(u))
        return out

    def cvar(self, assign, q=0.1):
        """Mean of the worst q fraction of order costs (tail risk)."""
        costs = sorted(c for c in self.order_costs(assign) if c > 0)
        if not costs:
            return 0.0
        k = max(1, int(round(q * len(costs))))
        return statistics.fmean(costs[-k:])

    def aisle_load(self, assign):
        cnt = [0.0] * self.data["layout"]["aisles"]
        for ids in self.orders:
            for i in ids:
                if assign[i] >= 0:
                    cnt[self.slots[assign[i]]["aisle"]] += 1
        return cnt

    def aisle_var(self, assign):
        load = self.aisle_load(assign)
        tot = sum(load) or 1.0
        return statistics.pvariance([v / tot for v in load])

    # ---- incremental evaluation -----------------------------------------
    def sync(self, assign):
        xs = self.x
        self._ord = [sorted({xs[assign[i]] for i in ids if assign[i] >= 0}) for ids in self.orders]
        return self

    def delta_swap(self, assign, a, b):
        sa, sb = assign[a], assign[b]
        if sa < 0 or sb < 0 or sa == sb:
            return 0.0
        xs = self.x
        xa, xb = xs[sa], xs[sb]
        d = 0.0
        for oi in set(self.by_sku[a]) | set(self.by_sku[b]):
            after = sorted({xb if i == a else (xa if i == b else xs[assign[i]])
                            for i in self.orders[oi] if assign[i] >= 0})
            d += self.order_cost(after) - self.order_cost(self._ord[oi])
        return d / max(1, len(self.orders))

    def apply_swap(self, assign, a, b):
        xs = self.x
        assign[a], assign[b] = assign[b], assign[a]
        for oi in set(self.by_sku[a]) | set(self.by_sku[b]):
            self._ord[oi] = sorted({xs[assign[i]] for i in self.orders[oi] if assign[i] >= 0})

    def delta_shift(self, assign, a, slot):
        old = assign[a]
        if old == slot or old < 0:
            return 0.0
        xs = self.x
        xo, xn = xs[old], xs[slot]
        d = 0.0
        for oi in self.by_sku[a]:
            after = sorted({xn if i == a else xs[assign[i]] for i in self.orders[oi] if assign[i] >= 0})
            d += self.order_cost(after) - self.order_cost(self._ord[oi])
        return d / max(1, len(self.orders))

    def apply_shift(self, assign, a, slot):
        xs = self.x
        assign[a] = slot
        for oi in self.by_sku[a]:
            self._ord[oi] = sorted({xs[assign[i]] for i in self.orders[oi] if assign[i] >= 0})


# ---------------------------------------------------------------------------
# constructors
# ---------------------------------------------------------------------------
def _free_slots(data):
    slots = data["slots"]
    return sorted(range(len(slots)), key=lambda s: (slots[s]["x"], slots[s]["level"]))


def place(data, priority):
    """Greedy along x: give each SKU in `priority` order the first free slot it
    fits.  Every constructor goes through here, so capacity / level / hazmat
    handling is identical everywhere."""
    slots, skus = data["slots"], data["skus"]
    free = _free_slots(data)
    used = set()
    out = [-1] * len(skus)
    for i in priority:
        for s in free:
            if s in used or not fits(slots[s], skus[i]):
                continue
            out[i] = s
            used.add(s)
            break
    return out


def assign_abc(weights, data):
    return place(data, sorted(range(len(data["skus"])),
                              key=lambda i: -weights[i] * data["skus"][i]["m3"]))


def assign_turnover(weights, data):
    return place(data, sorted(range(len(data["skus"])), key=lambda i: -weights[i]))


def assign_affinity(weights, data):
    groups = {}
    for i, k in enumerate(data["skus"]):
        groups.setdefault(k["group"], []).append(i)
    order = []
    for _, members in sorted(groups.items(), key=lambda kv: -sum(weights[i] for i in kv[1])):
        order.extend(sorted(members, key=lambda i: -weights[i]))
    return place(data, order)


def assign_weighted(weights, data, p=1.0, q=0.0, r=0.0):
    """EoH-S family: priority = -(w^p * m3^q * group_mass^r)."""
    skus = data["skus"]
    gmass = {}
    for i, k in enumerate(skus):
        gmass[k["group"]] = gmass.get(k["group"], 0.0) + weights[i]
    def score(i):
        return -((weights[i] ** p) * ((skus[i]["m3"] + 1e-6) ** q)
                 * ((gmass[skus[i]["group"]] + 1e-6) ** r))
    return place(data, sorted(range(len(skus)), key=score))


# ---------------------------------------------------------------------------
# local search
# ---------------------------------------------------------------------------
def local_search(assign, cost, data, rng, iters, shift_prob=0.3):
    """Swap + shift descent on mean travel from `assign`.

    `iters` is the evaluation budget: one swap or one shift probe each.
    Returns (assignment, cost).
    """
    a = list(assign)
    cost.sync(a)
    slots, skus = data["slots"], data["skus"]
    free = [s for s in range(len(slots)) if s not in set(a)]
    cur = cost.total(a)
    for _ in range(iters):
        if free and rng.random() < shift_prob:
            x = rng.randrange(cost.n)
            s = free[rng.randrange(len(free))]
            if not fits(slots[s], skus[x]):
                continue
            d = cost.delta_shift(a, x, s)
            if d < -1e-12:
                old = a[x]
                cost.apply_shift(a, x, s)
                free.remove(s)
                free.append(old)
                cur += d
        else:
            x, y = rng.randrange(cost.n), rng.randrange(cost.n)
            if x == y or a[x] == a[y]:
                continue
            if not fits(slots[a[y]], skus[x]) or not fits(slots[a[x]], skus[y]):
                continue
            d = cost.delta_swap(a, x, y)
            if d < -1e-12:
                cost.apply_swap(a, x, y)
                cur += d
    return a, cost.total(a)
