#!/usr/bin/env bash
# macOS/Linux launcher. Keep setup local to this checkout; never install globally.
set -eu

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

fail() {
    printf '\n%s\n' "$*" >&2
    exit 1
}

if [[ ! -x .venv/bin/python ]]; then
    python_command=''
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
            python_command="$candidate"
            break
        fi
    done
    [[ -n "$python_command" ]] || fail 'Install Python 3.10+ and make python3 available in your PATH, then try again.'
    printf '%s\n' 'First run: setting up Python environment...'
    "$python_command" -m venv .venv ||
        fail 'Could not create .venv. Install venv support for your Python (python3-venv on Debian/Ubuntu), then retry.'
fi

python_executable="$PWD/.venv/bin/python"
"$python_executable" -c 'import sys; sys.exit(sys.version_info < (3, 10))' ||
    fail 'This .venv needs Python 3.10+. Rename it and relaunch with a supported Python installed.'

# Record only successful installs, so failures retry and requirement changes update.
requirements_signature="$(cksum < requirements.txt)"
stamp='.venv/.strata-requirements'
installed_signature=''
if [[ -f "$stamp" ]]; then
    installed_signature="$(cat "$stamp")"
fi
if [[ "$installed_signature" != "$requirements_signature" ]]; then
    "$python_executable" -m pip install --upgrade pip ||
        fail 'Could not update pip. Check the error above and your internet connection, then retry.'
    "$python_executable" -m pip install -r requirements.txt ||
        fail 'Installing dependencies failed. Check the error above, then rerun this launcher to retry.'
    printf '%s\n' "$requirements_signature" > "$stamp"
fi

exec "$python_executable" run.py "$@"
