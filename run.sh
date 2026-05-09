#!/usr/bin/env sh
cd "$(dirname "$0")"
uv run mesa
echo
read -r -p "Press Enter to close..." _
