#!/bin/bash
# Finder-friendly macOS entry point; also works with: bash Strata.command
launcher_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
/bin/bash "$launcher_directory/Strata.sh" "$@"
status=$?
if [[ $status -ne 0 && -t 0 ]]; then
    printf '\nStrata exited with an error. See the messages above. Press Return to close.'
    read -r _
fi
exit "$status"
