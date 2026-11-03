# systemd 部署

petd 装成开机自启的用户级服务。

## 安装

```bash
cd ai-agent-pet
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

mkdir -p ~/.config/petd
cp deploy/petd.env.example ~/.config/petd/petd.env
chmod 600 ~/.config/petd/petd.env
# 编辑 petd.env 填入 gateway token

cp deploy/petd.service ~/.config/systemd/user/petd.service
systemctl --user daemon-reload
systemctl --user enable --now petd
```

## 验证

```bash
systemctl --user status petd
curl -s http://127.0.0.1:18860/admin/api/status
```

## 日志

```bash
journalctl --user -u petd -f
```

## 注意

- 服务监听 `0.0.0.0`（局域网），**petd 本身无鉴权**。只在你信任的局域网里用。
- 要跑在开机自启，需要 `loginctl enable-linger $USER`。
- 端口、渲染质量等改 `petd/data/config.json`，改完 `systemctl --user restart petd`。
