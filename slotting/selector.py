"""select:offline -- a tiny learned selector for the synthetic slotting portfolio.

The scenario's online layer sees, at the start of every window, a *forecast*
demand distribution (never the window's realised orders).  For each portfolio
member we can therefore compute cheap forecast features:

    pred        plan-sample mean travel of the member's assignment
    pred_cvar   plan-sample CVaR90 of the per-order travel
    pred_gap    (pred - best pred) / best pred

Structural window features (entropy, top-share, total-variation drift) describe
the regime.  `OfflineSelector` fits a ridge regression that predicts the
member's *realised* relative gap from those features, using training windows
from other synthetic seeds.  At run time it picks the member with the smallest
predicted gap.  Pure stdlib; the model is small (k + 6 weights).
"""
import math


def entropy(weights):
    n = len(weights)
    h = -sum(w * math.log(w + 1e-12) for w in weights if w > 0)
    return h / math.log(n)


def top_share(weights, k=10):
    return sum(sorted(weights, reverse=True)[:k])


def tv(a, b):
    return 0.5 * sum(abs(x - y) for x, y in zip(a, b))


def window_features(weights, prev_weights, window=None):
    """Forecast features of one window.

    `window` is the forecast's order-structure block (size range, sampler,
    cohesion).  It is visible before the week starts, so using it is causal; it
    is what lets the selector learn "baskets want the affinity member, pallet
    picks want the pair packer" instead of guessing from the demand vector
    alone.
    """
    wf = dict(entropy=entropy(weights), top10=top_share(weights),
              tv=tv(weights, prev_weights) if prev_weights else 0.0)
    size, coh, grp = 3.0, 0.0, 0.0
    if window:
        lo, hi = window.get("size", (1, 5))
        size = 0.5 * (lo + hi)
        coh = float(window.get("cohesion", 0.0))
        grp = 1.0 if window.get("sampler") in ("grouped", "paired") else 0.0
    wf.update(size=size / 10.0, cohesion=coh, structure=grp)
    return wf


class OfflineSelector:
    """Ridge regression on (features -> realised normalised gap)."""

    def __init__(self, members, ridge=1e-2):
        self.members = list(members)
        self.ridge = ridge
        self.w = None
        self.nfeat = None

    # ---- feature construction -------------------------------------------
    def vector(self, member, pred, pred_cvar, best_pred, wf):
        k = len(self.members)
        idx = self.members.index(member)
        r = pred / best_pred if best_pred else 1.0
        onehot = [1.0 if i == idx else 0.0 for i in range(k)]
        return ([1.0, r, pred_cvar / best_pred if best_pred else 1.0,
                 wf["tv"], wf["entropy"], wf["top10"], r * wf["tv"],
                 wf.get("size", 0.3), wf.get("cohesion", 0.0),
                 wf.get("structure", 0.0),
                 r * wf.get("size", 0.3), r * wf.get("cohesion", 0.0)] + onehot)

    # ---- fitting ---------------------------------------------------------
    def fit(self, rows):
        """rows: list of (x, y) with y = realised normalised gap."""
        if not rows:
            raise ValueError("no training rows")
        n = len(rows[0][0])
        self.nfeat = n
        XtX = [[0.0] * n for _ in range(n)]
        Xty = [0.0] * n
        for x, y in rows:
            for i in range(n):
                Xty[i] += x[i] * y
                for j in range(n):
                    XtX[i][j] += x[i] * x[j]
        for i in range(n):
            XtX[i][i] += self.ridge
        self.w = _solve(XtX, Xty)
        return self

    def predict(self, x):
        return sum(wi * xi for wi, xi in zip(self.w, x))

    def pick(self, feats):
        """feats: list of (member, vector); returns (member, predicted gap)."""
        return min(((m, self.predict(v)) for m, v in feats), key=lambda t: t[1])


def _solve(A, b):
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    M = [list(row) + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            continue
        M[c], M[p] = M[p], M[c]
        pv = M[c][c]
        for r in range(n):
            if r == c:
                continue
            f = M[r][c] / pv
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]
