#!/usr/bin/env python3
"""编译装箱内核，并收拢 README「运行」一节里的命令。

  python3 build.py                  编译 kernel/pack.cpp → build/pack
  python3 build.py demo             order_10：求解、校验、生成 out/r.html
  python3 build.py demo --block     块构造内核 → out/b.json，同样校验并生成 html
  python3 build.py aura main        多 Agent（需 AURA_BIN）
  python3 build.py --help           全部子命令

不带额外参数时使用 README 里的默认值。参数直接接在子命令后面。
环境变量盖过这些默认值。CXX / CXXFLAGS 传给编译器；--debug 用 -O0 -g；--force 强制重编。
"""
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = [ROOT / "kernel" / "pack.cpp", ROOT / "kernel" / "blocks.hpp"]
BINARY = ROOT / "build" / "pack"
STAMP = ROOT / "build" / "pack.flags"

DEBUG = False
FORCE = False

COMMANDS = (
    "kernel", "clean", "demo", "pack", "verify", "viz", "aura", "bench",
    "consolidate", "matrix", "pk", "synthetic", "pool", "import", "test", "help",
)

AURA_ENTRY = {
    "main": "aura/main.aura",
    "evolve": "aura/evolve-main.aura",
    "tune": "aura/tune-main.aura",
    "consolidate": "aura/consolidate-main.aura",
}

CONS_PRESET = {
    "nf": ["--groups", "examples/pool/pools.json", "--algo", "nf", "--types", "45HC", "--out", "out/cons-nf"],
    "ff": ["--groups", "examples/pool/pools.json", "--algo", "ff", "--types", "45HC", "--out", "out/cons-ff"],
    "ffd": ["--groups", "examples/pool/pools.json", "--algo", "ffd", "--types", "45HC", "--out", "out/cons-ffd"],
    "lns": ["--groups", "examples/pool/pools.json", "--algo", "lns", "--time-s", "120", "--out", "out/cons-lns"],
}


def say(*parts):
    print(*parts, flush=True)


def sh_quote(s):
    if not s:
        return "''"
    ok = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:=+-")
    if all(c in ok for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def order_list(pattern):
    paths = sorted(ROOT.glob(pattern))
    if not paths:
        sys.exit(f"没有匹配的订单：{pattern}")
    return " ".join(str(p.relative_to(ROOT)) for p in paths)


def flag_sig(cxx):
    mode = "debug" if DEBUG else "release"
    opt = "-O0 -g" if DEBUG else "-O2"
    return "\n".join([mode, cxx, os.environ.get("CXXFLAGS", ""), opt, "-std=c++20 -Wall -Werror"]) + "\n"


def compile_kernel():
    """g++ -O2 -std=c++20 -Wall -Werror -o build/pack kernel/pack.cpp"""
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    cxx = os.environ.get("CXX") or shutil.which("g++") or shutil.which("c++")
    if not cxx:
        sys.exit("找不到 g++。需要支持 C++20 的编译器，或设置 CXX。")
    sig = flag_sig(cxx)
    fresh = (
        not FORCE
        and BINARY.is_file()
        and STAMP.is_file()
        and STAMP.read_text() == sig
        and all(BINARY.stat().st_mtime >= src.stat().st_mtime for src in SOURCES)
    )
    if fresh:
        say("up to date: build/pack")
        return BINARY
    opt = ["-O0", "-g"] if DEBUG else ["-O2"]
    extra = os.environ.get("CXXFLAGS", "").split()
    tmp = BINARY.with_name("pack.tmp")
    cmd = [cxx, *opt, "-std=c++20", "-Wall", "-Werror", *extra, "-o", str(tmp), str(SOURCES[0])]
    say("+", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        sys.exit(result.returncode)
    os.replace(tmp, BINARY)
    os.chmod(BINARY, 0o755)
    STAMP.write_text(sig)
    say("built build/pack")
    return BINARY


def run(cmd, env=None):
    say("+", " ".join(sh_quote(str(c)) for c in cmd))
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    if result.returncode != 0:
        sys.exit(result.returncode)


def run_py(rel, args):
    run([sys.executable, str(ROOT / rel), *args])


def run_pack(args):
    binary = compile_kernel()
    for i, arg in enumerate(args):
        if arg == "--out" and i + 1 < len(args):
            Path(args[i + 1]).parent.mkdir(parents=True, exist_ok=True)
    run([str(binary), *args])


def take(args, flag):
    if flag not in args:
        return None, args
    i = args.index(flag)
    if i + 1 >= len(args):
        sys.exit(f"{flag} 需要一个值")
    value = args[i + 1]
    return value, args[:i] + args[i + 2:]


def cmd_clean(_args):
    removed = False
    for path in (BINARY, STAMP, BINARY.with_name("pack.tmp")):
        if path.exists():
            path.unlink()
            removed = True
    say("removed build/pack" if removed else "nothing to clean")


def cmd_demo(args):
    if args[:1] == ["--help"] or args[:1] == ["-h"]:
        say("python3 build.py demo [--block] [--in FILE] [--out FILE] [--time-ms N]")
        return
    block = "--block" in args
    args = [a for a in args if a != "--block"]
    inp, args = take(args, "--in")
    out, args = take(args, "--out")
    time_ms, args = take(args, "--time-ms")
    if args:
        sys.exit(f"demo 不认识参数：{' '.join(args)}")
    inp = inp or "examples/synthetic/order_10.txt"
    out = out or ("out/b.json" if block else "out/r.json")
    time_ms = time_ms or ("2000" if block else "3000")
    pack_args = ["--in", inp, "--out", out, f"time_ms={time_ms}"]
    if block:
        pack_args += ["algo=block", "space=0", "w_vol=1", "w_yz=0.5"]
    run_pack(pack_args)
    run_py("tools/verify.py", [out])
    run_py("tools/viz.py", [out, str(Path(out).with_suffix(".html"))])


def cmd_pack(args):
    if not args:
        run_pack([])
        return
    run_pack(args)


def cmd_verify(args):
    if not args:
        sys.exit("用法：python3 build.py verify result.json [min_support]")
    run_py("tools/verify.py", args)


def cmd_viz(args):
    if len(args) < 2:
        sys.exit("用法：python3 build.py viz result.json out.html [--title TEXT]")
    run_py("tools/viz.py", args)


def fill_defaults(env, spec):
    applied = {}
    for key, value in spec.items():
        if env.get(key):
            continue
        got = value() if callable(value) else value
        env[key] = got
        applied[key] = got
    return applied


def cmd_aura(args):
    if not args or args[0] in ("-h", "--help"):
        say("python3 build.py aura {main|evolve|tune|consolidate} [KEY=VALUE ...]")
        say("  main          PC_ORDERS=order_01 order_07  PC_OUT=out/aura")
        say("  evolve        PC_ORDERS=order_01–04  PC_FEEDBACK=examples/feedback.synthetic.txt  PC_OUT=out/evo")
        say("  tune          PC_TRAIN=order_01–06  PC_HOLDOUT=order_1*  PC_GENS=3  PC_OUT=out/tune")
        say("  consolidate   PC_CONS_GROUPS=examples/pool/pools.json  PC_OUT=out/cons-aura  PC_CONS_TIME_S=30")
        say("也可以直接给 aura 文件：python3 build.py aura aura/main.aura")
        sys.exit(0 if args else 2)
    name, overrides = args[0], args[1:]
    if name in AURA_ENTRY:
        entry = AURA_ENTRY[name]
        spec = {
            "main": {
                "PC_ORDERS": "examples/synthetic/order_01.txt examples/synthetic/order_07.txt",
                "PC_OUT": "out/aura",
            },
            "evolve": {
                "PC_ORDERS": lambda: order_list("examples/synthetic/order_0[1-4].txt"),
                "PC_FEEDBACK": "examples/feedback.synthetic.txt",
                "PC_OUT": "out/evo",
            },
            "tune": {
                "PC_TRAIN": lambda: order_list("examples/synthetic/order_0[1-6].txt"),
                "PC_HOLDOUT": lambda: order_list("examples/synthetic/order_1*.txt"),
                "PC_GENS": "3",
                "PC_OUT": "out/tune",
            },
            "consolidate": {
                "PC_CONS_GROUPS": "examples/pool/pools.json",
                "PC_OUT": "out/cons-aura",
                "PC_CONS_TIME_S": "30",
            },
        }[name]
    elif name.endswith(".aura"):
        entry, spec = name, {}
    else:
        sys.exit(f"未知 Aura 入口 {name}。可选：main evolve tune consolidate")
    env = os.environ.copy()
    applied = fill_defaults(env, spec)
    for item in overrides:
        if "=" not in item:
            sys.exit(f"额外参数写成 KEY=VALUE，收到 {item}")
        key, value = item.split("=", 1)
        env[key] = value
        applied[key] = value
    if not env.get("AURA_BIN"):
        sys.exit("请设置 AURA_BIN 指向 aura 可执行文件")
    if not shutil.which("script"):
        sys.exit("需要 util-linux 的 script 命令（给 aura 一个 pty，否则 stdout 块缓冲）")
    compile_kernel()
    cmd = ["script", "-qc", f"scripts/aura.sh {entry}", "/dev/null"]
    prefix = " ".join(f"{k}={sh_quote(v)}" for k, v in applied.items())
    say("+", prefix, " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    sys.exit(result.returncode)


def wants_help(args):
    return "-h" in args or "--help" in args


def cmd_bench(args):
    if not wants_help(args):
        compile_kernel()
    if not args:
        args = ["--orders", "examples/synthetic", "--out", "out/bench", "--time-ms", "2000", "--strategies", "--aura"]
    run_py("tools/bench.py", args)


def cmd_consolidate(args):
    if not wants_help(args):
        compile_kernel()
    if not args:
        args = CONS_PRESET["lns"]
    elif args[0] in CONS_PRESET:
        args = CONS_PRESET[args[0]] + args[1:]
    run_py("tools/consolidate.py", args)


def cmd_matrix(args):
    if not wants_help(args):
        compile_kernel()
    if not args:
        problems = sorted(glob.glob("examples/synthetic/order_*.txt"))
        if not problems:
            sys.exit("examples/synthetic 下没有 order_*.txt")
        args = ["--problems", *problems, "--out", "out/matrix.json", "--time-ms", "2000"]
    elif args == ["--report"]:
        args = ["--report", "out/matrix.json"]
    run_py("tools/agent_matrix.py", args)


def cmd_pk(args):
    if not args:
        sys.exit(
            "pk 需要参数，例如：\n"
            "  python3 build.py pk --problems examples/synthetic --plans 甲=dirA 乙=dirB --ours-ms 2000 --md out/pk.md"
        )
    if not wants_help(args):
        compile_kernel()
    run_py("tools/pk.py", args)


def cmd_synthetic(args):
    if not args:
        args = ["--orders", "12", "--seed", "7", "--out", "examples/synthetic"]
    run_py("tools/gen_synthetic.py", args)


def cmd_pool(args):
    if not args:
        args = ["--routes", "6", "--seed", "11", "--out", "examples/pool"]
    run_py("tools/gen_pool.py", args)


def cmd_import(args):
    if not args:
        args = ["inspect"]
    run_py("tools/import_xlsx.py", args)


def cmd_test(args):
    if args:
        sys.exit("test 不接受参数")
    script = ROOT / "tests" / "run_tests.sh"
    run(["bash", str(script)])


def cmd_help(_args):
    say(__doc__.strip())
    say()
    say("子命令：")
    say("  kernel                 编译（默认）")
    say("  clean                  删除 build/pack")
    say("  demo [--block]         order_10 求解 + verify + viz")
    say("  pack --in ... --out ...  把参数原样交给内核")
    say("  verify / viz           转给 tools/verify.py、tools/viz.py")
    say("  aura NAME [K=V]        main | evolve | tune | consolidate")
    say("  bench [args]           默认合成基准，2s，--strategies --aura")
    say("  consolidate [nf|ff|ffd|lns] [args]")
    say("                         默认 lns，120s；nf/ff/ffd 只用 45HC")
    say("  matrix [--report]      贡献矩阵；--report 读 out/matrix.json")
    say("  pk [args]              转给 tools/pk.py（没有默认参赛方）")
    say("  synthetic / pool       重新生成已提交的合成数据")
    say("  import [inspect|convert] [args]   真实数据，需 PEICANG_DATA")
    say("  test                   tests/run_tests.sh")
    say()
    say("全局：--debug  --force    环境变量 CXX、CXXFLAGS 会传给编译器")


DISPATCH = {
    "kernel": lambda args: compile_kernel() if not args else sys.exit("kernel 不接受参数"),
    "clean": cmd_clean,
    "demo": cmd_demo,
    "pack": cmd_pack,
    "verify": cmd_verify,
    "viz": cmd_viz,
    "aura": cmd_aura,
    "bench": cmd_bench,
    "consolidate": cmd_consolidate,
    "matrix": cmd_matrix,
    "pk": cmd_pk,
    "synthetic": cmd_synthetic,
    "pool": cmd_pool,
    "import": cmd_import,
    "test": cmd_test,
    "help": cmd_help,
}


def parse(argv):
    global DEBUG, FORCE
    DEBUG = False
    FORCE = False
    cmd = None
    args = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            args.extend(argv[i + 1:])
            break
        if token == "--debug":
            DEBUG = True
        elif token == "--force":
            FORCE = True
        elif token in ("-h", "--help") and cmd is None and not args:
            cmd = "help"
        elif cmd is None and token in COMMANDS:
            cmd = token
        else:
            if cmd is None:
                sys.exit(f"未知参数 {token}。可用命令见：python3 build.py --help")
            args.append(token)
        i += 1
    return cmd or "kernel", args


def main(argv):
    os.chdir(ROOT)
    cmd, args = parse(argv)
    DISPATCH[cmd](args)


if __name__ == "__main__":
    main(sys.argv[1:])
