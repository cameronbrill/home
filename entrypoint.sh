#!/bin/bash
set -euo pipefail

echo "=== Home Automation Service Starting ==="

exec python -m core.main

