"""Ask/tell bridge to Aura (std/moead) for the slotting front-end (#4947 B3).

Aura owns the MOEA/D state; Python owns the evaluation, because only Python can
score a slotting assignment.  The host is slotting/moead_host.aura, a tiny line
service:

    MAKE <n-obj> <H> <T> <dim> <seed> <lo0> <hi0> ...  -> OK <n-weights>
    ASK <k>                                            -> CANDS <n> + n lines
    TELL <n> + n objective lines                       -> OK
    BYE                                                -> BYE

This replaces the hand-rolled lambda sweep of the first round: the trade-off
between travel distance and aisle-load variance is now searched by MOEA/D and
the resulting configuration is a real portfolio member.
"""
import os
import shutil
import subprocess

HOST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moead_host.aura")


class AuraUnavailable(RuntimeError):
    pass


def _lib_of(binary):
    """<root>/lib next to a build binary, if it carries std/moead."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(binary)))
    lib = os.path.join(root, "lib")
    return lib if os.path.exists(os.path.join(lib, "std", "moead.aura")) else None


def find_aura():
    """Aura binary + its stdlib dir.

    Order: AURA_BIN, AURA_PATH (../build/aura), PATH.  A candidate is only
    accepted when std/moead.aura exists in its sibling lib/ (or in AURA_PATH),
    because an older installed aura will otherwise fail at require time with a
    confusing module error.
    """
    cands = []
    for key in ("AURA_BIN", "AURA_BIN_PATH"):
        v = os.environ.get(key)
        if v and os.path.exists(v):
            cands.append(v)
    lib_env = os.environ.get("AURA_PATH")
    if lib_env:
        root = os.path.dirname(os.path.abspath(lib_env.rstrip("/")))
        for cand in (os.path.join(root, "build", "aura"),
                     os.path.join(root, "build", "aura.exe")):
            if os.path.exists(cand):
                cands.append(cand)
    w = shutil.which("aura")
    if w:
        cands.append(w)
    for cand in cands:
        lib = _lib_of(cand) or (lib_env if lib_env and os.path.exists(
            os.path.join(lib_env, "std", "moead.aura")) else None)
        if lib:
            return cand, lib
    raise AuraUnavailable("no aura with std/moead found: set "
                          "AURA_BIN=/path/to/aura (or AURA_PATH=/path/to/aura/lib)")


class MoeadHost:
    """One live Aura process holding one MOEA/D state."""

    def __init__(self, aura=None, timeout=120):
        if aura:
            self.bin, self.lib = aura, (_lib_of(aura) or os.environ.get("AURA_PATH"))
        else:
            self.bin, self.lib = find_aura()
        env = dict(os.environ)
        env.setdefault("AURA_SANDBOX", "off")
        if self.lib:
            env["AURA_PATH"] = self.lib
        self.p = subprocess.Popen([self.bin, "--grant", "mutate", HOST],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1,
                                  env=env)
        self.timeout = timeout
        self.dim = 0

    # ---- plumbing ------------------------------------------------------
    def _send(self, line):
        if self.p.poll() is not None:
            raise AuraUnavailable("aura host exited early")
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def _read(self):
        line = self.p.stdout.readline()
        if not line:
            raise AuraUnavailable("aura host closed its stdout")
        line = line.strip()
        if line.startswith("error:") or "error:" in line[:8]:
            raise AuraUnavailable("aura host error: %s" % line)
        return line

    def _expect(self, prefix):
        """Skip Aura banner lines until the expected reply shows up."""
        for _ in range(8):
            line = self._read()
            if line.startswith(prefix):
                return line
        raise AuraUnavailable("expected %r from aura host" % prefix)

    # ---- protocol ------------------------------------------------------
    def make(self, n_obj, h, t, dim, seed, bounds):
        parts = ["MAKE", str(n_obj), str(h), str(t), str(dim), str(seed)]
        for lo, hi in bounds:
            parts += [repr(float(lo)), repr(float(hi))]
        self._send(" ".join(parts))
        reply = self._expect("OK ")
        self.dim = dim
        return int(reply.split()[1])

    def ask(self, k):
        self._send("ASK %d" % k)
        head = self._expect("CANDS ")
        n = int(head.split()[1])
        out = []
        for _ in range(n):
            parts = self._read().split()
            out.append(dict(slot=int(float(parts[0])), gen=int(float(parts[1])),
                            sub=int(float(parts[2])),
                            genome=[float(x) for x in parts[3:3 + self.dim]]))
        return out

    def tell(self, objs):
        self._send("TELL %d" % len(objs))
        for row in objs:
            self._send(" ".join(repr(float(x)) for x in row))
        self._expect("OK")
        return True

    def close(self):
        try:
            if self.p.poll() is None:
                self._send("BYE")
                self.p.wait(timeout=10)
        except Exception:
            pass
        finally:
            if self.p.poll() is None:
                self.p.kill()
            for f in (self.p.stdin, self.p.stdout):
                try:
                    f.close()
                except Exception:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
