"""画层的主机侧测试 —— 验证菜单接管屏幕时强制整屏刷新。

不需要 ESP-IDF：tests/fw_host/stubs/ 里有 ESP-IDF 头的桩，
编译真实的 firmware/main/game/game_draw.c，跑推屏行为的断言。

菜单叠在宠物画面上（黑遮罩/残影）就是这么来的：引擎接管屏幕时
逐行 diff 对着没记过宠物帧的黑影子比，一行都不推。
"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_draw_layer_on_host():
    """跑主机侧画层测试 —— 退出码非 0 就是接管屏幕的刷新逻辑不对。"""
    script = ROOT / "tests" / "fw_host" / "run.sh"
    out = subprocess.run(["bash", str(script)], capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "draw layer: 0 项失败" in out.stdout, out.stdout
