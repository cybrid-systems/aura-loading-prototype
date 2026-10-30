#!/usr/bin/env python3
"""Independent feasibility checker for a kernel result JSON (does not trust the kernel).

Checks: inside container, no overlap, weight limit, support ratio >= min_support, LIFO
(no box of a later stop lies between a box and the door with y/z overlap), every box placed.
  python3 tools/verify.py result.json [min_support]
Exit 0 = feasible.
"""
import json, sys

E = 1e-3


def ov(a0, a1, b0, b1):
    return a0 < b1 - E and b0 < a1 - E


def check(r, min_support=0.75, lifo=True):
    errs = []
    if r["unplaced"]:
        errs.append(f"unplaced={len(r['unplaced'])}")
    for ci, c in enumerate(r["containers"]):
        bs = c["boxes"]
        if sum(b["kg"] for b in bs) > c["max_kg"] + E:
            errs.append(f"c{ci} overweight")
        for i, b in enumerate(bs):
            if b["x"] < -E or b["y"] < -E or b["z"] < -E or b["x"] + b["dx"] > c["L"] + E or b["y"] + b["dy"] > c["W"] + E or b["z"] + b["dz"] > c["H"] + E:
                errs.append(f"c{ci} box{i} out of bounds")
            sup = 0.0
            for j, q in enumerate(bs):
                if j == i:
                    continue
                oxy = ov(b["x"], b["x"] + b["dx"], q["x"], q["x"] + q["dx"]) and ov(b["y"], b["y"] + b["dy"], q["y"], q["y"] + q["dy"])
                if oxy and ov(b["z"], b["z"] + b["dz"], q["z"], q["z"] + q["dz"]) and j > i:
                    errs.append(f"c{ci} overlap {i},{j}")
                if oxy and abs(q["z"] + q["dz"] - b["z"]) < E:
                    sup += (min(b["x"] + b["dx"], q["x"] + q["dx"]) - max(b["x"], q["x"])) * (min(b["y"] + b["dy"], q["y"] + q["dy"]) - max(b["y"], q["y"]))
                if lifo and q["stop"] > b["stop"] and q["x"] >= b["x"] + b["dx"] - E and ov(b["y"], b["y"] + b["dy"], q["y"], q["y"] + q["dy"]) and ov(b["z"], b["z"] + b["dz"], q["z"], q["z"] + q["dz"]):
                    errs.append(f"c{ci} lifo {i} blocked by {j}")
            if b["z"] > E and sup < min_support * b["dx"] * b["dy"] - 1:
                errs.append(f"c{ci} box{i} support {sup / (b['dx'] * b['dy']):.2f}")
    return errs


if __name__ == "__main__":
    r = json.load(open(sys.argv[1]))
    e = check(r, float(sys.argv[2]) if len(sys.argv) > 2 else 0.75)
    print("OK" if not e else "\n".join(e[:20]))
    sys.exit(1 if e else 0)
