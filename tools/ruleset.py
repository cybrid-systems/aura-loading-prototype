#!/usr/bin/env python3
"""客户/线路规则文件（S-expression）的解析、安全底线和方案复核。

和 aura/rules.aura 的 rules->kernel-args / check-plan 对齐。
语法或键名错误带行号；不改 C++ 源码就能换成另一份文件。
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARD_NUM = ("min-support", "lifo", "hazmat-sep", "max-kg")
HARD_SYM = {"only-type": 1, "no-mix": 2}
CHECK_NUM = {"cog-x": 2, "cog-y": 2, "max-unplaced": 1, "end-load": 1, "min-vol-util": 1}
PREFER_NUM = ("cost", "vol-util", "cog-dev", "unplaced")
REPEATABLE = {("hard", "no-mix")}
FLOOR = {"lifo": 1, "min-support": 0.75, "hazmat-sep": 1000}


class RuleError(Exception):
    def __init__(self, path: str, line: int, message: str):
        self.path = path
        self.line = line
        self.message = message
        text = message
        if line and path:
            try:
                raw = Path(path).read_text(encoding="utf-8").splitlines()
            except OSError:
                raw = []
            if 0 < line <= len(raw):
                src = raw[line - 1].strip()
                if src and src not in text:
                    text = f"{text}：{src}"
        where = f"{path}:{line}" if line else str(path)
        super().__init__(f"{where}: {text}")


class Quoted(str):
    """双引号字符串，和裸符号区分开。说明文字必须是这种。"""


@dataclass
class Rule:
    kind: str
    name: str
    args: list
    doc: str
    line: int
    path: str = ""

    def key(self):
        return (self.kind, self.name, tuple(self.args))


@dataclass
class Parser:
    text: str
    path: str
    i: int = 0
    line: int = 1

    def peek(self) -> str:
        return self.text[self.i] if self.i < len(self.text) else ""

    def bump(self) -> str:
        ch = self.text[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
        return ch

    def err(self, message: str):
        raw = self.text.splitlines()
        snippet = raw[self.line - 1].strip() if 0 < self.line <= len(raw) else ""
        if snippet:
            message = f"{message}：{snippet}"
        raise RuleError(self.path, self.line, message)

    def skip(self):
        while self.i < len(self.text):
            ch = self.peek()
            if ch in " \t\r\n":
                self.bump()
            elif ch == ";" and self.text[self.i : self.i + 2] == ";;":
                while self.i < len(self.text) and self.peek() != "\n":
                    self.bump()
            else:
                return

    def parse_form(self):
        self.skip()
        if self.i >= len(self.text):
            self.err("文件在这里结束了，规则列表没有写完")
        ch = self.peek()
        if ch == "(":
            return self.parse_list()
        if ch == '"':
            return self.parse_string()
        if ch == ")":
            self.err("多了一个右括号")
        return self.parse_atom()

    def parse_list(self):
        start = self.line
        self.bump()
        items = []
        while True:
            self.skip()
            if self.i >= len(self.text):
                self.line = start
                self.err("列表没有闭合的 )")
            if self.peek() == ")":
                self.bump()
                return items
            items.append(self.parse_form())

    def parse_string(self):
        self.bump()
        buf = []
        while self.i < len(self.text):
            ch = self.bump()
            if ch == '"':
                return Quoted("".join(buf))
            if ch == "\\":
                if self.i >= len(self.text):
                    self.err("字符串没有结束的引号")
                buf.append(self.bump())
                continue
            if ch == "\n":
                self.err("字符串不能换行，引号要在同一行关上")
            buf.append(ch)
        self.err("字符串没有结束的引号")

    def parse_atom(self):
        start = self.i
        while self.i < len(self.text) and self.peek() not in " \t\r\n();\"":
            self.bump()
        token = self.text[start : self.i]
        if not token:
            self.err("这里应该是数字、名字或括号")
        if _is_int(token):
            return int(token)
        if _is_float(token):
            return float(token)
        return token


def _is_int(token: str) -> bool:
    if token in ("", "-", "+"):
        return False
    body = token[1:] if token[0] in "+-" else token
    return body.isdigit()


def _is_float(token: str) -> bool:
    if token.count(".") != 1:
        return False
    left, right = token.split(".")
    if left in ("", "-", "+"):
        return False
    lb = left[1:] if left[0] in "+-" else left
    return lb.isdigit() and right.isdigit() and right != ""


def parse_rules(path: str | Path) -> list[Rule]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise RuleError(str(path), 0, f"读不到文件（{e.strerror}）") from e
    _find_line.seen = {}
    parser = Parser(text, str(path))
    parser.skip()
    if parser.i >= len(parser.text):
        parser.err("文件是空的")
    if parser.peek() != "(":
        parser.err("规则文件应以 ((hard ...) ...) 这样的列表开头")
    form = parser.parse_form()
    parser.skip()
    if parser.i < len(parser.text):
        parser.err("规则列表后面还有多余内容")
    if not isinstance(form, list):
        raise RuleError(str(path), 1, "规则文件应是一个列表，例如 ((hard lifo 1 \"...\") ...)")
    rules = []
    seen: dict[tuple[str, str], Rule] = {}
    for item in form:
        rules.append(_as_rule(item, str(path), seen))
    return rules


def _as_rule(item, path: str, seen: dict) -> Rule:
    if not isinstance(item, list) or len(item) < 3:
        raise RuleError(path, 1, "每一条规则要写成 (类别 名称 参数... \"说明\")")
    kind, name = item[0], item[1]
    if not isinstance(kind, str) or isinstance(kind, Quoted):
        raise RuleError(path, 1, "规则类别必须是 hard、check 或 prefer")
    if kind not in ("hard", "check", "prefer"):
        raise RuleError(path, 1, f"未知类别 {kind}（只能是 hard、check、prefer）")
    if not isinstance(name, str) or isinstance(name, Quoted):
        raise RuleError(path, 1, "规则名称要写成不带引号的键，例如 no-mix")
    doc = item[-1]
    args = item[2:-1]
    line = _find_line(path, kind, name)
    if not isinstance(doc, Quoted):
        raise RuleError(path, line, f"键 {kind} {name} 的最后一项说明要用双引号")
    shape = _check_shape(kind, name, args)
    if shape:
        raise RuleError(path, line, shape)
    rule = Rule(kind, name, list(args), str(doc), line, path)
    ident = (kind, name)
    if ident not in REPEATABLE:
        if ident in seen:
            raise RuleError(
                path,
                rule.line,
                f"键 {kind} {name} 重复了（第 {seen[ident].line} 行已经有一条）。留一条即可",
            )
        seen[ident] = rule
    return rule


def _find_line(path: str, kind: str, name: str) -> int:
    """按文件里第 N 次出现定位。parse_rules 开头会清空计数。"""
    import re

    text = Path(path).read_text(encoding="utf-8")
    pat = re.compile(rf"\({re.escape(kind)}\s+{re.escape(name)}\b")
    matches = list(pat.finditer(text))
    key = (path, kind, name)
    idx = _find_line.seen.get(key, 0)
    _find_line.seen[key] = idx + 1
    if idx >= len(matches):
        return 1
    return text[: matches[idx].start()].count("\n") + 1


_find_line.seen = {}


def _check_shape(kind: str, name: str, args: list) -> str | None:
    def bad_nums(k: int) -> bool:
        return len(args) != k or not all(isinstance(a, (int, float)) and not isinstance(a, bool) for a in args)

    def bad_syms(k: int) -> bool:
        return len(args) != k or not all(isinstance(a, str) and not isinstance(a, Quoted) for a in args)

    if kind == "hard" and name in HARD_NUM:
        if bad_nums(1):
            return f"键 {kind} {name} 需要 1 个数字，再加上双引号说明"
        if name == "min-support" and not 0 <= args[0] <= 1:
            return f"键 min-support 的值 {args[0]} 不在 0 到 1 之间"
        if name == "lifo" and args[0] not in (0, 1):
            return f"键 lifo 只能是 0 或 1，收到 {args[0]}"
        if name == "hazmat-sep" and args[0] < 0:
            return f"键 hazmat-sep 不能是负数，收到 {args[0]}"
        if name == "max-kg" and args[0] <= 0:
            return f"键 max-kg 需要正数，收到 {args[0]}"
        return None
    if kind == "hard" and name == "allow-types":
        if not args or not all(isinstance(a, str) and not isinstance(a, Quoted) for a in args):
            return "键 allow-types 至少要一个柜型名（不带引号），例如 20GP 40HQ"
        return None
    if kind == "hard" and name in HARD_SYM:
        if bad_syms(HARD_SYM[name]):
            return f"键 {kind} {name} 需要 {HARD_SYM[name]} 个不带引号的名字，再加上双引号说明"
        if name == "no-mix" and args[0] == args[1]:
            return f"键 no-mix 的两边都是 {args[0]}，禁混装需要两个不同品类"
        return None
    if kind == "check" and name in CHECK_NUM:
        if bad_nums(CHECK_NUM[name]):
            return f"键 {kind} {name} 需要 {CHECK_NUM[name]} 个数字，再加上双引号说明"
        return None
    if kind == "prefer" and name in PREFER_NUM:
        if bad_nums(1):
            return f"键 {kind} {name} 需要 1 个数字，再加上双引号说明"
        return None
    known = {
        "hard": list(HARD_NUM) + ["allow-types", *HARD_SYM],
        "check": list(CHECK_NUM),
        "prefer": list(PREFER_NUM),
    }[kind]
    return f"未知键 {kind} {name}。这一类可用：{'、'.join(known)}"


def floor_issues(rules: list[Rule]) -> list[str]:
    """安全底线只能收紧。缺了或写小了都拒绝热替换。"""
    issues = []
    for name, lo in FLOOR.items():
        found = [r for r in rules if r.kind == "hard" and r.name == name]
        if not found:
            issues.append(f"缺少安全底线 hard {name}（不能低于 {lo}）")
        elif found[0].args[0] < lo:
            issues.append(f"{found[0].path}:{found[0].line}: {name}={found[0].args[0]} 低于安全底线 {lo}")
    return issues


def changes(base: list[Rule], new: list[Rule]) -> list[str]:
    b = {r.key() for r in base}
    n = {r.key() for r in new}
    lines = []
    for kind, name, args in sorted(n - b, key=lambda x: (x[0], x[1], x[2])):
        lines.append(f"新增 {kind} {name} {' '.join(_num(a) for a in args)}".rstrip())
    for kind, name, args in sorted(b - n, key=lambda x: (x[0], x[1], x[2])):
        lines.append(f"删去 {kind} {name} {' '.join(_num(a) for a in args)}".rstrip())
    return lines


def _num(value) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "g")
    return str(value)


def kernel_args(rules: list[Rule]) -> str:
    """与 aura/rules.aura 的 rules->kernel-args 同一个键序。"""
    hard = {(r.name): r for r in rules if r.kind == "hard" and r.name != "no-mix"}
    mix = [r for r in rules if r.kind == "hard" and r.name == "no-mix"]
    check = {r.name: r for r in rules if r.kind == "check"}
    parts = []
    if "min-support" in hard:
        parts.append(f"min_support={_num(hard['min-support'].args[0])}")
    if "lifo" in hard:
        parts.append(f"lifo={_num(hard['lifo'].args[0])}")
    if "hazmat-sep" in hard:
        parts.append(f"hazmat_sep={_num(hard['hazmat-sep'].args[0])}")
    if "only-type" in hard:
        parts.append(f"only={hard['only-type'].args[0]}")
    if "allow-types" in hard:
        parts.append("types=" + ",".join(str(a) for a in hard["allow-types"].args))
    if "max-kg" in hard:
        parts.append(f"cap_kg={_num(hard['max-kg'].args[0])}")
    if mix:
        parts.append("no_mix=" + ",".join(f"{r.args[0]}+{r.args[1]}" for r in mix))
    if "cog-x" in check:
        lo, hi = check["cog-x"].args
        parts.append(f"cog_x_lo={_num(lo)}")
        parts.append(f"cog_x_hi={_num(hi)}")
    if "cog-y" in check:
        lo, hi = check["cog-y"].args
        parts.append(f"cog_y_lo={_num(lo)}")
        parts.append(f"cog_y_hi={_num(hi)}")
    return " ".join(parts)


def sku_class(sku: str) -> str:
    return sku.split("-", 1)[0]


def _r3(x: float) -> float:
    return round(x * 1000) / 1000


def check_plan(rules: list[Rule], plan: dict) -> list[str]:
    """方案复核。硬约束里只复核内核不一定能回头看旧方案的那些（柜型、限重、禁混装）。"""
    metrics = plan.get("metrics") or {}
    containers = plan.get("containers") or []
    bad = []
    for rule in rules:
        name = rule.name
        if rule.kind == "check" and name == "max-unplaced":
            if metrics.get("unplaced", 0) > rule.args[0]:
                bad.append(f"未装货物 {metrics.get('unplaced', 0)} 件")
        elif rule.kind == "check" and name in ("cog-x", "cog-y"):
            idx = 0 if name == "cog-x" else 1
            for c in containers:
                cog = c.get("cog") or [0.5, 0.5, 0]
                v = cog[idx]
                if v < rule.args[0] or v > rule.args[1]:
                    bad.append(f"{c.get('type', '?')} {name}={_r3(v)} 超出 [{rule.args[0]},{rule.args[1]}]")
        elif rule.kind == "check" and name == "end-load":
            for c in containers:
                ends = c.get("end_load_kg") or {}
                front, door = ends.get("front", 0), ends.get("door", 0)
                if max(front, door) > rule.args[0]:
                    bad.append(f"{c.get('type', '?')} 端部载荷 {round(max(front, door))}kg > {rule.args[0]}")
        elif rule.kind == "check" and name == "min-vol-util":
            if metrics.get("vol_util", 0) < rule.args[0]:
                bad.append(f"体积利用率 {_r3(metrics.get('vol_util', 0))} < {rule.args[0]}")
        elif rule.kind == "hard" and name == "only-type":
            want = str(rule.args[0])
            for c in containers:
                if c.get("type", "") != want:
                    bad.append(f"规则 only-type：柜型 {c.get('type', '?')} 不在允许列表（只要 {want}）")
        elif rule.kind == "hard" and name == "allow-types":
            ok = {str(a) for a in rule.args}
            for c in containers:
                if c.get("type", "") not in ok:
                    bad.append(f"规则 allow-types：柜型 {c.get('type', '?')} 不在允许列表")
        elif rule.kind == "hard" and name == "max-kg":
            for c in containers:
                if c.get("kg", 0) > rule.args[0]:
                    bad.append(f"规则 max-kg：{c.get('type', '?')} 毛重 {round(c.get('kg', 0))}kg > {rule.args[0]}")
        elif rule.kind == "hard" and name == "no-mix":
            a, b = str(rule.args[0]), str(rule.args[1])
            for c in containers:
                classes = {sku_class(box.get("sku", "")) for box in c.get("boxes") or []}
                if a in classes and b in classes:
                    bad.append(f"规则 no-mix：{c.get('type', '?')} 同柜混装了 {a} 与 {b}")
    return bad


def same_args(left: str, right: str) -> bool:
    def kv(s: str) -> dict[str, str]:
        out = {}
        for tok in s.split():
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            out[k] = v
        return out

    a, b = kv(left), kv(right)
    if a.keys() != b.keys():
        return False
    for key in a:
        try:
            if abs(float(a[key]) - float(b[key])) > 1e-6:
                return False
        except ValueError:
            if a[key] != b[key]:
                return False
    return True


@dataclass
class PackResult:
    plan: dict | None
    code: int
    stdout: str = ""
    stderr: str = ""
    argv: list = field(default_factory=list)


def pack(problem: str | Path, rules: list[Rule], out: str | Path, extra: list[str] | None = None) -> PackResult:
    binary = ROOT / "build" / "pack"
    if not binary.is_file():
        raise RuleError(str(binary), 0, "还没有内核。先运行 python3 build.py")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(binary), "--in", str(problem), "--out", str(out), *kernel_args(rules).split(), *(extra or [])]
    proc = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
    plan = None
    if out.is_file() and out.stat().st_size:
        try:
            plan = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan = None
    return PackResult(plan, proc.returncode, proc.stdout or "", proc.stderr or "", argv)


FAST = ["algo=block", "space=0", "w_vol=1", "w_yz=0.5", "width=1", "noise=0", "time_ms=200"]


def metrics_of(plan: dict | None) -> dict:
    if not plan:
        return {}
    return plan.get("metrics") or {}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python3 tools/ruleset.py <规则文件>", file=sys.stderr)
        sys.exit(2)
    try:
        rules = parse_rules(sys.argv[1])
    except RuleError as e:
        print(f"失败（规则）：{e}", file=sys.stderr)
        sys.exit(2)
    for issue in floor_issues(rules):
        print(f"安全底线：{issue}")
    print(kernel_args(rules))
