#!/usr/bin/env python3
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, ".github/workflows/build.yml")

def main():
    changed = "--changed" in sys.argv
    wf = yaml.safe_load(open(WF))
    job = wf["jobs"]["publish"]
    image = job["container"]["image"]
    env = dict(wf.get("env", {}))
    if not os.path.isdir(os.path.join(ROOT, "repo")):
        sys.exit("build the Flatpak into repo/ first")

    w = tempfile.mkdtemp(prefix="ci-dryrun-")
    ws, origin = f"{w}/ws", f"{w}/origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", ROOT, origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, ws], check=True)
    os.makedirs(f"{ws}/out")
    subprocess.run(["tar", "-cf", f"{ws}/out/repo.tar", "-C", ROOT, "repo"], check=True)
    open(f"{ws}/out/icon.png", "wb").write(b"\x89PNG fake icon")
    if changed:
        m = open(f"{ws}/{env['MANIFEST']}").read()
        open(f"{ws}/{env['MANIFEST']}", "w").write(m.replace("claude-desktop_2.", "claude-desktop_9."))

    g = f"{w}/gnupg"
    os.makedirs(g, mode=0o700)
    subprocess.run(["gpg", "--homedir", g, "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
                    "--quick-gen-key", "dry run <dry@example.invalid>", "ed25519", "sign", "never"],
                   check=True, capture_output=True)
    fpr = subprocess.run(["gpg", "--homedir", g, "--with-colons", "--list-keys"], capture_output=True,
                         text=True).stdout.split("fpr:::::::::")[1].split(":")[0]
    secret = subprocess.run(["gpg", "--homedir", g, "--batch", "--armor", "--export-secret-keys", fpr],
                            capture_output=True, text=True, check=True).stdout
    with open(f"{w}/pub.gpg", "wb") as f:
        f.write(subprocess.run(["gpg", "--homedir", g, "--export", fpr], capture_output=True, check=True).stdout)
    subprocess.run(["gpgconf", "--homedir", g, "--kill", "gpg-agent"])

    os.makedirs(f"{w}/stubs")
    with open(f"{w}/stubs/gh", "w") as f:
        f.write('#!/bin/bash\necho "gh $*" >> /w/gh.log\n'
                'case "$1 $2" in "release view") exit 1;; "release create")\n'
                '  for a in "$@"; do case "$a" in _site/*) test -s "$a" || { echo "missing $a"; exit 1; };; esac; done;;\n'
                'esac\nexit 0\n')
    os.chmod(f"{w}/stubs/gh", 0o755)

    genv = {
        **env, "GITHUB_WORKSPACE": "/w/ws", "GITHUB_ENV": "/w/github_env", "GITHUB_OUTPUT": "/w/github_output",
        "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "musmandev092/claude-desktop-flatpak-for-linux",
        "GITHUB_RUN_ID": "123456789", "GITHUB_EVENT_NAME": "schedule" if changed else "push",
        "GITHUB_REF": "refs/heads/main", "HOME": "/root", "CI": "true",
        "PATH": "/w/stubs:/app/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
    ctx = {"secrets.FLATPAK_GPG_PRIVATE_KEY": secret, "secrets.FLATPAK_GPG_KEY_ID": fpr,
           "github.token": "dry-run-token",
           "needs.check.outputs.changed": "true" if changed else ""}

    def expr(v):
        return re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", lambda m: ctx.get(m.group(1), f"<<{m.group(1)}>>"), str(v))

    steps = []
    for st in job["steps"]:
        name = st.get("name") or st.get("uses", "")
        cond = st.get("if")
        if cond and "needs.check.outputs.changed == 'true'" in cond and not changed:
            steps.append(("skip", name, None, None))
            continue
        if "run" in st:
            senv = {k: expr(v) for k, v in st.get("env", {}).items()}
            steps.append(("run", name, st["run"], senv))
        else:
            steps.append(("stub", name, st.get("uses"), None))

    with open(f"{w}/driver.sh", "w") as f:
        f.write("set -u\ncd /w/ws\n: > /w/github_env\n")
        f.write("git config --global user.name dry; git config --global user.email dry@example.invalid\n")
        f.write("git -C /w/ws remote set-url origin /w/origin.git\n")
        for i, (kind, name, body, senv) in enumerate(steps):
            f.write(f"echo; echo '=== {name.replace(chr(39), '')} ({kind})'\n")
            if kind != "run":
                if body and "upload-pages-artifact" in body:
                    f.write("test -s _site/index.html && test -s _site/repo/config && echo 'pages artifact: _site ok'\n")
                elif body and "attest-build-provenance" in body:
                    f.write("for s in _site/BUILDINFO.json _site/claude-desktop.flatpakref _site/claude-desktop.flatpakrepo; do test -s $s || exit 1; done; echo 'attest subjects exist'\n")
                continue
            path = f"{w}/step{i}.sh"
            with open(path, "w") as s:
                s.write(body)
            envs = " ".join(shlex.quote(f"{k}={v}") for k, v in senv.items())
            f.write(f"( set -a; while IFS= read -r l; do export \"$l\"; done < /w/github_env; set +a; "
                    f"env {envs} bash -e /w/step{i}.sh ) || {{ echo \"STEP FAILED: {name}\"; exit 1; }}\n")
        f.write("echo; echo '=== results'; cat /w/gh.log; echo\n"
                "git -C /w/origin.git log --oneline -2; echo; cat _site/BUILDINFO.json; echo\n"
                "echo '=== a user installs from the published folder, with the signing key'\n"
                "export FLATPAK_USER_DIR=/w/fp\n"
                "flatpak --user remote-add --gpg-import=/w/pub.gpg dry file:///w/ws/_site/repo && "
                "flatpak --user remote-ls dry | grep -q \"$APP_ID\" && echo 'signature verified: OK' "
                "|| { echo 'SIGNATURE CHECK FAILED'; exit 1; }\n"
                "flatpak --user remote-add --no-gpg-verify nosig file:///w/ws/_site/repo >/dev/null 2>&1; "
                "grep -q \"$(cat /w/ws/repo/refs/heads/app/$APP_ID/x86_64/master)\" _site/BUILDINFO.json "
                "&& echo 'BUILDINFO flatpak_commit matches the published commit: OK' || { echo 'BUILDINFO MISMATCH'; exit 1; }\n")
    os.chmod(f"{w}/driver.sh", 0o755)

    cmd = ["podman", "run", "--rm", "--privileged", "-v", f"{w}:/w:Z"]
    for k, v in genv.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [image, "bash", "/w/driver.sh"]
    print(f"dry run ({'new version' if changed else 'no new version'}) in {image.split('@')[0]}", flush=True)
    rc = subprocess.run(cmd).returncode
    if rc == 0:
        subprocess.run(["podman", "unshare", "rm", "-rf", w])
    else:
        print(f"work folder kept for inspection: {w}")
    print("DRY RUN", "PASSED" if rc == 0 else "FAILED")
    return rc

if __name__ == "__main__":
    sys.exit(main())

