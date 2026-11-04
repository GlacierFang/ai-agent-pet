# 参与贡献

> 项目名 `ai-agent-pet`（GitHub 仓库名，2026-11-03 定）。

## 两条线分开授权

**代码**和**美术**分开授权，不要混在一个 LICENSE 里。

| 内容 | 授权 |
|---|---|
| 代码（petd / firmware） | 见根目录 `LICENSE`（Apache-2.0） |
| 美术（`skins/`） | **每份素材单独声明**，见 `meta.json` 的 `license` 字段 |
| 文档 | 同代码 |

原因：程序生成的默认角色让 clone 下来的人零授权风险就能用；维护者提供的美术作为可选皮肤包单独发布。混在一起授权会让「能不能商用分发」这个问题无解。

## 提交素材

PR 里要注明：

- 来源（自己画的 / AI 生成 / 第三方）
- 授权
- 如果是第三方，必须附原始授权证明

## 环境

```bash
# petd
python3 -m venv venv
./venv/bin/pip install -e '.[dev]'
./venv/bin/pytest

# 固件
. $IDF_PATH/export.sh
idf.py set-target esp32s3 && idf.py build
```

## 提交前自查

- [ ] `pytest` 过
- [ ] 状态语义有变化 → 同步改 `docs/状态语义.md` 和 `petd/data/state_rules.json`
- [ ] 加了新 feature → 在 `docs/feature开发.md` 补一段
- [ ] 改了旋钮语义 → 改 `petd/data/gestures.json`，**不要改固件**
- [ ] 美术有改动 → 跑 `python -m petd.tools.check_assets`
- [ ] 加了新的素材 → 在那个皮肤目录放 `meta.json` 声明 `license` 字段
- [ ] 任何改动都**不应该**需要改设备固件

## 最后一条最重要

**如果你发现某个功能需要改固件才能实现，先想一想是不是设计错了。**

固件只该做三件事：连 Wi-Fi、解码显示、上报原始输入。业务逻辑全在 petd。想在固件里加「状态判断」或「中文渲染」，说明逻辑放错地方了。
