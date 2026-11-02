#!/bin/bash
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m vii.main --api
