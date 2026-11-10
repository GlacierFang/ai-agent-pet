#!/usr/bin/env bash
# 在开发机上跑固件引擎 —— 不需要 ESP-IDF。
#
# 引擎的物理和事件逻辑是纯 C，没有硬件依赖：用桩头替掉 ESP-IDF 的头文件，
# 把 petd/packs/brickout.json 生成成 C 场景，编译真实的 game_phys.c / game_comp.c，
# 跑物理与事件的行为断言。
#
# 用法：bash tests/fw_host/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${TMPDIR:-/tmp}/petd_host_test"
mkdir -p "$OUT"

python3 "$ROOT/tools/gen_host_scene.py" "$OUT/scene.h"

gcc -std=c11 -O1 -Wall \
    -I"$ROOT/tests/fw_host/stubs" \
    -I"$ROOT/firmware/main/game" \
    -I"$OUT" \
    "$ROOT/firmware/main/game/game_comp.c" \
    "$ROOT/firmware/main/game/game_phys.c" \
    "$ROOT/firmware/main/game/game_glyph.c" \
    "$ROOT/tests/fw_host/test_game_engine.c" \
    "$ROOT/tests/fw_host/stubs.c" \
    -lm -o "$OUT/test_engine"

"$OUT/test_engine"
