#!/bin/bash
# Rebuild wheelhouse/ with every wheel the offline install needs.
# Covers Linux (manylinux x86_64) plus Windows (win_amd64) on CPython 3.14,
# for the app, mcp, and dev extras. Desktop (PySide6) stays online only:
# its webengine wheel tops 100 MB, past the GitHub single file limit.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf wheelhouse
mkdir -p wheelhouse
python3 -m pip download -q -d wheelhouse ".[app,mcp,dev]"
python3 -m pip download -q -d wheelhouse --only-binary=:all: \
  --python-version=3.14 --platform=win_amd64 --abi=cp314 ".[app,mcp,dev]"
python3 -m pip download -q -d wheelhouse setuptools wheel
du -sh wheelhouse
ls wheelhouse | wc -l
