#!/usr/bin/env bash
set -euo pipefail

uvicorn main:APP --host 0.0.0.0 --port 8099
