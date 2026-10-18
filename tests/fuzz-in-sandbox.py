#!/usr/bin/python3
import argparse
import fnmatch
import hashlib
import json
import os
import random
import re
import select
import shutil
import signal
import stat
import statistics
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

PLAN = [("roundtrip", 6000), ("exitcode", 1700), ("signal", 700), ("burst", 200),
        ("mcp", 800), ("cache", 600)]

PROBE = r'''
import sys,os,json,hashlib,random
d=sys.stdin.buffer.read()
k=os.environ.get("FZ_KEYS","")
keys=k.split(",") if k else []
res={"argv":sys.argv[1:],"cwd":os.getcwd(),"sha":hashlib.sha256(d).hexdigest(),"n":len(d),
     "env":{x:os.environ.get(x) for x in keys}}
n=int(os.environ.get("FZ_OUT","0"))
sys.stdout.buffer.write(json.dumps(res).encode()+b"\n"+random.Random(os.environ.get("FZ_SEED","0")).randbytes(n))
sys.stdout.flush()
e=int(os.environ.get("FZ_ERR","0"))
if e: sys.stderr.write("noise-"*e); sys.stderr.flush()
sys.exit(int(os.environ.get("FZ_RC","0")))
'''
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

ENV_DROPPED = ["PATH", "LD_*", "FLATPAK_*", "DBUS_*", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS",
               "XDG_*_HOME", "container", "GIO_*", "GST_*", "GDK_*", "GTK_*", "GSETTINGS_*",
               "ZYPAK_*", "CHROME_*", "ELECTRON_*", "SHELL", "SHLVL", "PWD", "OLDPWD",
               "_", "HOST_BIN", "BASH_FUNC_*"]
ENV_IF_SANDBOX = ["*PATH", "PYTHON*", "ALSA_*", "__EGL_*"]

FP = f"/run/flatpak/app/{APP}"
OUT = f"{os.environ['XDG_RUNTIME_DIR']}/app/{APP}"

def rewrite(s):
    return s.replace(FP, OUT)

def sandbox_env():
    try:
        with open(f"{OUT}/sandbox.env", "rb") as f:
            pairs = [kv.partition(b"=") for kv in f.read().split(b"\0") if kv]
    except OSError:
        return {}
    base = {os.fsdecode(k): os.fsdecode(v) for k, _, v in pairs
            if re.fullmatch(rb"[A-Za-z_][A-Za-z0-9_]*", k)}
    return base if base.get("FLATPAK_ID") == APP else {}

def env_passes(name, value):
    value = rewrite(value)
    if any(fnmatch.fnmatchcase(name, p) for p in ENV_DROPPED):
        return False
    if any(fnmatch.fnmatchcase(name, p) for p in ENV_IF_SANDBOX):
        base = sandbox_env()
        if not base or base.get(name) == value:
            return False
    return "/run/flatpak/" not in value and not value.startswith("/app/")

SANDBOX_ONLY = ["/", "/app", "/app/*", "/usr", "/usr/*", "/etc", "/etc/*", "/tmp", "/tmp/*",
                "/var/tmp", "/var/tmp/*", "/var/config", "/var/config/*", "/var/data", "/var/data/*",
                "/var/cache", "/var/cache/*", "/var/lib", "/var/lib/*", "/run", "/run/*",
                "/proc", "/proc/*", "/sys", "/sys/*", "/dev", "/dev/*"]

def expected_dir(cwd):
    if fnmatch.fnmatchcase(cwd, "/run/user/*") or fnmatch.fnmatchcase(cwd, "/run/media/*"):
        return cwd
    return HOME if any(fnmatch.fnmatchcase(cwd, p) for p in SANDBOX_ONLY) else cwd

ARG_POOL = ["", " ", "-", "--", "-rf", "--help", "-c", "$HOME", "$(id)", "`id`", "*", "?", "~",
            "'", '"', "\\", "\n", "\t", "a b", "a\nb", "ñ", "日本語", "🎉🚀", "%s%n%x", "{}",
            ";", "|", "&", ">", "<", "!", "#", "=", "a=b", "\x01\x02", "\x7f", "​", "﻿",
            "--toolbox", "--host", "-socket", FP, FP + "/tmp/x", "a" + FP + "b"]
BYTES_POOL = [b"\xff", b"\xfe\xff", b"\x80abc", b"ok\xc3", b"\xed\xa0\x80"]
VAL_POOL = ["", " ", "a=b=c", "line1\nline2", "ñ日本🎉", "$(id)", "`id`", "'\"", "\\",
            "/app/fz", "x/run/flatpak/y", "/apply", "/app", "tab\there", "\r\n", "=", "-", FP, FP + "/tmp/x"]
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
        if not env_passes(name, val):
            val = val + "~" + str(rng.random())
        total += len(val)
        env[name] = val
        expect[name] = env_passes(name, val)
    return env, expect

class Ctx:
    pass

def hr(ctx, cmd, stdin=b"", env=None, cwd=HOME, timeout=120, dd=False):
    e = dict(ctx.base_env)
    e.update(env or {})
    e["PWD"] = cwd
    return subprocess.run(ctx.hr + (["--"] if dd else []) + cmd, input=stdin, capture_output=True,
                          env=e, cwd=cwd, timeout=timeout)

def check_probe(p, i, args, env, expect_env, stdin, out_n, err_n, rc, cwd):
    problems = []
    if p.returncode != rc:
        problems.append(f"exit {p.returncode} != {rc}")
    head, _, blob = p.stdout.partition(b"\n")
    try:
        res = json.loads(head)
    except ValueError:
        return [f"no probe output (exit {p.returncode}); out={p.stdout[:150]!r} err={p.stderr[-300:]!r}"]
    want_args = [rewrite(a if isinstance(a, str) else os.fsdecode(a)) for a in args]
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
        if ok and got != rewrite(env[k]):
            problems.append(f"env {k} not passed ({(got or '')[:30]!r})")
        if not ok and got == rewrite(env[k]):
            problems.append(f"env {k} should have been dropped")
    if blob != random.Random(str(i)).randbytes(out_n):
        problems.append(f"stdout corrupted ({len(blob)} of {out_n} bytes)")
    if p.stderr != b"noise-" * err_n:
        problems.append(f"stderr differs: {p.stderr[-200:]!r}")
    return problems

def sc_roundtrip(rng, i, ctx):
    dd = rng.random() < 0.15
    args = gen_args(rng)
    env, expect_env = gen_env(rng)
    stdin = rng.randbytes(pick_size(rng, STDIN_SIZES))
    out_n = pick_size(rng, OUT_SIZES)
    err_n = rng.choice([0, 0, 0, 0, rng.randint(1, 20000)])
    rc = rng.choice([0] * 6 + [rng.randint(1, 255)])
    cwd = rng.choice(ctx.cwds)
    env.update(FZ_KEYS=",".join(expect_env), FZ_OUT=str(out_n), FZ_ERR=str(err_n), FZ_RC=str(rc), FZ_SEED=str(i))
    t = time.monotonic()
    p = hr(ctx, ["python3", "-c", PROBE, *args], stdin, env, cwd, dd=dd)
    ms = (time.monotonic() - t) * 1000
    probs = check_probe(p, i, args, env, expect_env, stdin, out_n, err_n, rc, cwd)
    return probs, ms, {"bytes": len(stdin) + out_n}

def sc_exitcode(rng, i, ctx):
    r = rng.random()
    dd = rng.random() < 0.2
    if r < 0.57:
        rc = rng.randint(0, 255)
        cmd, want = ["python3", "-c", f"import sys; sys.exit({rc})"], rc
    elif r < 0.77:
        cmd, want = [rng.choice([f"fz-missing-{rng.getrandbits(32):x}", f"/nonexistent/{rng.getrandbits(32):x}",
                                 f"./fz-rel-{rng.getrandbits(32):x}", ""])], 127
    elif r < 0.87:
        cmd, want = [ctx.noexec], 126
    elif r < 0.93:
        cmd, want, dd = [], 2, rng.random() < 0.5
    else:
        cmd, want = [ctx.tmp], 126
    t = time.monotonic()
    p = hr(ctx, cmd, cwd=HOME, timeout=60, dd=dd)
    ms = (time.monotonic() - t) * 1000
    probs = [] if p.returncode == want else [f"{(cmd or ['(none)'])[0][:40]!r} exit {p.returncode}, want {want} ({p.stderr[-150:]!r})"]
    return probs, ms, {}

def leftover(ctx, marker):
    pat = marker[:-1] + "[" + marker[-1] + "]"
    for _ in range(10):
        p = hr(ctx, ["pgrep", "-f", pat], timeout=30)
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
    sig = rng.choice([signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
    early = rng.random() < 0.2
    marker = f"FZMARK-{ctx.seed}-{i}"
    e = dict(ctx.base_env, PWD=HOME)
    t = time.monotonic()
    p = subprocess.Popen(ctx.hr + ["python3", "-c", SLEEPER, marker], stdin=subprocess.DEVNULL,
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
        if not early and rc not in ok_rc:
            probs.append(f"{sig.name}: exit {rc}, want {128 + sig}")
    except subprocess.TimeoutExpired:
        p.kill()
        probs.append(f"{sig.name}: did not stop within 30 s")
    p.stdout.close()
    ms = (time.monotonic() - t) * 1000
    if leftover(ctx, marker):
        probs.append(f"{sig.name}{' (early)' if early else ''}: process left running on the host")
        hr(ctx, ["pkill", "-f", marker[:-1] + "[" + marker[-1] + "]"], timeout=30)
    if early and probs:
        return [], ms, {"known": "early signal lost by flatpak-spawn (upstream race)"}
    return probs, ms, {}

def sc_burst(rng, i, ctx):
    k = rng.randint(5, 80)
    t = time.monotonic()
    procs = []
    for j in range(k):
        stdin = rng.randbytes(rng.randint(0, 5000))
        rc = rng.choice([0, 0, 0, rng.randint(1, 255)])
        out_n = rng.randint(0, 3000)
        env = dict(ctx.base_env, PWD=HOME, FZ_OUT=str(out_n), FZ_RC=str(rc), FZ_SEED=f"{i}.{j}", FZ_KEYS="")
        p = subprocess.Popen(ctx.hr + ["python3", "-c", PROBE], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=HOME)
        procs.append((p, stdin, rc, out_n, j))
    results = [None] * k
    threads = []
    for idx, (p, stdin, rc, out_n, j) in enumerate(procs):
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
    for (p, stdin, rc, out_n, j), (out, err) in zip(procs, results):
        cp = subprocess.CompletedProcess(p.args, p.returncode, out, err)
        pr = check_probe(cp, f"{i}.{j}", [], {}, {}, stdin, out_n, 0, rc, HOME)
        if pr:
            probs.append(f"#{j}/{k}: " + "; ".join(pr))
    return probs[:3] + ([f"... {len(probs) - 3} more"] if len(probs) > 3 else []), ms, {"n": k}

def sc_mcp(rng, i, ctx):
    n = rng.choice([1, 5, 20, 50, 200])
    pipelined = rng.random() < 0.3
    e = dict(ctx.base_env, PWD=HOME)
    alphabet = PRINTABLE + "\n\t\"\\ñ日本🎉'"
    msgs = [{"jsonrpc": "2.0", "id": k, "p": rstr(rng, 0, rng.choice([10, 200, 5000, 65536]), alphabet)} for k in range(n)]
    t = time.monotonic()
    p = subprocess.Popen(ctx.hr + ["python3", "-u", "-c", SERVER], stdin=subprocess.PIPE,
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
    return probs, ms, {"rtt": rtts}

def remove(path):
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
    for _ in range(20):
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            return
        time.sleep(0.05)

DEFAULT = object()

def sc_cache(rng, i, ctx):
    home = f"{ctx.tmp}/cache-{i}"
    cache = f"{home}/host-bridge/host.path"
    os.makedirs(f"{home}/host-bridge")
    variant = rng.choice(["empty", "garbage", "huge", "binary", "newlines", "long", "custom", "trailing-nl",
                          "directory", "unreadable", "symlink", "fifo", "missing"])
    custom = f"/fz/{rng.getrandbits(32):x}:/usr/bin"
    content = {"empty": b"", "garbage": b"hello world", "huge": b"99999999999999 1", "newlines": b"\n\n\n",
               "binary": rng.randbytes(rng.randint(1, 100)), "long": b"7" * 10000,
               "custom": custom.encode(), "trailing-nl": (custom + "\n\n").encode()}.get(variant)
    want = {"garbage": "hello world", "huge": "99999999999999 1", "newlines": DEFAULT, "long": "7" * 10000,
            "custom": custom, "trailing-nl": custom, "directory": DEFAULT, "unreadable": DEFAULT}.get(variant)
    if content is not None:
        with open(cache, "wb") as f:
            f.write(content)
    elif variant == "directory":
        os.mkdir(cache)
    elif variant == "unreadable":
        with open(cache, "w") as f:
            f.write("/usr/bin")
        os.chmod(cache, 0)
    elif variant == "symlink":
        with open(f"{home}/target", "w") as f:
            f.write(custom)
        os.symlink(f"{home}/target", cache)
        want = custom
    elif variant == "fifo":
        os.mkfifo(cache)
    t = time.monotonic()
    probs = []
    try:
        p = hr(ctx, ["/usr/bin/python3", "-c", PROBE], env={"FZ_SEED": str(i), "FZ_KEYS": "PATH",
                                                          "XDG_CACHE_HOME": home}, timeout=30)
        probs = check_probe(p, i, [], {}, {}, b"", 0, 0, 0, HOME)
        if variant in ("directory", "unreadable", "binary"):
            probs = [x for x in probs if not x.startswith("stderr differs")]
        if not probs and want is not None:
            got = json.loads(p.stdout.partition(b"\n")[0])["env"]["PATH"]
            if want is DEFAULT:
                if "/usr/bin" not in str(got).split(":"):
                    probs.append(f"PATH {str(got)[:60]!r} is not the host default")
            elif got != want:
                probs.append(f"PATH {str(got)[:60]!r} != {want[:60]!r}")
    except subprocess.TimeoutExpired:
        probs = ["hung (30 s) on a broken host.path"]
        unblock(cache)
    ms = (time.monotonic() - t) * 1000
    if variant == "unreadable":
        os.chmod(cache, 0o600)
    shutil.rmtree(home, ignore_errors=True)
    return [f"{variant}: {x}" for x in probs], ms, {}

SCENARIOS = {"roundtrip": sc_roundtrip, "exitcode": sc_exitcode, "signal": sc_signal, "burst": sc_burst,
             "mcp": sc_mcp, "cache": sc_cache}

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
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 8)
    ap.add_argument("--project", action="store_true", help="test the scripts in this folder, not the installed ones")
    a = ap.parse_args()

    scale = a.count / sum(n for _, n in PLAN)
    plan = [(c, max(1, round(n * scale))) for c, n in PLAN]
    total = sum(n for _, n in plan)

    ctx = Ctx()
    ctx.seed = a.seed
    ctx.base_env = {k: v for k, v in os.environ.items()}
    src = f"{PROJECT}/scripts" if a.project else "/app/bridge/bin"
    ctx.hr = ["/bin/bash", f"{src}/host-run"]
    cache_root = f"{HOME}/.var/app/{APP}/cache"
    for old in os.listdir(cache_root):
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
          f"testing={'project scripts' if a.project else 'installed app'}", flush=True)
    jobs_before = set(f for f in os.listdir(RUN_DIR) if f.startswith("job."))
    fds_before = len(os.listdir("/proc/self/fd"))

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

    order = list(indices)
    random.Random(a.seed).shuffle(order)
    with ThreadPoolExecutor(a.workers) as pool:
        futs = [pool.submit(run, i) for i in order]
        for f in futs:
            f.result()
    wall = time.monotonic() - start

    time.sleep(2)
    leaks = []
    jobs = set(f for f in os.listdir(RUN_DIR) if f.startswith("job.")) - jobs_before
    if jobs:
        leaks.append(f"{len(jobs)} job files left in {RUN_DIR}")
    p = hr(ctx, ["pgrep", "-fc", "FZMAR[K]"], timeout=30)
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

    print(f"\n{'category':<11}{'runs':>7}{'pass':>7}{'fail':>6}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}")
    for cat, _ in plan:
        rs = [r for r in results.values() if r[0] == cat]
        if not rs:
            continue
        ms = [r[2] for r in rs]
        f = sum(1 for r in rs if r[1])
        print(f"{cat:<11}{len(rs):>7}{len(rs) - f:>7}{f:>6}{pct(ms, .5):>9.0f}{pct(ms, .95):>9.0f}{pct(ms, .99):>9.0f}{max(ms):>9.0f}")
    rt = [r for r in results.values() if r[0] == "roundtrip" and not r[1]]
    for mode in ("host",):
        small = [r[2] for r in rt if r[3]["bytes"] < 10000]
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

