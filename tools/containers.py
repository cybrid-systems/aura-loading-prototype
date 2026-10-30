"""Default container specs (internal dimensions in mm, payload in kg).

Costs are *relative* freight units (20GP = 1.0), placeholders only: replace them with
real lane rates before quoting any cost saving. Override via PEICANG_CONTAINERS=<json file>.
"""
import json, os

DEFAULT = [
    # name,  L,     W,    H,    max_kg, relative_cost
    ("20GP", 5898, 2352, 2393, 28200, 1.00),
    ("40HQ", 12032, 2352, 2698, 26500, 1.60),
    ("45HC", 13556, 2352, 2698, 27700, 1.85),
]


def load(types=None):
    rows = DEFAULT
    path = os.environ.get("PEICANG_CONTAINERS")
    if path:
        rows = [tuple(r) for r in json.load(open(path, encoding="utf-8"))]
    if types:
        rows = [r for r in rows if r[0] in types]
    return rows
