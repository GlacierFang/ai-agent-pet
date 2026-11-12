#!/usr/bin/env bash
# 在开发机上跑固件引擎 —— 不需要 ESP-IDF。
#
# 引擎的物理和事件逻辑是纯 C，没有硬件依赖：用桩头替掉 ESP-IDF 的头文件，
# 把 petd/packs/*.json 生成成 C 场景，编译真实的 game_phys.c / game_comp.c，
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

# 贪吃蛇场景 —— 同一套引擎，另一套语义（纯网格 + 方向）。
OUT3="${TMPDIR:-/tmp}/petd_host_snake"
mkdir -p "$OUT3"

python3 "$ROOT/tools/gen_host_scene.py" "$OUT3/scene_snake.h" snake

gcc -std=c11 -O1 -Wall \
    -I"$ROOT/tests/fw_host/stubs" \
    -I"$ROOT/firmware/main/game" \
    -I"$OUT3" \
    "$ROOT/firmware/main/game/game_comp.c" \
    "$ROOT/firmware/main/game/game_phys.c" \
    "$ROOT/firmware/main/game/game_glyph.c" \
    "$ROOT/tests/fw_host/test_snake_engine.c" \
    "$ROOT/tests/fw_host/stubs.c" \
    -lm -o "$OUT3/test_snake_engine"

"$OUT3/test_snake_engine"

# 画层测试 —— 验证「引擎接管屏幕时强制整屏刷新」。
OUT2="${TMPDIR:-/tmp}/petd_host_draw"
mkdir -p "$OUT2"

gcc -std=c11 -O1 -Wall \
    -I"$ROOT/tests/fw_host/stubs" \
    -I"$ROOT/firmware/main/game" \
    "$ROOT/firmware/main/game/game_draw.c" \
    "$ROOT/tests/fw_host/test_draw_layer.c" \
    "$ROOT/tests/fw_host/draw_stubs.c" \
    -lm -o "$OUT2/test_draw_layer"

"$OUT2/test_draw_layer"

# 打地鼠场景 —— 新加的 move_cell / intent_overlap 原语。
OUT4="${TMPDIR:-/tmp}/petd_host_whack"
mkdir -p "$OUT4"

python3 "$ROOT/tools/gen_host_scene.py" "$OUT4/scene_whack.h" whack

gcc -std=c11 -O1 -Wall \
    -I"$ROOT/tests/fw_host/stubs" \
    -I"$ROOT/firmware/main/game" \
    -I"$OUT4" \
    "$ROOT/firmware/main/game/game_comp.c" \
    "$ROOT/firmware/main/game/game_phys.c" \
    "$ROOT/firmware/main/game/game_glyph.c" \
    "$ROOT/tests/fw_host/test_whack_engine.c" \
    "$ROOT/tests/fw_host/stubs.c" \
    -lm -o "$OUT4/test_whack_engine"

"$OUT4/test_whack_engine"

# 钓鱼场景 —— 两阶段时机玩法：advance_cell + intent_overlap + 双定时器切阶段。
OUT5="${TMPDIR:-/tmp}/petd_host_fishing"
mkdir -p "$OUT5"

python3 "$ROOT/tools/gen_host_scene.py" "$OUT5/scene_fishing.h" fishing

gcc -std=c11 -O1 -Wall \
    -I"$ROOT/tests/fw_host/stubs" \
    -I"$ROOT/firmware/main/game" \
    -I"$OUT5" \
    "$ROOT/firmware/main/game/game_comp.c" \
    "$ROOT/firmware/main/game/game_phys.c" \
    "$ROOT/firmware/main/game/game_glyph.c" \
    "$ROOT/tests/fw_host/test_fishing_engine.c" \
    "$ROOT/tests/fw_host/stubs.c" \
    -lm -o "$OUT5/test_fishing_engine"

"$OUT5/test_fishing_engine"
