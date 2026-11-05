#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tools_dir="${FIRMWARE_TOOLS_DIR:-/workspace/toolchain}"
arm_dir="$tools_dir/gcc-arm-none-eabi-9-2019-q4-major"
mkdir -p "$tools_dir/cache"
if [[ ! -x "$arm_dir/bin/arm-none-eabi-as" ]]; then
  archive="$tools_dir/cache/gcc-arm-none-eabi-9-2019-q4-major-x86_64-linux.tar.bz2"
  curl --fail --location --silent --show-error \
    https://github.com/adafruit/arduino-board-index/releases/download/build-tools/gcc-arm-none-eabi-9-2019-q4-major-x86_64-linux.tar.bz2 \
    --output "$archive"
  printf '%s  %s\n' bcd840f839d5bf49279638e9f67890b2ef3a7c9c7a9b25271e83ec4ff41d177a "$archive" | sha256sum --check -
  tar -xjf "$archive" -C "$tools_dir"
fi
"$arm_dir/bin/arm-none-eabi-as" --version
if [[ ! -x "$tools_dir/venv/bin/python" ]]; then python3 -m venv "$tools_dir/venv"; fi
"$tools_dir/venv/bin/python" -m pip install -r "$repo_dir/tools/requirements-firmware.txt"
