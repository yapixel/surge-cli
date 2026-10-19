#!/bin/sh
# Read-only parity check: run the same commands through the native and Python
# backends against one Controller and compare their --raw JSON.
#
#   SURGE_CLI_PASSWORD=... parity_check.sh <host:port>
#
# "identical" = same JSON; "same-shape" = same keys/types (live values such as
# uptime or traffic differ); "DIFF" = structural mismatch worth investigating.
# A second block checks streaming (diagnostics, watch speed) and retrieve-data;
# it takes about a minute and prints "ok" / "skipped" / "FAIL".
set -eu

[ $# -eq 1 ] || { echo "usage: $0 <host:port>" >&2; exit 2; }
[ -n "${SURGE_CLI_PASSWORD:-}" ] || { echo "SURGE_CLI_PASSWORD is not set" >&2; exit 2; }
REMOTE=$1
CLI="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)/surge-cli"
SURGE_CLI_BACKEND=native "$CLI" --which-backend >/dev/null || exit 1
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

COMMANDS="version
status
environment
dump policy
dump summary
rule match example.com
rule temp list"

fail=0
set -f
old_ifs=$IFS; IFS='
'
for cmd in $COMMANDS; do
  IFS=$old_ifs
  for backend in native python; do
    # shellcheck disable=SC2086 # word-split the command on purpose
    SURGE_CLI_BACKEND=$backend "$CLI" --raw -r "$REMOTE" $cmd > "$TMP/$backend.json" 2>&1 || true
  done
  verdict=$(python3 -I - "$TMP/native.json" "$TMP/python.json" <<'PY'
import json, sys

def shape(v):
    """Recursive structure of a JSON value: keys and scalar types, not values."""
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    return type(v).__name__

try:
    a, b = (json.load(open(p)) for p in sys.argv[1:3])
except Exception as e:
    print(f"DIFF (unparsable output: {e})")
    raise SystemExit
print("identical" if a == b else "same-shape" if shape(a) == shape(b) else "DIFF")
PY
)
  printf '%-12s %s\n' "$verdict" "$cmd"
  case $verdict in DIFF*) fail=1 ;; esac
  IFS='
'
done
IFS=$old_ifs
set +f

# Streaming and data-channel checks (bounded in time; still read-only).
# "ok" = Python behaves as required; "skipped" = nothing to test; "FAIL" = regression.
python3 -I - "$CLI" "$REMOTE" <<'PY' || fail=1
import json, os, subprocess, sys
cli, remote = sys.argv[1], sys.argv[2]

def run(backend, argv, timeout):
    """Run one command; return (exited, rc, frames) where frames are parsed JSON lines."""
    env = dict(os.environ, SURGE_CLI_BACKEND=backend)
    cmd = [cli, "--raw", "-r", remote, *argv]
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, timeout=timeout)
        exited, rc, out = True, p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        exited, rc, out = False, None, e.stdout or b""
    frames = []
    for line in out.decode(errors="replace").splitlines():
        try: frames.append(json.loads(line))
        except ValueError: pass
    return exited, rc, frames

def shape(v):
    if isinstance(v, dict): return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list): return [shape(v[0])] if v else []
    return type(v).__name__

failed = False
def report(verdict, name):
    global failed
    print(f"{verdict:<12} {name}")
    failed |= verdict.startswith("FAIL")

# diagnostics must finish with {"result":"complete"} and exit on both backends.
res = {b: run(b, ["diagnostics"], 90) for b in ("native", "python")}
ok = all(e and fr and fr[-1] == {"result": "complete"} for e, _, fr in res.values())
report("ok" if ok else "FAIL", "diagnostics (exits after complete)")

# watch speed: event frames must be unwrapped identically (compare structure).
res = {b: run(b, ["watch", "speed"], 8) for b in ("native", "python")}
n, p = res["native"][2], res["python"][2]
if len(n) < 2 or len(p) < 2:
    report("skipped", "watch speed (no events within 8s)")
else:
    report("same-shape" if shape(n[1]) == shape(p[1]) else "FAIL", "watch speed (event frames)")

# retrieve-data: Python must return a body for a captured record; native is known broken.
_, _, recent = run("python", ["dump", "recent"], 60)
reqs = recent[0].get("requests", []) if recent else []
ids = [r["id"] for r in reqs if r.get("replica") and r.get("streamHasResponseBody")]
if not ids:
    report("skipped", "retrieve-data (no captured record with a body)")
else:
    rid = str(ids[0])
    env = dict(os.environ, SURGE_CLI_BACKEND="python")
    p = subprocess.run([cli, "--raw", "-r", remote, "retrieve-data", rid, "response"],
                       env=env, capture_output=True, timeout=60)
    report("ok" if p.returncode == 0 and p.stdout else "FAIL", f"retrieve-data {rid} response (python)")
    nb = subprocess.run([cli, "--raw", "-r", remote, "retrieve-data", rid, "response"],
                        env=dict(os.environ, SURGE_CLI_BACKEND="native"), capture_output=True, timeout=60)
    report("identical" if nb.returncode == 0 and nb.stdout == p.stdout else "native-broken (expected)",
           f"retrieve-data {rid} response (native)")
sys.exit(1 if failed else 0)
PY
exit $fail
