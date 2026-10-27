# QQ HelloWorld 机器人

使用 QQ 官方 Python SDK `qq-botpy`，通过 WebSocket 接收事件，无需公网回调地址。

## 已实现

- 群聊/频道中 `@机器人` 使用命令，单聊直接发送命令；未知命令不回复。
- `/pvp`：返回对应战场图片、`今日战场：名称` 及下一轮换倒计时。
- `/xiucai`：切换 `xiucai_trigger`，回复 `xiucai_trigger：已开启` 或 `xiucai_trigger：已关闭`。群聊/频道中需 `@机器人`，单聊直接发指令。
- `/plan HHMM`：在QQ群设置一次性闹钟；`/plan cancel` 取消本群当前闹钟。

## 群闹钟

在 QQ 群中发送 `@机器人 /plan 2400`，设置 **北京时间今晚 24:00（次日 00:00）** 的闹钟。
时间使用四位 `HHMM`，例如 `2330`；`2400` 和 `0000` 均表示下一次午夜。其他时间若今天已过或恰好等于当前时刻，则设置为次日的该时刻。`2401`、`2360` 等无效时间会被拒绝。

每个群独立保留一个闹钟：

- 没有闹钟时，创建闹钟。
- 新时间严格晚于旧时间，覆盖旧闹钟，原任务取消，设置者更新。
- 新时间更早或相同，保留旧闹钟，并回复 `用户名 已设置时间 的闹钟`。
- `/plan cancel` 取消本群闹钟；任何群成员都可设置、覆盖和取消。

设置者昵称读取 QQ 消息事件；如平台未提供昵称，会使用 `用户（OpenID末六位）` 标识。
记录保存在 `.data/plans.json`，程序重启后恢复尚未到期的闹钟。停机期间已过期的闹钟不会补发，日志会说明；发送失败也不自动重试，以免重复通知全体。
请保持机器人进程在线，定时消息还需平台允许主动发送。

**QQ群 @全体为实测模式**：按你的选择，到点将使用主动 Markdown 消息发送 `<qqbot-at-everyone />` 标签。官方文本交互文档目前仅公开支持文字子频道 @全体，QQ群是否真正提醒所有成员需 QQ 实测，不能仅以消息发送成功判断。不会把普通文字“@全体成员”当作真正提及的替代。
消息发送成功后，如秀才开关开启，仍会追加一张秀才图片。`/plan` 仅支持QQ群，私聊和频道不会创建闹钟。

## 随机秀才图片

`xiucai_trigger` 当前默认开启，是当前机器人进程的全局开关，所有群聊、单聊和频道共享；重启后恢复开启。
开启时，每成功发送一条普通回复，立即从项目根目录的 `秀才/` 文件夹随机挑选一张图片发送；允许连续随机到同一张。
开启状态的确认回复也会附图，关闭状态的确认回复不附图。秀才附图自身不会再次触发，来自机器人的消息也会被忽略。

`/pvp` 的战场图片与名称合并为一条消息。开启秀才时返回「战场图文 → 秀才图」，共两条；关闭秀才时只返回战场图文一条。
每条收到的消息独立分配回复序号，确保图片和文字不会因重复序号被拒绝。

支持 `秀才/` 下的 PNG/JPG/GIF/WebP 文件（不递归子目录）。按原始字节、文件名和格式上传，保留 GIF/WebP 动画；图片须在 5 MB 以内。群聊和单聊的秀才图片使用 Markdown 素材引用发送，复用战场图片的上传与缓存流程；官方素材接口支持 GIF/WebP，动画的实际播放效果以 QQ 客户端为准。
文件夹不存在、无可用图片或附图发送失败时，仅记录日志，正常回复仍保留。

群聊和单聊的普通文字、开关状态及错误提示也统一使用 Markdown，不在内容中添加 @ 或引用用户消息。你提供的 QQ 截图已确认该客户端的 Markdown 回复不会出现普通图片回复的自动 @。频道仍沿用原有文字及 multipart 图片接口，因为频道 Markdown 需要单独开通权限。

## 战场轮换

战场名称和本地图片路径读取 `pvp-info/info.json`，轮换配置位于 `pvp-info/rotation.json`。
按北京时间（UTC+8）每日 **23:00** 切换，与电脑所在时区无关。
`/pvp` 图文内会追加剩余时间及下一战场，例如 `2小时15分钟30秒后轮换至沃刻其特（演习战）`。
倒计时按查询时刻计算，精确到秒；23:00 整点显示新轮次及距下一次切换的 24 小时。

八日顺序：尘封秘岩 → 荣誉野 → 昂萨哈凯尔 → 沃刻其特 → 尘封秘岩 → 周边遗迹群 → 昂萨哈凯尔 → 沃刻其特 → 循环。

以你提供的「当前竞争战、昨天阵地战」为基准：北京时间 **2026-10-22 23:00 至 2026-10-23 22:59:59** 为昂萨哈凯尔（竞争战），2026-10-23 23:00 切换为沃刻其特（演习战）。
`anchor_time` 表示某一轮次的起点，`anchor_index` 是该轮次在 `order` 中从 0 开始的索引；当前设为 6，以区分一个周期内两次出现的竞争战。
配置按每次查询读取，修改图片或名称无需重启。

群聊/单聊使用自定义 Markdown，将图片和 `今日战场：名称` 放在同一条消息中；频道使用 multipart 图文消息。图片上传或图文发送失败时回退为文字，并记录错误日志。
本地战场图片通过 QQ 素材管理上传，获得 `qqbot-media://` 引用，无需公网图片链接；引用按机器人、环境和图片内容缓存在 `.cache/markdown-images.json`，重启后可复用，避免每次查询重复上传。
所有 Markdown 图片引用会读取原图实际宽高，使用 `![说明 #宽px #高px](引用)` 格式，包括战场图、秀才图和闹钟附图；读取尺寸不改写图片，GIF/WebP 保留原格式与动画。
图片已配置为 `pvp-info/image/` 中的五张本地 PNG。例如 `"image": "image/昂萨哈凯尔.png"`，相对路径以 `info.json` 所在目录为基准，也支持绝对路径（Windows 反斜杠在 JSON 中须写为 `\\`，或使用 `/`）。
支持 PNG/JPG，单张不超过 5 MB。群聊/单聊使用本地文件数据上传，频道使用 multipart 文件上传，无需公网图片链接。

运行离线测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 配置

项目的 `.env` 已填写 AppID 和 AppSecret；它已加入 `.gitignore`。
`.env.example` 仅包含配置模板。请勿提交或分享实际 `.env`。

`QQ_BOT_SANDBOX=false` 使用正式环境；若在平台配置的频道沙箱测试，可改为 `true`。
系统环境变量优先于 `.env`。

在 [QQ 开放平台](https://q.qq.com/) 对应机器人的管理页中：

1. 进入「开发基础设置 → 事件订阅与回调地址」，选择 **WebSocket**。
2. 根据测试场景启用群聊、单聊或频道相关消息事件和权限。
3. 在「内部体验号码」中添加测试 QQ，并根据服务范围配置将机器人加入测试群或频道。
4. 若已配置服务器 IP 白名单，需要加入运行本程序的公网 IPv4。

以上平台配置需要在管理端完成，本地代码不会自动修改它们。

## 启动（Windows PowerShell）

支持 Python 3.10–3.12；本地使用 Python 3.12，Ubuntu 22.04 服务器使用 Python 3.10。Pillow 按 Python 版本选择兼容版本。

```powershell
# 首次安装；当前目录已创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 启动，不必激活虚拟环境
.\.venv\Scripts\python.exe bot.py
```

出现「机器人已上线」后，在 QQ 单聊发送 `/pvp`，或在群/频道发送 `@机器人 /pvp`。
预期收到战场图文。按 `Ctrl+C` 停止，未到期的群闹钟会在下次启动后恢复。

若启动失败，请检查 AppID / AppSecret、平台回调方式、网络连接和 IP 白名单。
若上线后没有事件，请检查测试账号、服务范围、对应场景权限和事件订阅。

## 参考

- [QQ 机器人官方接入指南](https://bot.q.qq.com/wiki/)
- [官方 SDK 接入说明](https://bot.q.qq.com/wiki/develop/api-v2/)
- [官方 Python SDK 与示例](https://github.com/tencent-connect/botpy)
- [官方群聊消息与富媒体参数](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)
- [官方本地文件上传参数](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html)
- [官方 Markdown 图文格式](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html)
- [官方 Markdown 本地图片素材管理](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/material-management.html)
- [官方 @能力与适用范围](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html)
- [官方主动消息与被动回复规则](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html)
