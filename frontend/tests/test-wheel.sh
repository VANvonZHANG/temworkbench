#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
test_port="${TEMWORKBENCH_TEST_PORT:-18766}"
test_url="http://127.0.0.1:$test_port"
if curl --silent --max-time 1 --output /dev/null "$test_url/"; then
  printf 'Port %s already responds. Set TEMWORKBENCH_TEST_PORT to a free port.\n' "$test_port" >&2
  exit 1
fi

run_dir="$(mktemp -d "${TMPDIR:-/tmp}/temworkbench-wheel.XXXXXX")"
server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf -- "$run_dir"
}
trap cleanup EXIT

cd "$repo_dir"
uv build --out-dir "$run_dir"
uv venv --python 3.11 "$run_dir/venv"
uv export --quiet --locked --no-dev --no-emit-project --output-file "$run_dir/requirements.txt"
uv pip install --quiet --python "$run_dir/venv/bin/python" -r "$run_dir/requirements.txt"
uv pip install --quiet --python "$run_dir/venv/bin/python" --no-deps "$run_dir"/*.whl

"$run_dir/venv/bin/python" - <<'PY'
from pathlib import Path

import temworkbench

source = Path("src/temworkbench/web")
installed = Path(temworkbench.__file__).with_name("web")
expected = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
actual = {path.relative_to(installed): path.read_bytes() for path in installed.rglob("*") if path.is_file()}
assert expected and expected == actual, "The wheel web files differ from the source tree."
print(f"Wheel contains all {len(actual)} web files and their contents match.")
PY

(
  cd "$run_dir"
  exec env PATH="$run_dir/venv/bin" \
    TEMWORKBENCH_OPERATOR_TOKEN=browser-test-operator TEMWORKBENCH_AGENT_TOKEN=browser-test-agent \
    "$run_dir/venv/bin/temworkbench" --port "$test_port" --data "$run_dir/simulator" \
    --device-python "$repo_dir/.venv-device/bin/python"
) > "$run_dir/server.log" 2>&1 &
server_pid=$!

if ! curl --fail --silent --show-error --retry 15 --retry-connrefused --retry-delay 1 \
  "$test_url/" --output "$run_dir/index.html"; then
  cat "$run_dir/server.log" >&2
  exit 1
fi
cmp "$run_dir/index.html" src/temworkbench/web/index.html

cd frontend
TEMWORKBENCH_TEST_URL="$test_url" npm run test:e2e
