#!/usr/bin/python3
"""Generated extreme scenarios (10,000 by default) for everything we ship:
the bridge (host-run), the settings parser (host-run + host-bridge) and the
Cowork patcher. Runs INSIDE the sandbox; started by tests/fuzz-tests.sh.

Each scenario is built from (seed, index) alone, so any failure can be
replayed exactly:   tests/fuzz-tests.sh --seed S --only INDEX
Every scenario checks the result against what SHOULD happen (an oracle),
not just "it didn't crash".
"""
import argparse
import fnmatch
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import random
import re
import select
import shutil
import signal
import stat
import statistics
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

APP = os.environ["FLATPAK_ID"]
HOME = os.environ["HOME"]
UID = os.getuid()
RUN_DIR = f"{os.environ['XDG_RUNTIME_DIR']}/app/{APP}/host-run"
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLAN = [("roundtrip", 3500), ("exitcode", 1000), ("signal", 400), ("burst", 100),
        ("mcp", 400), ("cache", 300), ("config", 1300), ("patcher", 3000)]

# ── What runs on the other side ─────────────────────────────────────────────
# Reports everything it received, then writes a known blob, noise on stderr,
# and exits with the requested code.
PROBE = r'''
import sys,os,json,hashlib,random
d=sys.stdin.buffer.read()
k=os.environ.get("FZ_KEYS","")
keys=k.split(",") if k else []
box=None
try:
    for l in open("/run/.containerenv"):
        if l.startswith("name="): box=l.split("=",1)[1].strip().strip('"')
except OSError: pass
res={"argv":sys.argv[1:],"cwd":os.getcwd(),"sha":hashlib.sha256(d).hexdigest(),"n":len(d),
     "env":{x:os.environ.get(x) for x in keys},"box":box}
n=int(os.environ.get("FZ_OUT","0"))
sys.stdout.buffer.write(json.dumps(res).encode()+b"\n"+random.Random(os.environ.get("FZ_SEED","0")).randbytes(n))
sys.stdout.flush()
e=int(os.environ.get("FZ_ERR","0"))
if e: sys.stderr.write("noise-"*e); sys.stderr.flush()
sys.exit(int(os.environ.get("FZ_RC","0")))
'''
# A line-based JSON server, like an MCP plugin
SERVER = r'''
import sys,json,hashlib
for line in sys.stdin:
    m=json.loads(line)
    print(json.dumps({"id":m["id"],"sha":hashlib.sha256(m["p"].encode()).hexdigest(),"n":len(m["p"])}),flush=True)
'''
SLEEPER = r'''
import time,sys
print("ready",flush=True)
time.sleep(60)
'''

# ── Rules the bridge promises ───────────────────────────────────────────────
ENV_DROPPED = ["*PATH", "LD_*", "FLATPAK_*", "DBUS_*", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS",
               "XDG_*_HOME", "container", "GIO_*", "GST_*", "GDK_*", "GTK_*", "GSETTINGS_*",
               "PYTHON*", "ZYPAK_*", "CHROME_*", "ELECTRON_*", "SHELL", "SHLVL", "PWD", "OLDPWD",
               "_", "HOST_BIN", "BASH_FUNC_*"]


def env_passes(name, value):
    if any(fnmatch.fnmatchcase(name, p) for p in ENV_DROPPED):
        return False
    return "/run/flatpak/" not in value and not value.startswith("/app/")


def expected_dir(cwd):
    for p in (HOME, HOME + "/*", "/run/user/*", "/media/*", "/mnt/*", "/var/home/*"):
        if fnmatch.fnmatchcase(cwd, p):
            return cwd
    return HOME


SPACE = rb"[ \t\n\r\f\v]"


def settings_oracle(data):
    """Which toolbox a settings.conf means: the LAST line `[export] TOOLBOX=value`
    wins; quotes and whitespace are removed. "" = the host."""
    val = None
    for line in data.split(b"\n"):
        m = re.match(SPACE + rb"*(?:export" + SPACE + rb"+)?TOOLBOX=(.*)", line, re.S)
        if m:
            val = m.group(1)
    if val is None:
        return ""
    return re.sub(rb"[\"' \t\n\r\f\v\x00]", b"", val).decode("utf-8", "surrogateescape")


RULES = [(b"/usr/share/OVMF/", b"/app/share/OVMF/"),
         (b"/usr/libexec/virtiofsd", b"/app/libexec/virtiofsd")]


def asar_header(data):
    json_len = struct.unpack_from("<I", data, 12)[0]
    raw = data[16:16 + json_len]
    json.loads(raw)
    return raw


def patch_oracle(data):
    """The patched archive, or None when the patcher must refuse."""
    try:
        if data is None or len(data) < 16:
            return None
        header = asar_header(data)
        patched = data
        for old, new in RULES:
            if patched.count(old) == 0 or old in header:
                return None
            patched = patched.replace(old, new)
        if len(patched) != len(data) or asar_header(patched) != header:
            return None
        return patched
    except Exception:
        return None


# ── Random building blocks ──────────────────────────────────────────────────
ARG_POOL = ["", " ", "-", "--", "-rf", "--help", "-c", "$HOME", "$(id)", "`id`", "*", "?", "~",
            "'", '"', "\\", "\n", "\t", "a b", "a\nb", "ñ", "日本語", "🎉🚀", "%s%n%x", "{}",
            ";", "|", "&", ">", "<", "!", "#", "=", "a=b", "\x01\x02", "\x7f", "​", "﻿",
            "--toolbox", "--host", "-socket"]
BYTES_POOL = [b"\xff", b"\xfe\xff", b"\x80abc", b"ok\xc3", b"\xed\xa0\x80"]
VAL_POOL = ["", " ", "a=b=c", "line1\nline2", "ñ日本🎉", "$(id)", "`id`", "'\"", "\\",
            "/app/fz", "x/run/flatpak/y", "/apply", "/app", "tab\there", "\r\n", "=", "-"]
DROPPED_NAMES = ["FZ{n}_PATH", "LD_FZ{n}", "FLATPAK_FZ{n}", "DBUS_FZ{n}", "XDG_FZ{n}_HOME",
                 "GTK_FZ{n}", "PYTHONFZ{n}", "ZYPAK_FZ{n}", "CHROME_FZ{n}", "ELECTRON_FZ{n}",
                 "GIO_FZ{n}", "GST_FZ{n}", "GDK_FZ{n}", "GSETTINGS_FZ{n}", "BASH_FUNC_fz{n}%%",
                 "HOST_BIN", "SHELL", "container", "OLDPWD"]
PRINTABLE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !#$%&()*+,-./:;<=>?@[]^_{|}~"


def rstr(rng, lo, hi, alphabet=PRINTABLE):
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(lo, hi)))


def pick_size(rng, table):
    r, acc = rng.random(), 0.0
    for p, lo, hi in table:
        acc += p
        if r < acc:
            return rng.randint(lo, hi)
    return table[-1][2]


STDIN_SIZES = [(0.2, 0, 0), (0.4, 1, 1000), (0.3, 1000, 262144), (0.09, 262144, 4 << 20), (0.01, 4 << 20, 16 << 20)]
OUT_SIZES = [(0.3, 0, 0), (0.4, 1, 1000), (0.25, 1000, 262144), (0.05, 262144, 4 << 20)]


def gen_args(rng):
    args, total = [], 0
    for _ in range(rng.choice([0, 1, 2, 3, 5, 10, 30])):
        r = rng.random()
        if r < 0.75:
            a = rng.choice(ARG_POOL)
        elif r < 0.85:
            a = rng.choice(BYTES_POOL)
        elif r < 0.95:
            a = rstr(rng, 1, 50)
        else:
            a = "x" * rng.randint(1000, 100000)
        total += len(a)
        if total > 600000:
            break
        args.append(a)
    return args


def gen_env(rng):
    env, expect, total = {}, {}, 0
    for n in range(rng.choice([0, 1, 3, 5, 10])):
        r = rng.random()
        if r < 0.7:
            name = "FZ_" + rstr(rng, 1, 10, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
        elif r < 0.9:
            name = rng.choice(DROPPED_NAMES).format(n=rng.randint(0, 999))
        else:
            name = rng.choice(["fz-", "fz.", "9fz"]) + rstr(rng, 1, 6, "abc123")
        r = rng.random()
        if r < 0.6:
            val = rng.choice(VAL_POOL)
        elif r < 0.95:
            val = rstr(rng, 1, 60)
        else:
            val = "v" * rng.randint(1000, 100000)
        if name in env or total + len(val) > 900000:
            continue
        # values must be unique so "not passed" can be told apart from a host default
        if not env_passes(name, val):
            val = val + "~" + str(rng.random())
        total += len(val)
        env[name] = val
        expect[name] = env_passes(name, val)
    return env, expect


# ── Running things through the bridge ───────────────────────────────────────
class Ctx:
    pass


def hr(ctx, mode, cmd, stdin=b"", env=None, cwd=HOME, timeout=120, home=None):
    e = dict(ctx.base_env)
    e.update(env or {})
    e["PWD"] = cwd
    if home:
        e["HOME"] = home
    flags = {"toolbox": ["--toolbox", "dev"], "host": ["--host"], "conf": []}[mode] if isinstance(mode, str) else mode
    return subprocess.run(ctx.hr + flags + cmd, input=stdin, capture_output=True, env=e, cwd=cwd, timeout=timeout)


def check_probe(p, i, mode_box, args, env, expect_env, stdin, out_n, err_n, rc, cwd):
    problems = []
    if p.returncode != rc:
        problems.append(f"exit {p.returncode} != {rc}")
    head, _, blob = p.stdout.partition(b"\n")
    try:
        res = json.loads(head)
    except ValueError:
        return [f"no probe output (exit {p.returncode}); out={p.stdout[:150]!r} err={p.stderr[-300:]!r}"]
    want_args = [a if isinstance(a, str) else os.fsdecode(a) for a in args]
    if res["argv"] != want_args:
        diff = next((k for k, (x, y) in enumerate(zip(res["argv"], want_args)) if x != y), None)
        where = f", arg {diff}: sent {want_args[diff][:40]!r} got {res['argv'][diff][:40]!r}" if diff is not None else ""
        problems.append(f"argv differs: {len(res['argv'])} vs {len(want_args)} args{where}")
    if res["cwd"] != expected_dir(cwd):
        problems.append(f"cwd {res['cwd']!r} != {expected_dir(cwd)!r}")
    if res["n"] != len(stdin) or res["sha"] != hashlib.sha256(stdin).hexdigest():
        problems.append(f"stdin corrupted ({res['n']} of {len(stdin)} bytes)")
    for k, ok in expect_env.items():
        got = res["env"].get(k)
        if ok and got != env[k]:
            problems.append(f"env {k} not passed ({(got or '')[:30]!r})")
        if not ok and got == env[k]:
            problems.append(f"env {k} should have been dropped")
    if res["box"] != mode_box:
        problems.append(f"ran in {res['box']!r}, wanted {mode_box!r}")
    if blob != random.Random(str(i)).randbytes(out_n):
        problems.append(f"stdout corrupted ({len(blob)} of {out_n} bytes)")
    if p.stderr != b"noise-" * err_n:
        problems.append(f"stderr differs: {p.stderr[-200:]!r}")
    return problems


def sc_roundtrip(rng, i, ctx):
    mode = "toolbox" if rng.random() < 0.7 else "host"
    args = gen_args(rng)
    env, expect_env = gen_env(rng)
    stdin = rng.randbytes(pick_size(rng, STDIN_SIZES))
    out_n = pick_size(rng, OUT_SIZES)
    err_n = rng.choice([0, 0, 0, 0, rng.randint(1, 20000)])
    rc = rng.choice([0] * 6 + [rng.randint(1, 255)])
    cwd = rng.choice(ctx.cwds)
    env.update(FZ_KEYS=",".join(expect_env), FZ_OUT=str(out_n), FZ_ERR=str(err_n), FZ_RC=str(rc), FZ_SEED=str(i))
    t = time.monotonic()
    p = hr(ctx, mode, ["python3", "-c", PROBE, *args], stdin, env, cwd)
    ms = (time.monotonic() - t) * 1000
    probs = check_probe(p, i, "dev" if mode == "toolbox" else None, args, env, expect_env, stdin, out_n, err_n, rc, cwd)
    return probs, ms, {"mode": mode, "bytes": len(stdin) + out_n}


def sc_exitcode(rng, i, ctx):
    mode = "toolbox" if rng.random() < 0.6 else "host"
    r = rng.random()
    if r < 0.6:
        rc = rng.randint(0, 255)
        cmd, want = ["python3", "-c", f"import sys; sys.exit({rc})"], rc
    elif r < 0.8:
        cmd, want = [rng.choice([f"fz-missing-{rng.getrandbits(32):x}", f"/nonexistent/{rng.getrandbits(32):x}",
                                 f"./fz-rel-{rng.getrandbits(32):x}", ""])], 127
    elif r < 0.9:
        cmd, want = [ctx.noexec], 126
    else:
        cmd, want = [ctx.tmp], 126
    t = time.monotonic()
    p = hr(ctx, mode, cmd, cwd=HOME, timeout=60)
    ms = (time.monotonic() - t) * 1000
    probs = [] if p.returncode == want else [f"{mode}: {cmd[0][:40]!r} exit {p.returncode}, want {want} ({p.stderr[-150:]!r})"]
    return probs, ms, {"mode": mode}


def leftover(ctx, marker):
    """Is a process with this marker still alive anywhere on the host?"""
    pat = marker[:-1] + "[" + marker[-1] + "]"          # does not match itself
    for _ in range(10):
        p = hr(ctx, "host", ["pgrep", "-f", pat], timeout=30)
        if p.returncode == 1:
            return False
        time.sleep(0.5)
    return True


def read_line(fd, buf, timeout):
    end = time.monotonic() + timeout
    while b"\n" not in buf:
        left = end - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            return None, buf
        chunk = os.read(fd, 65536)
        if not chunk:
            return None, buf
        buf += chunk
    line, _, rest = buf.partition(b"\n")
    return line, rest


def sc_signal(rng, i, ctx):
    mode = "toolbox" if rng.random() < 0.6 else "host"
    sig = rng.choice([signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
    early = rng.random() < 0.2
    marker = f"FZMARK-{ctx.seed}-{i}"
    e = dict(ctx.base_env, PWD=HOME)
    flags = ["--toolbox", "dev"] if mode == "toolbox" else ["--host"]
    t = time.monotonic()
    p = subprocess.Popen(ctx.hr + flags + ["python3", "-c", SLEEPER, marker], stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=e, cwd=HOME)
    probs = []
    if early:
        time.sleep(rng.uniform(0, 0.05))
    else:
        line, _ = read_line(p.stdout.fileno(), b"", 30)
        if line != b"ready":
            probs.append("sleeper never became ready")
        time.sleep(rng.uniform(0, 0.3))
    p.send_signal(sig)
    try:
        rc = p.wait(timeout=30)
        ok_rc = (128 + sig, -sig)
        if ctx.fallback and sig == signal.SIGINT:   # documented: Ctrl-C arrives as SIGTERM there
            ok_rc += (143, -15)
        if not early and rc not in ok_rc:
            probs.append(f"{mode} {sig.name}: exit {rc}, want {128 + sig}")
    except subprocess.TimeoutExpired:
        p.kill()
        probs.append(f"{mode} {sig.name}: did not stop within 30 s")
    p.stdout.close()
    ms = (time.monotonic() - t) * 1000
    if leftover(ctx, marker):
        probs.append(f"{mode} {sig.name}{' (early)' if early else ''}: process left running on the host")
        hr(ctx, "host", ["pkill", "-f", marker[:-1] + "[" + marker[-1] + "]"], timeout=30)
    if early and probs:
        # flatpak-spawn itself sometimes loses a signal sent while the portal is
        # still starting the command (reproduced without host-run): not ours
        return [], ms, {"mode": mode, "known": "early signal lost by flatpak-spawn (upstream race)"}
    return probs, ms, {"mode": mode}


def sc_burst(rng, i, ctx):
    k = rng.randint(5, 80)
    t = time.monotonic()
    procs = []
    for j in range(k):
        mode = "toolbox" if rng.random() < 0.7 else "host"
        stdin = rng.randbytes(rng.randint(0, 5000))
        rc = rng.choice([0, 0, 0, rng.randint(1, 255)])
        out_n = rng.randint(0, 3000)
        env = dict(ctx.base_env, PWD=HOME, FZ_OUT=str(out_n), FZ_RC=str(rc), FZ_SEED=f"{i}.{j}", FZ_KEYS="")
        flags = ["--toolbox", "dev"] if mode == "toolbox" else ["--host"]
        p = subprocess.Popen(ctx.hr + flags + ["python3", "-c", PROBE], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=HOME)
        procs.append((p, mode, stdin, rc, out_n, j))
    results = [None] * k
    threads = []
    for idx, (p, mode, stdin, rc, out_n, j) in enumerate(procs):
        def talk(idx=idx, p=p, stdin=stdin):
            try:
                results[idx] = p.communicate(stdin, timeout=180)
            except subprocess.TimeoutExpired:
                p.kill()
                results[idx] = (b"", b"timeout")
        th = threading.Thread(target=talk)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    ms = (time.monotonic() - t) * 1000
    probs = []
    for (p, mode, stdin, rc, out_n, j), (out, err) in zip(procs, results):
        cp = subprocess.CompletedProcess(p.args, p.returncode, out, err)
        pr = check_probe(cp, f"{i}.{j}", "dev" if mode == "toolbox" else None, [], {}, {}, stdin, out_n, 0, rc, HOME)
        if pr:
            probs.append(f"#{j}/{k} {mode}: " + "; ".join(pr))
    return probs[:3] + ([f"... {len(probs) - 3} more"] if len(probs) > 3 else []), ms, {"n": k}


def sc_mcp(rng, i, ctx):
    mode = "toolbox" if rng.random() < 0.6 else "host"
    n = rng.choice([1, 5, 20, 50, 200])
    pipelined = rng.random() < 0.3
    e = dict(ctx.base_env, PWD=HOME)
    flags = ["--toolbox", "dev"] if mode == "toolbox" else ["--host"]
    alphabet = PRINTABLE + "\n\t\"\\ñ日本🎉'"
    msgs = [{"jsonrpc": "2.0", "id": k, "p": rstr(rng, 0, rng.choice([10, 200, 5000, 65536]), alphabet)} for k in range(n)]
    t = time.monotonic()
    p = subprocess.Popen(ctx.hr + flags + ["python3", "-u", "-c", SERVER], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=e, cwd=HOME, bufsize=0)
    fd, buf, probs, rtts = p.stdout.fileno(), b"", [], []

    def check(m, line):
        if line is None:
            return "no answer within 60 s"
        r = json.loads(line)
        if r["id"] != m["id"] or r["sha"] != hashlib.sha256(m["p"].encode()).hexdigest():
            return f"wrong answer for message {m['id']}"
        return None

    try:
        if pipelined:
            writer = threading.Thread(target=lambda: [p.stdin.write((json.dumps(m) + "\n").encode()) for m in msgs])
            writer.start()
            for m in msgs:
                line, buf = read_line(fd, buf, 60)
                err = check(m, line)
                if err:
                    probs.append(err)
                    break
            writer.join()
        else:
            for m in msgs:
                s = time.monotonic()
                p.stdin.write((json.dumps(m) + "\n").encode())
                line, buf = read_line(fd, buf, 60)
                rtts.append((time.monotonic() - s) * 1000)
                err = check(m, line)
                if err:
                    probs.append(err)
                    break
        p.stdin.close()
        rc = p.wait(timeout=30)
        if rc != 0:
            probs.append(f"server exit {rc} after stdin closed")
    except (BrokenPipeError, subprocess.TimeoutExpired, ValueError) as ex:
        p.kill()
        probs.append(f"{type(ex).__name__}: {ex}")
    ms = (time.monotonic() - t) * 1000
    return [f"{mode}: {x}" for x in probs], ms, {"rtt": rtts, "mode": mode}


def remove(path):
    """Remove a file, link or folder, even while other commands write into it."""
    for _ in range(50):
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.unlink(path)
            return
        except OSError:
            time.sleep(0.05)


def unblock(path):
    """Release anything stuck opening a FIFO for reading (open + close a writer)."""
    for _ in range(20):
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            return
        time.sleep(0.05)


def sc_cache(rng, i, ctx):
    cache = f"{RUN_DIR}/dev.nspid"
    variant = rng.choice(["empty", "garbage", "one-one", "huge", "negative", "binary", "wrong-start",
                          "wrong-pid", "long", "newlines", "directory", "unreadable", "symlink",
                          "fifo", "missing"])
    with ctx.cache_lock:
        good = ctx.good_cache
        remove(cache)
        pid, start = good.split()
        content = {"empty": b"", "garbage": b"hello world", "one-one": b"1 1", "huge": b"99999999999999 1",
                   "negative": b"-1 -1", "binary": rng.randbytes(rng.randint(1, 100)),
                   "wrong-start": f"{pid} {int(start) + 1}".encode(),
                   "wrong-pid": f"{os.getpid()} {start}".encode(), "long": b"7" * 10000,
                   "newlines": b"\n\n\n"}.get(variant)
        if content is not None:
            with open(cache, "wb") as f:
                f.write(content)
        elif variant == "directory":
            os.mkdir(cache)
        elif variant == "unreadable":
            with open(cache, "w") as f:
                f.write("1 1")
            os.chmod(cache, 0)
        elif variant == "symlink":
            os.symlink("/etc/passwd", cache)
        elif variant == "fifo":
            os.mkfifo(cache)
        t = time.monotonic()
        probs = []
        try:
            p = hr(ctx, "toolbox", ["python3", "-c", PROBE], env={"FZ_SEED": str(i)}, timeout=30)
            probs = check_probe(p, i, "dev", [], {}, {}, b"", 0, 0, 0, HOME)
        except subprocess.TimeoutExpired:
            probs = ["hung (30 s) on a broken cache file"]
            unblock(cache)
        ms = (time.monotonic() - t) * 1000
        # afterwards the cache should be a valid "pid start" file again
        # (the fallback path does not use the cache at all)
        if ctx.fallback:
            pass
        elif os.path.isfile(cache) and not os.path.islink(cache):
            try:
                with open(cache) as f:
                    if f.read().split() != [pid, start] and not probs:
                        probs.append("cache not repaired")
            except OSError:
                probs.append("cache left unreadable")
        elif not probs:
            probs.append(f"cache left as a {variant}")
        # restore a good cache for the rest of the run
        remove(cache)
        with open(cache, "w") as f:
            f.write(good + "\n")
    return [f"{variant}: {x}" for x in probs], ms, {}


BOX_CANDIDATES = [b"dev", b"", b"nosuchbox", b"-l", b"--latest", b"DEV", "dév".encode(), b"../dev",
                  b"dev;id", b"$(id)", b"x" * 300, b"--help", b"-", b"dev dev"]


def sc_config(rng, i, ctx):
    home = f"{ctx.tmp}/home-{i}"
    conf_dir = f"{home}/.config/claude-desktop-flatpak"
    conf = f"{conf_dir}/settings.conf"
    os.makedirs(conf_dir)
    boxes = BOX_CANDIDATES + [b.encode() for b in ctx.boxes if b != "dev"]
    special = rng.random()
    data = b""
    if special < 0.03:
        kind = "missing"
    elif special < 0.05:
        kind = "directory"
        os.mkdir(conf)
    elif special < 0.07:
        kind = "fifo"
        os.mkfifo(conf)
    elif special < 0.09:
        kind = "unreadable"
    else:
        kind = "file"
    if kind in ("file", "unreadable"):
        lines = []
        for _ in range(rng.randint(0, 10)):
            lines.append(rng.choice([rstr(rng, 0, 80).encode(), b"COWORK=off", b"#TOOLBOX=dev", b"TOOLBOXX=dev",
                                     b"toolbox=dev", b"COWORK_LOCAL=on", rng.randbytes(rng.randint(1, 40)).replace(b"\n", b""),
                                     "ünïcödé=✓".encode(), b"y" * 100000, b""]))
        for _ in range(rng.choice([0, 1, 1, 1, 2, 3])):
            pre = rng.choice([b"", b" ", b"\t", b"  \t", b"export ", b" export  ", b"export\t", b"#", b"# ", b"X"])
            q1, q2 = rng.choice([(b"", b""), (b"'", b"'"), (b'"', b'"'), (b'"', b""), (b"", b"'")])
            suf = rng.choice([b"", b" ", b"\t", b"\r", b" \r", b"  # comment"])
            lines.insert(rng.randint(0, len(lines)), pre + b"TOOLBOX=" + q1 + rng.choice(boxes) + q2 + suf)
        nl = b"\r\n" if rng.random() < 0.1 else b"\n"
        data = nl.join(lines) + (nl if rng.random() < 0.8 else b"")
        with open(conf, "wb") as f:
            f.write(data)
        if kind == "unreadable":
            os.chmod(conf, 0)
    parsed = settings_oracle(data) if kind == "file" else ""
    flag = rng.random()
    if flag < 0.1:
        mode, target = ["--host"], ""
    elif flag < 0.2:
        b = rng.choice(boxes).decode("utf-8", "surrogateescape")
        mode, target = ["--toolbox", b], b
    else:
        mode, target = "conf", parsed
    probs = []
    # 1. host-bridge must read the same toolbox as host-run
    with ctx.bridge_lock:
        ctx.bridge.CONF = conf
        box = {}

        def read():
            try:
                box["got"] = ctx.bridge.toolbox()
            except Exception as ex:
                box["err"] = f"{type(ex).__name__}: {ex}"
        th = threading.Thread(target=read, daemon=True)
        th.start()
        th.join(10)
        if th.is_alive():
            probs.append("host-bridge hung reading settings.conf")
            unblock(conf)
            th.join(5)
        elif "err" in box:
            probs.append(f"host-bridge crashed: {box['err']}")
        elif box["got"] != parsed:
            probs.append(f"host-bridge reads {box['got']!r}, should be {parsed!r}")
    # 2. host-run must run there (or refuse cleanly)
    t = time.monotonic()
    try:
        p = hr(ctx, mode, ["python3", "-c", PROBE], env={"FZ_SEED": str(i)}, timeout=60, home=home)
        if target == "" or target in ctx.boxes:
            probs += check_probe(p, i, target or None, [], {}, {}, b"", 0, 0, 0, HOME)
        elif p.returncode == 0:
            probs.append(f"ran although toolbox {target[:40]!r} does not exist")
    except subprocess.TimeoutExpired:
        probs.append("host-run hung (60 s)")
        unblock(conf)
    ms = (time.monotonic() - t) * 1000
    if kind == "unreadable":
        os.chmod(conf, 0o600)
    shutil.rmtree(home, ignore_errors=True)
    return [f"{kind} target={target[:30]!r}: {x}" for x in probs], ms, {}


def sc_patcher(rng, i, ctx):
    d = f"{ctx.tmp}/patch-{i}"
    os.makedirs(d)
    src, dst = f"{d}/app.asar", f"{d}/out/patched.asar" if False else f"{d}/patched.asar"
    if i == ctx.first_patch:                         # the real thing
        shutil.copy(ctx.real_asar, src)
        kind = "real app.asar"
    else:
        kind = rng.choices(["normal", "in-header", "truncated", "tiny", "empty", "bad-len", "bad-json",
                            "overlap", "missing-src", "no-dst-dir", "boundary", "no-rules"],
                           [50, 10, 8, 4, 3, 5, 5, 5, 3, 3, 4, 3])[0]
        files = {"files": {rstr(rng, 1, 12, "abcdef.-_"): {"size": rng.randint(0, 999), "offset": str(rng.randint(0, 10 ** 6))}
                           for _ in range(rng.randint(0, 20))}}
        if kind == "in-header":
            files["files"][rng.choice(RULES)[0].decode()] = {"size": 1}
        hj = json.dumps(files).encode()
        body = bytearray(rng.randbytes(rng.choice([0, rng.randint(1, 1000), rng.randint(1000, 200000)])))
        for old, _ in RULES:
            for _ in range(0 if kind == "no-rules" else rng.choice([0, 1, 1, 2, 3, 5])):
                pos = rng.randint(0, len(body))
                body[pos:pos] = old
        if kind == "overlap":
            body += b"/usr/share/OVMF//usr/libexec/virtiofsd"
        data = struct.pack("<IIII", 4, len(hj) + 8, len(hj) + 4, len(hj)) + hj
        if kind == "boundary":
            data = data[:-3] + RULES[0][0][:3]                   # rule string starts inside the header
            data += RULES[0][0][3:]
        data += bytes(body)
        if kind == "truncated":
            data = data[:rng.randint(0, len(data))]
        elif kind == "tiny":
            data = data[:rng.randint(0, 15)]
        elif kind == "empty":
            data = b""
        elif kind == "bad-len":
            data = data[:12] + struct.pack("<I", rng.choice([0, 2 ** 32 - 1, len(data) * 2])) + data[16:]
        elif kind == "bad-json" and len(hj) > 2:
            pos = 16 + rng.randint(0, len(hj) - 1)
            data = data[:pos] + bytes([rng.choice(b"{}[]\x00\xff,:")]) + data[pos + 1:]
        if kind != "missing-src":
            with open(src, "wb") as f:
                f.write(data)
        if kind == "no-dst-dir":
            dst = f"{d}/no/such/dir/patched.asar"
    src_data = open(src, "rb").read() if os.path.exists(src) else None
    want = patch_oracle(src_data)
    if kind == "no-dst-dir":
        want = None
    t = time.monotonic()
    p = subprocess.run(ctx.patcher + [src, dst], capture_output=True, timeout=120)
    ms = (time.monotonic() - t) * 1000
    probs = []
    out = p.stdout.decode(errors="replace")
    if b"Traceback" in p.stderr:
        probs.append("crashed with a traceback")
    if want is not None:
        if p.returncode != 0 or not out.rstrip().endswith("enabled"):
            probs.append(f"should patch, got exit {p.returncode}: {out.strip()[-120:]!r}")
        elif open(dst, "rb").read() != want:
            probs.append("patched file differs from the expected bytes")
    else:
        if p.returncode != 1 or "disabled:" not in out:
            probs.append(f"should refuse cleanly, got exit {p.returncode}: {out.strip()[-120:]!r}")
        if os.path.exists(dst):
            probs.append("left a (partial) output file although it refused")
    if src_data is not None and open(src, "rb").read() != src_data:
        probs.append("MODIFIED THE ORIGINAL")
    if kind == "real app.asar" and not probs and open(dst, "rb").read() != open(ctx.real_patched, "rb").read():
        probs.append("differs from the installed patched app.asar")
    shutil.rmtree(d, ignore_errors=True)
    return [f"{kind}: {x}" for x in probs], ms, {}


SCENARIOS = {"roundtrip": sc_roundtrip, "exitcode": sc_exitcode, "signal": sc_signal, "burst": sc_burst,
             "mcp": sc_mcp, "cache": sc_cache, "config": sc_config, "patcher": sc_patcher}


def category_of(i, plan):
    for name, n in plan:
        if i < n:
            return name
        i -= n
    raise IndexError


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260928)
    ap.add_argument("--count", type=int, default=10000)
    ap.add_argument("--only", type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--project", action="store_true", help="test the scripts in this folder, not the installed ones")
    ap.add_argument("--fallback", action="store_true", help="force the slower `toolbox run` path (no nsenter)")
    a = ap.parse_args()

    scale = a.count / sum(n for _, n in PLAN)
    plan = [(c, max(1, round(n * scale))) for c, n in PLAN]
    total = sum(n for _, n in plan)

    ctx = Ctx()
    ctx.seed = a.seed
    ctx.base_env = {k: v for k, v in os.environ.items()}
    src = f"{PROJECT}/scripts" if a.project else "/app/bin"
    ctx.hr = ["/bin/bash", f"{src}/host-run"]
    ctx.fallback = a.fallback
    if a.fallback:
        os.makedirs(f"{HOME}/.var/app/{APP}/cache", exist_ok=True)
        os.makedirs(f"{HOME}/.var/app/{APP}/cache/fallback", exist_ok=True)
        forced = f"{HOME}/.var/app/{APP}/cache/fallback/host-run"   # host-run acts on its own name
        text = open(f"{src}/host-run").read()
        assert "ns=$(command -v nsenter)" in text
        with open(forced, "w") as f:
            f.write(text.replace("ns=$(command -v nsenter)", "ns="))
        ctx.hr = ["/bin/bash", forced]
    ctx.patcher = [sys.executable, f"{src}/cowork-patch"]
    loader = importlib.machinery.SourceFileLoader("host_bridge", f"{src}/host-bridge")
    spec = importlib.util.spec_from_loader("host_bridge", loader)
    ctx.bridge = importlib.util.module_from_spec(spec)
    loader.exec_module(ctx.bridge)
    ctx.bridge_lock, ctx.cache_lock = threading.Lock(), threading.Lock()
    ctx.real_asar = "/app/extra/claude-desktop-orig/resources/app.asar"
    ctx.real_patched = "/app/extra/claude-desktop/resources/app.asar"
    ctx.first_patch = sum(n for c, n in plan if c != "patcher") if a.only is None else -1
    if a.only is not None and category_of(a.only, plan) == "patcher" and a.only == sum(n for c, n in plan if c != "patcher"):
        ctx.first_patch = a.only
    cache_root = f"{HOME}/.var/app/{APP}/cache"
    for old in os.listdir(cache_root):              # leftovers of an interrupted run
        path = f"{cache_root}/{old}"
        if old.startswith("fuzz-run-") and time.time() - os.path.getmtime(path) > 3600:
            shutil.rmtree(path, ignore_errors=True)
    ctx.tmp = f"{cache_root}/fuzz-run-{a.seed}-{time.time_ns()}"
    os.makedirs(ctx.tmp)
    ctx.noexec = f"{ctx.tmp}/not-executable.txt"
    open(ctx.noexec, "w").write("hello\n")
    deep = ctx.tmp + "".join(f"/deep{n}" for n in range(40))
    for d in (f"{ctx.tmp}/dir with spaces ñ 日本 🎉", f"{ctx.tmp}/new\nline", deep):
        os.makedirs(d, exist_ok=True)
    ctx.cwds = [HOME, PROJECT, f"{ctx.tmp}/dir with spaces ñ 日本 🎉", f"{ctx.tmp}/new\nline", deep,
                "/tmp", "/app", f"/run/user/{UID}"]

    print(f"Fuzz: seed={a.seed} scenarios={total} workers={a.workers} "
          f"testing={'project scripts' if a.project else 'installed app'}{' (fallback path)' if a.fallback else ''}", flush=True)
    # Which toolboxes are running right now (we never start or stop yours)
    p = hr(ctx, "host", ["podman", "ps", "--filter", "label=com.github.containers.toolbox=true",
                         "--format", "{{.Names}}"], timeout=60)
    ctx.boxes = set(p.stdout.decode().split())
    if "dev" not in ctx.boxes:
        print("The 'dev' toolbox must be running (open it once).")
        return 2
    hr(ctx, "toolbox", ["true"], timeout=60)
    ctx.good_cache = open(f"{RUN_DIR}/dev.nspid").read().strip()
    jobs_before = set(f for f in os.listdir(RUN_DIR) if f.startswith("job."))
    fds_before = len(os.listdir("/proc/self/fd"))

    # Baseline: the same probe without the bridge
    base = []
    for _ in range(20):
        t = time.monotonic()
        subprocess.run([sys.executable, "-c", PROBE], input=b"", capture_output=True, env=dict(ctx.base_env, FZ_SEED="0"))
        base.append((time.monotonic() - t) * 1000)

    indices = [a.only] if a.only is not None else list(range(total))
    results = {}
    done = [0]
    lock = threading.Lock()
    start = time.monotonic()

    def run(i):
        cat = category_of(i, plan)
        rng = random.Random(f"{a.seed}-{i}")
        try:
            probs, ms, extra = SCENARIOS[cat](rng, i, ctx)
        except Exception as ex:
            probs, ms, extra = [f"harness error: {type(ex).__name__}: {ex}"], 0, {}
        with lock:
            results[i] = (cat, probs, ms, extra)
            done[0] += 1
            if done[0] % 250 == 0 or done[0] == len(indices):
                fails = sum(1 for r in results.values() if r[1])
                print(f"  {done[0]:>6}/{len(indices)}  failed so far: {fails}  ({time.monotonic() - start:.0f}s)", flush=True)

    cache_idx = [i for i in indices if category_of(i, plan) == "cache"]
    other_idx = [i for i in indices if category_of(i, plan) != "cache"]
    # interleave so heavy categories overlap (more extreme), cache tests on their own thread
    random.Random(a.seed).shuffle(other_idx)
    with ThreadPoolExecutor(a.workers) as pool, ThreadPoolExecutor(1) as serial:
        futs = [serial.submit(run, i) for i in cache_idx] + [pool.submit(run, i) for i in other_idx]
        for f in futs:
            f.result()
    wall = time.monotonic() - start

    # ── Leak checks ──
    time.sleep(2)
    leaks = []
    jobs = set(f for f in os.listdir(RUN_DIR) if f.startswith("job.")) - jobs_before
    if jobs:
        leaks.append(f"{len(jobs)} job files left in {RUN_DIR}")
    tmpcache = [f for f in os.listdir(RUN_DIR) if f.startswith("dev.nspid.")]
    if tmpcache:
        leaks.append(f"{len(tmpcache)} temporary cache files left")
    p = hr(ctx, "host", ["pgrep", "-fc", "FZMAR[K]"], timeout=30)
    if p.stdout.strip() not in (b"", b"0"):
        leaks.append(f"{p.stdout.decode().strip()} test processes still running on the host")
    kids = [pid for pid in os.listdir("/proc") if pid.isdigit() and
            open(f"/proc/{pid}/stat").read().split(")")[-1].split()[1] == str(os.getpid())]
    if kids:
        leaks.append(f"{len(kids)} child processes not reaped")
    fds_after = len(os.listdir("/proc/self/fd"))
    if fds_after > fds_before + 2:
        leaks.append(f"file descriptors leaked: {fds_before} -> {fds_after}")
    shutil.rmtree(ctx.tmp, ignore_errors=True)

    # ── Report ──
    print(f"\n{'category':<11}{'runs':>7}{'pass':>7}{'fail':>6}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}")
    for cat, _ in plan:
        rs = [r for r in results.values() if r[0] == cat]
        if not rs:
            continue
        ms = [r[2] for r in rs]
        f = sum(1 for r in rs if r[1])
        print(f"{cat:<11}{len(rs):>7}{len(rs) - f:>7}{f:>6}{pct(ms, .5):>9.0f}{pct(ms, .95):>9.0f}{pct(ms, .99):>9.0f}{max(ms):>9.0f}")
    rt = [r for r in results.values() if r[0] == "roundtrip" and not r[1]]
    for mode in ("toolbox", "host"):
        small = [r[2] for r in rt if r[3]["mode"] == mode and r[3]["bytes"] < 10000]
        if small:
            print(f"\nlatency, small {mode} command: p50 {pct(small, .5):.0f} ms, p99 {pct(small, .99):.0f} ms "
                  f"(same probe without the bridge: {statistics.median(base):.0f} ms)")
    big = [(r[3]["bytes"], r[2]) for r in rt if r[3]["bytes"] > 2 << 20]
    if big:
        print(f"throughput, >2 MB transfers: {statistics.median(b / (m / 1000) for b, m in big) / 2**20:.0f} MB/s (median)")
    rtts = [x for r in results.values() if r[0] == "mcp" for x in r[3].get("rtt", [])]
    if rtts:
        print(f"MCP message round trip: p50 {pct(rtts, .5):.2f} ms, p99 {pct(rtts, .99):.2f} ms ({len(rtts)} messages)")
    bursts = [(r[3]["n"], r[2]) for r in results.values() if r[0] == "burst" and "n" in r[3]]
    if bursts:
        print(f"bursts: {sum(n for n, _ in bursts)} commands in {len(bursts)} bursts, "
              f"{statistics.median(n / (m / 1000) for n, m in bursts):.0f} commands/s (median)")
    known = [r[3]["known"] for r in results.values() if r[3].get("known")]
    if known:
        print(f"known upstream issue (not counted as failures): {len(known)}x {known[0]}")
    print(f"wall time {wall:.0f}s")
    print("\nleak checks: " + ("none found" if not leaks else "; ".join(leaks)))

    failed = sorted((i, r) for i, r in results.items() if r[1])
    if failed:
        print(f"\nFAILURES ({len(failed)}), replay with --seed {a.seed} --only N:")
        groups = {}
        for i, r in failed:
            key = (r[0], re.sub(r"\d+", "#", r[1][0])[:90])
            groups.setdefault(key, []).append(i)
        for (cat, msg), ids in sorted(groups.items(), key=lambda x: -len(x[1])):
            print(f"  {len(ids):>5}x {cat}: {msg}   e.g. N={ids[0]}")
            ex = results[ids[0]][1]
            for line in ex[:3]:
                print(f"         {line[:220]}")
    report = f"{HOME}/.var/app/{APP}/cache/fuzz-report-{a.seed}.json"
    with open(report, "w") as f:
        json.dump({str(i): {"category": r[0], "problems": r[1], "ms": r[2]} for i, r in results.items()}, f)
    print(f"\nResult: {total - len(failed) if a.only is None else 1 - len(failed)} passed, "
          f"{len(failed)} failed, {len(leaks)} leak problems   (full report: {report})")
    return 1 if failed or leaks else 0


if __name__ == "__main__":
    sys.exit(main())
