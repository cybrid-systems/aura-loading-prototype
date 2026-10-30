#!/usr/bin/env python3
"""Import customer cargo lists (xlsx / csv, Chinese or English headers) into kernel problem files.

Customer data never goes into this repo: put it in a local directory and point PEICANG_DATA at it.

  # 1) look at the structure only (sheet names, headers, row counts; no cell values are printed)
  PEICANG_DATA=/path/to/data python3 tools/import_xlsx.py inspect
  # 2) convert: one problem file per order (or per sheet when there is no order column)
  PEICANG_DATA=/path/to/data python3 tools/import_xlsx.py convert --out out/real
     [--map mapping.json]   # optional {"field": "header text"} overrides, see FIELDS below
If the sheet also carries an existing loading plan (container no./type per line), convert records the
number/types of containers actually used per order in <out>/import_report.json; tools/bench.py then adds
an "EXIST 现有方案" column. Assumptions: weight = per box (per line ÷ qty if you know it is a line total),
unload order = order of first appearance of the destination column, missing upright column = upright only.
Forwarder loading manifests (container label above the header, 件数/实重/方数 as line totals, carton size in one
"55×45×35cm" column, continuation lines without 件数) become one problem per sheet = one existing container
(--group sheet / auto, --existing-type 45HC); lines without dimensions are skipped or estimated (--est-dims).
Pure standard library (zipfile + xml), no openpyxl needed.
"""
import argparse, csv, glob, json, os, re, statistics, sys, zipfile
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(__file__))
import containers, problem

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

# field -> header synonyms (lower-cased substring match, first hit wins)
FIELDS = {
    "order": ["订单号", "订单", "单号", "委托号", "提单号", "booking", "order", "po"],
    "sku": ["sku", "货号", "物料编码", "物料号", "品号", "型号", "item", "part"],
    "name": ["品名", "货物名称", "名称", "description", "desc"],
    "l": ["长", "length", "len", "l(mm)", "l(cm)"],
    "w": ["宽", "width", "w(mm)", "w(cm)"],
    "h": ["高", "height", "h(mm)", "h(cm)"],
    "kg": ["毛重", "单件重", "单箱重", "实重", "重量", "weight", "gw", "kg"],
    "qty": ["箱数", "件数", "数量", "qty", "quantity", "ctns", "pcs"],
    "cbm": ["体积", "立方", "方数", "cbm", "volume", "m3"],
    "dims": ["货品尺寸", "外箱尺寸", "箱规", "尺寸", "规格尺寸", "dimension", "carton size", "dims"],
    "stop": ["卸货顺序", "目的港", "卸货港", "站点", "pod", "stop", "destination"],
    "upright": ["不可倒置", "朝上", "向上", "this side up", "upright", "可倒置", "倒置"],
    "stack": ["堆叠", "可叠", "限压", "承重", "stack"],
    "fragile": ["易碎", "fragile"],
    "hazmat": ["危险品", "危险", "dg", "hazmat", "un"],
    "container_no": ["柜号", "箱号", "container no", "cntr no", "container_no"],
    "container_type": ["柜型", "箱型", "container type", "cntr type", "size"],
}


def col_idx(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels}
    sheets = {}
    for s in wb.find("m:sheets", NS):
        tgt = rmap[s.get(RNS)].lstrip("/")
        tgt = tgt if tgt.startswith("xl/") else "xl/" + tgt
        rows = []
        for row in ET.fromstring(z.read(tgt)).iter("{%s}row" % NS["m"]):
            vals = {}
            for c in row.findall("m:c", NS):
                v = c.find("m:v", NS); t = c.get("t")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
                else:
                    val = v.text if v is not None else ""
                vals[col_idx(c.get("r"))] = val
            if vals:
                rows.append([vals.get(i, "") for i in range(max(vals) + 1)])
        sheets[s.get("name")] = rows
    return sheets


def read_any(path):
    if path.lower().endswith((".xlsx", ".xlsm")):
        return read_xlsx(path)
    if path.lower().endswith(".csv"):
        for enc in ("utf-8-sig", "gb18030"):
            try:
                return {os.path.basename(path): list(csv.reader(open(path, encoding=enc)))}
            except UnicodeDecodeError:
                pass
    return {}


def data_files(root):
    out = []
    for p in sorted(glob.glob(os.path.join(root, "**", "*"), recursive=True)):
        if p.lower().endswith(".zip"):
            d = p + ".d"
            if not os.path.isdir(d):
                zipfile.ZipFile(p).extractall(d)
        if p.lower().endswith((".xlsx", ".xlsm", ".csv")) and not os.path.basename(p).startswith("~$"):
            out.append(p)
    return out


def find_header(rows):
    """header row = the first row (within 15) that matches the most field synonyms"""
    best, bi = -1, 0
    for i, r in enumerate(rows[:15]):
        hits = sum(1 for f in FIELDS if match_col([str(x) for x in r], f) is not None)
        if hits > best:
            best, bi = hits, i
    return bi


def match_col(header, field, override=None):
    if override and field in override:
        return header.index(override[field]) if override[field] in header else None
    hl = [h.strip().lower() for h in header]
    for syn in FIELDS[field]:
        for i, h in enumerate(hl):
            if syn in h and not (field == "l" and ("宽" in h or "高" in h)):
                return i
    return None


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def unit_scale(header_text, values):
    h = header_text.lower()
    if "mm" in h or "毫米" in h: return 1
    if "cm" in h or "厘米" in h: return 10
    if re.search(r"\(m\)|（m）|米", h): return 1000
    med = statistics.median(values) if values else 0
    return 1000 if med < 5 else 10 if med < 300 else 1


def truthy(x):
    s = str(x).strip().lower()
    return s in ("1", "y", "yes", "true", "是", "√", "✓", "x") or "不可" in s


# headers whose value is a per-line total (forwarder loading manifests: 件数 / 实重 / 方数), not per box
LINE_TOTAL = ("实重", "总重", "总毛重", "方数", "总方数", "总体积", "total")


def is_line_total(header_text):
    return any(k in header_text.lower() for k in LINE_TOTAL)


def parse_dims(x):
    """'55×45×35cm' / '55*45*35' / '550x450x350mm' -> (l, w, h, scale_to_mm or None); None if not three numbers"""
    s = str(x).strip().lower()
    m = re.match(r"^\s*([\d.]+)\s*[×x*xX]\s*([\d.]+)\s*[×x*xX]\s*([\d.]+)\s*(mm|cm|m)?", s)
    if not m:
        return None
    unit = m.group(4)
    return float(m.group(1)), float(m.group(2)), float(m.group(3)), {"mm": 1, "cm": 10, "m": 1000}.get(unit)


# generic carton aspect ratio used only when a line has a volume but no dimensions (--est-dims)
EST_ASPECT = (1.25, 1.0, 0.9)


def est_dims(cbm_per_box):
    k = (cbm_per_box * 1e9 / (EST_ASPECT[0] * EST_ASPECT[1] * EST_ASPECT[2])) ** (1 / 3)
    return tuple(round(a * k) for a in EST_ASPECT)


def sheet_container(rows, hi):
    """sheet-level container label above the header (e.g. a '柜号' cell followed by a value, or a title row)"""
    for r in rows[:hi]:
        cells = [str(x).strip() for x in r]
        for i, c in enumerate(cells):
            if c in ("柜号", "箱号", "container no", "container no.") and i + 1 < len(cells) and cells[i + 1]:
                return cells[i + 1]
    for r in rows[:hi]:
        cells = [str(x).strip() for x in r if str(x).strip()]
        if len(cells) == 1:
            return cells[0]
    return None


def inspect(root):
    for p in data_files(root):
        for name, rows in read_any(p).items():
            hi = find_header(rows) if rows else 0
            hdr = [str(x) for x in rows[hi]] if rows else []
            mapped = {f: hdr[c] for f in FIELDS if (c := match_col(hdr, f)) is not None}
            print(json.dumps({"file": os.path.relpath(p, root), "sheet": name, "rows": len(rows) - hi - 1,
                              "header_row": hi + 1, "headers": hdr, "mapped": mapped}, ensure_ascii=False))


def convert(root, out, override=None, group="auto", existing_type=None, est=False):
    """group: order = one problem per order id; sheet = one problem per sheet (a loading manifest of one container);
    auto = sheet when the sheet carries a container label above the header and has no per-line container column."""
    os.makedirs(out, exist_ok=True)
    cts = containers.load(); report = []
    for p in data_files(root):
        for sname, rows in read_any(p).items():
            if not rows:
                continue
            hi = find_header(rows); hdr = [str(x) for x in rows[hi]]
            col = {f: match_col(hdr, f, override) for f in FIELDS}
            has_lwh = all(col[f] is not None for f in ("l", "w", "h"))
            if not has_lwh and col["dims"] is None and not (est and col["cbm"] is not None):
                report.append({"sheet": sname, "skipped": "no dimensions (L/W/H or size column; --est-dims needs a volume column)",
                               "mapped": {f: c for f, c in col.items() if c is not None}})
                continue
            body = [r for r in rows[hi + 1:] if any(str(x).strip() for x in r)]
            get = lambda r, f: r[col[f]] if col[f] is not None and col[f] < len(r) else ""
            sc = {d: unit_scale(hdr[col[d]], [v for r in body if (v := num(get(r, d)))]) for d in ("l", "w", "h")} if has_lwh else None
            kg_tot = col["kg"] is not None and is_line_total(hdr[col["kg"]])
            cbm_tot = col["cbm"] is not None and is_line_total(hdr[col["cbm"]])
            label = sheet_container(rows, hi)
            g = group if group != "auto" else ("sheet" if label and col["container_no"] is None else "order")
            stops, orders, existing = {}, {}, {}
            n_est = n_skip = 0; cbm_decl = 0.0; kg_all = 0.0
            for k, r in enumerate(body):
                q = num(get(r, "qty")) if col["qty"] is not None else 1
                if not q:
                    continue  # continuation line (extra goods description inside the same cartons) or blank
                qty = int(q)
                kg = num(get(r, "kg")) or 0.0
                kg_box = kg / qty if kg_tot else kg
                cbm = num(get(r, "cbm"))
                cbm_box = (cbm / qty if cbm_tot else cbm) if cbm else None
                cbm_decl += (cbm_box or 0) * qty; kg_all += kg_box * qty
                dims = None
                if has_lwh:
                    l, w, h = (num(get(r, d)) for d in ("l", "w", "h"))
                    if l and w and h:
                        dims = (round(l * sc["l"]), round(w * sc["w"]), round(h * sc["h"]))
                elif col["dims"] is not None and (pd := parse_dims(get(r, "dims"))):
                    l, w, h, s = pd
                    s = s or unit_scale(hdr[col["dims"]], [max(l, w, h)])
                    dims = (round(l * s), round(w * s), round(h * s))
                if dims is None and est and cbm_box:
                    dims = est_dims(cbm_box); n_est += qty
                if dims is None:
                    n_skip += qty
                    continue
                st = str(get(r, "stop")).strip()
                stop = stops.setdefault(st, len(stops) + 1)
                o = sname if g == "sheet" else (str(get(r, "order")).strip() or sname)
                it = dict(id=f"L{k+1}", sku=f"L{k+1}", l=dims[0], w=dims[1], h=dims[2], kg=round(kg_box, 3), qty=qty,
                          rot=1 if (col["upright"] is None or truthy(get(r, "upright"))) else 0,
                          fragile=col["fragile"] is not None and truthy(get(r, "fragile")),
                          stop=stop, hazmat=str(get(r, "hazmat")).strip() if col["hazmat"] is not None and truthy(get(r, "hazmat")) else "")
                orders.setdefault(o, []).append(it)
                cn, ctp = str(get(r, "container_no")).strip(), str(get(r, "container_type")).strip()
                if cn:
                    existing.setdefault(o, {})[cn] = ctp or existing_type or "?"
            if g == "sheet" and (label or group == "sheet") and sname in orders and not existing.get(sname):
                existing[sname] = {label or sname: existing_type or "?"}  # the sheet itself is the manifest of one loaded container
            sid = len({r.get("source_sheet") for r in report if "file" in r})
            for i, (o, items) in enumerate(orders.items()):
                # anonymised file names: real order ids / container labels stay out of every output that might be shared
                fn = os.path.join(out, f"real_{sid:02d}_{i:03d}.txt")
                problem.write(fn, items, cts)
                report.append({"file": os.path.basename(fn), "source_sheet": sname, "group": g, "lines": len(items),
                               "boxes": sum(x["qty"] for x in items), "unit_scale": sc,
                               "kg": round(sum(x["kg"] * x["qty"] for x in items), 1),
                               "cbm_items": round(sum(x["l"] * x["w"] * x["h"] * x["qty"] for x in items) / 1e9, 3),
                               "cbm_declared": round(cbm_decl, 3) if g == "sheet" else None,
                               "boxes_dims_estimated": n_est if g == "sheet" else None,
                               "boxes_skipped_no_dims": n_skip if g == "sheet" else None,
                               "existing_containers": existing.get(o, {}) and len(existing[o]),
                               "existing_types": sorted(set(existing.get(o, {}).values()))})
    json.dump(report, open(os.path.join(out, "import_report.json"), "w"), ensure_ascii=False, indent=1)
    print(f"converted {sum(1 for r in report if 'file' in r)} problems into {out} (see import_report.json)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inspect", "convert"])
    ap.add_argument("--out", default="out/real")
    ap.add_argument("--map")
    ap.add_argument("--group", choices=["auto", "order", "sheet"], default="auto",
                    help="sheet = each sheet is the manifest of one loaded container (one problem per sheet)")
    ap.add_argument("--existing-type", help="container type of the existing plan when the sheet only names the container (e.g. 40HQ)")
    ap.add_argument("--est-dims", action="store_true",
                    help="lines without dimensions: estimate a carton from volume/qty (aspect 1.25:1:0.9); counted in import_report")
    a = ap.parse_args()
    root = os.environ.get("PEICANG_DATA")
    if not root or not os.path.isdir(root):
        sys.exit("set PEICANG_DATA to the local directory holding the customer files")
    if a.cmd == "inspect":
        inspect(root)
    else:
        convert(root, a.out, json.load(open(a.map, encoding="utf-8")) if a.map else None, a.group, a.existing_type, a.est_dims)


if __name__ == "__main__":
    main()
