#!/bin/bash
# Explicit SYNTHETIC demo (fixtures only, not real analysis; no API key needed)
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m vii.main --demo
