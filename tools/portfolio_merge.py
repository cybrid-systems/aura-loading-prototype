#!/usr/bin/env python3
"""Merge per-seed portfolio matrices (synthetic runs) into one multi-seed matrix.

  python3 tools/portfolio_merge.py --dir out/v02/train --out out/v02/train/matrix_merged.json

means = mean of the per-seed means (each shard is one seed), vars = variance across
shard means.  A member/instance mismatch is a hard error: a silent reordering
would corrupt select:offline's feature model.
"""
import argparse, glob, json, os, statistics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    shards = sorted(glob.glob(os.path.join(a.dir, "matrix_s*.json")))
    if not shards:
        raise SystemExit("no matrix_s*.json in " + a.dir)
    mats = [json.load(open(p)) for p in shards]
    members = mats[0]["members"]
    insts = mats[0]["instances"]
    for m in mats[1:]:
        if m["members"] != members or m["instances"] != insts:
            raise SystemExit("shard mismatch in " + a.dir)
    means, vars_ = [], []
    for i in range(len(insts)):
        row_m, row_v = [], []
        for j in range(len(members)):
            vals = [float(m["means"][i][j]) for m in mats]
            row_m.append(round(statistics.fmean(vals), 6))
            row_v.append(round(statistics.variance(vals), 8) if len(vals) > 1 else 0.0)
        means.append(row_m)
        vars_.append(row_v)
    seeds = [m["seeds"][0] if m.get("seeds") else k + 1 for k, m in enumerate(mats)]
    json.dump({"members": members, "instances": insts, "seeds": seeds,
               "means": means, "vars": vars_, "shards": [os.path.basename(p) for p in shards]},
              open(a.out, "w"), indent=1)
    print("merged %d shards -> %s (%d instances x %d members)" % (len(shards), a.out, len(insts), len(members)))


if __name__ == "__main__":
    main()
