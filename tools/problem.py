"""Write the kernel's line-based problem format (docs/FORMAT.md)."""


def _tok(s):
    s = str(s).strip().replace(" ", "_")
    return s if s else "-"


def write(path, items, containers, rules=None, limits=None):
    limits = limits or {}
    with open(path, "w", encoding="utf-8") as f:
        f.write("# C name L W H max_kg cost limit(-1=unlimited)\n")
        for (n, L, W, H, kg, cost) in containers:
            f.write(f"C {n} {L} {W} {H} {kg} {cost} {limits.get(n, -1)}\n")
        f.write("# I id sku l w h kg qty rot(0=any,1=upright,2=fixed) max_top_kg fragile stop hazmat\n")
        for it in items:
            f.write("I {id} {sku} {l} {w} {h} {kg} {qty} {rot} {max_top} {fragile} {stop} {hazmat}\n".format(
                id=_tok(it["id"]), sku=_tok(it.get("sku", it["id"])), l=it["l"], w=it["w"], h=it["h"], kg=it["kg"],
                qty=int(it.get("qty", 1)), rot=int(it.get("rot", 1)), max_top=it.get("max_top", 1e9),
                fragile=1 if it.get("fragile") else 0, stop=int(it.get("stop", 1)), hazmat=_tok(it.get("hazmat", "") or "-")))
        for k, v in (rules or {}).items():
            f.write(f"R {k} {v}\n")
