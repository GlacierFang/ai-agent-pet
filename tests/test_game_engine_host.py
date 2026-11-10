"""引擎行为的主机侧测试 —— 在开发机上跑固件的物理与事件逻辑。

不需要 ESP-IDF：tests/fw_host/stubs/ 里有 ESP-IDF 头的桩，
tools/gen_host_scene.py 把 petd/packs/brickout.json 生成成 C 场景，
编译真实的 game_phys.c / game_comp.c 跑断言。

引擎改坏了（反弹方向反了、砖消不掉、边界不拦），这个测试会红。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_engine_behaviour_on_host():
    """跑主机侧引擎测试 —— 退出码非 0 就是引擎行为不对。"""
    script = ROOT / "tests" / "fw_host" / "run.sh"
    out = subprocess.run(["bash", str(script)], capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "0 项失败" in out.stdout, out.stdout
