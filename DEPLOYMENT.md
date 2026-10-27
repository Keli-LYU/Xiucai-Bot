# 阿里云部署

目标服务器：`root@121.43.164.152`，Ubuntu 22.04。

运行目录为 `/opt/qq-bot/current`，systemd 服务名为 `qq-bot`，运行用户为 `qqbot`。

当前版本：`20261023T140953Z`，运行环境为 Python 3.10 虚拟环境。
2026-10-23 22:27（北京时间）已确认 QQ 鉴权成功、机器人“秀才”上线并启动心跳，服务为 `enabled / active (running)`。
服务器以 qqbot 用户运行的 60 项测试全部通过，15 张秀才 GIF/WebP 均已通过 SHA-256 校验并保留原格式。
群内实际回复及闹钟的 @全体成员效果仍需在 QQ 客户端验证。

已同步补丁 `dimensions-20261023T172301Z`：战场图、秀才图及闹钟附图的 Markdown 引用均包含实际像素宽高，保留 GIF/WebP 原文件。
本地与服务器端均通过 61 项测试；服务重启后已确认机器人重新上线，代码 SHA-256 与本地一致。手机端显示效果需通过新消息验证。
本次更新前的文件备份：`/opt/qq-bot/admin/before-dimensions-20261023T172301Z.tar.gz`。

## 查看与管理

```bash
ssh root@121.43.164.152
systemctl status qq-bot --no-pager
journalctl -u qq-bot -n 80 --no-pager
journalctl -u qq-bot -f
systemctl restart qq-bot
systemctl stop qq-bot
systemctl start qq-bot
```

服务已配置自动重启与开机启动。停止本机旧实例后再启动服务器实例，避免重复连接和重复闹钟。

## 文件布局

- `/opt/qq-bot/releases/<版本>/`：代码、图片、测试及该版本的 Python 虚拟环境。
- `/opt/qq-bot/current`：当前版本符号链接。
- `/opt/qq-bot/shared/.env`：机器人配置，只有 root 和 qqbot 用户可读。
- `/opt/qq-bot/shared/.data/plans.json`：待触发的群闹钟。
- `/opt/qq-bot/shared/.cache/markdown-images.json`：已上传的 Markdown 图片引用。
- `/etc/systemd/system/qq-bot.service`：进程守护配置。

闹钟和缓存独立于发布版本，代码更新不会覆盖已有记录。修改 `.env` 后执行 `systemctl restart qq-bot`。

## 发布准备

在项目目录运行：

```powershell
.\.venv\Scripts\python.exe deploy/package.py .deploy/qq-bot-<UTC版本号>.tar.gz
```

版本号格式为 `20261023T140953Z`。`.env` 不进入代码包，须通过 SSH 单独上传。
服务器准备阶段执行 `deploy/install.sh prepare <版本号>`，创建虚拟环境并以 qqbot 用户运行测试；通过后执行 `deploy/install.sh activate <版本号>` 激活。
脚本使用 `/opt/qq-bot/incoming/qq-bot-<版本号>.tar.gz` 和同目录下的 `qq-bot-<版本号>.env`。
仅准备新的发布目录，不删除历史版本。正式激活后应检查日志中已出现机器人上线与 WebSocket 心跳。
