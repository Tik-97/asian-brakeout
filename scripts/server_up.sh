#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/asian-breakout}"

cd "$PROJECT_DIR"
mkdir -p runtime/dashboard
docker compose up -d --build
docker compose ps
