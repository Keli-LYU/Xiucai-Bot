"""QQ 机器人：HelloWorld、战场查询和随机秀才图片。"""

import logging
import os
import html
import re
from pathlib import Path

import botpy
from botpy.message import C2CMessage, GroupMessage, Message
from dotenv import load_dotenv
from botpy.http import Route

from markdown_images import MarkdownImageStore
from pvp import get_today_battlefield, parse_command, resolve_image_path
from plans import Plan, PlanManager, display_plan_time, parse_plan_time
from replies import ReplySession
from xiucai import choose_xiucai_image



logger = logging.getLogger("hello_bot")


class HelloBot(botpy.Client):
    def __init__(self, *args, xiucai_trigger=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.xiucai_trigger = xiucai_trigger
        self.markdown_images = None
        self.plan_manager = PlanManager(self._send_plan_notification)

    async def _bot_login(self, token):
        await super()._bot_login(token)
        # SDK 1.2.1 的群作者模型丢弃昵称；保留官方事件中的用户信息。
        self._connection.parser["group_at_message_create"] = self._parse_named_group_message

    def _parse_named_group_message(self, payload):
        data = payload.get("d", {})
        message = GroupMessage(self.api, payload.get("id"), data)
        author = data.get("author", {})
        message.author.username = author.get("username")
        message.author.bot = author.get("bot", False)
        self.ws_dispatch("group_at_message_create", message)

    async def close(self):
        await self.plan_manager.close()
        await super().close()

    async def on_ready(self):
        logger.info("机器人已上线：%s；等待消息。", self.robot.name)
        try:
            await self.plan_manager.start()
        except (OSError, ValueError, TypeError):
            logger.exception("闹钟记录恢复失败，其他功能继续运行。")

    async def on_c2c_message_create(self, message: C2CMessage):
        """QQ 单聊：收到消息后被动回复。"""
        await self._handle_message(message)

    async def on_group_at_message_create(self, message: GroupMessage):
        """QQ 群聊：被 @ 时回复。"""
        await self._handle_message(message)

    async def on_at_message_create(self, message: Message):
        """QQ 频道：被 @ 时回复。"""
        await self._handle_message(message)

    async def _handle_message(self, message: C2CMessage | GroupMessage | Message):
        if getattr(message.author, "bot", False):
            return
        if self.markdown_images is None:
            self.markdown_images = MarkdownImageStore(self.http)
        replies = ReplySession(self.http, message, self._append_xiucai, self.markdown_images)
        command = parse_command(message.content)
        if command == "/xiucai":
            self.xiucai_trigger = not self.xiucai_trigger
            status = "已开启" if self.xiucai_trigger else "已关闭"
            await replies.text(f"xiucai_trigger：{status}")
        elif command == "/pvp":
            await self._reply_pvp(replies)
        elif command.split()[:1] == ["/plan"]:
            await self._reply_plan(replies, command.split()[1:])

    @staticmethod
    def _display_owner(name):
        # 昵称作为普通文字展示，避免用户名被解释为 Markdown 或 @ 标签。
        escaped = html.escape(" ".join(name.split())[:80])
        return re.sub(r"([\\`*_{}\[\]()#+.!|])", r"\\\1", escaped)

    async def _reply_plan(self, replies: ReplySession, arguments):
        message = replies.message
        if not isinstance(message, GroupMessage):
            await replies.text("/plan 仅支持QQ群。")
            return
        if len(arguments) != 1:
            await replies.text("用法：/plan HHMM 设置闹钟，例如 /plan 2400；/plan cancel 取消。时间为北京时间。")
            return
        try:
            if arguments[0].lower() == "cancel":
                old = await self.plan_manager.cancel(message.group_openid)
                text = "已取消当前闹钟。" if old is not None else "当前没有待触发的闹钟。"
            else:
                when = parse_plan_time(arguments[0])
                owner_id = message.author.member_openid or "unknown"
                owner_name = getattr(message.author, "username", None) or f"用户（{owner_id[-6:]}）"
                accepted, plan = await self.plan_manager.set(message.group_openid, owner_id, owner_name, when)
                if accepted:
                    text = f"已设置{display_plan_time(plan.when)} 的闹钟，到点将尝试 @全体成员。"
                else:
                    text = f"{self._display_owner(plan.owner_name)} 已设置{display_plan_time(plan.when)} 的闹钟"
        except ValueError as exc:
            text = str(exc)
        except OSError:
            logger.exception("保存闹钟失败。")
            text = "闹钟保存失败，请稍后再试。"
        await replies.text(text)

    async def _send_active_group_markdown(self, group_openid: str, content: str):
        # 定时通知使用主动消息，不复用设置命令中已过期的 msg_id/event_id。
        result = await self.http.request(
            Route("POST", "/v2/groups/{group_openid}/messages", group_openid=group_openid),
            json={"msg_type": 2, "markdown": {"content": content}},
        )
        if not isinstance(result, dict) or not result.get("id"):
            raise RuntimeError("QQ 未返回主动消息 ID，闹钟通知未确认发送成功。")

    async def _send_plan_notification(self, plan: Plan):
        content = f"<qqbot-at-everyone />\n\n闹钟时间到了：{display_plan_time(plan.when)}"
        await self._send_active_group_markdown(plan.group_openid, content)
        logger.info("闹钟通知已发送：%s %s；@全体效果以 QQ 客户端为准。", plan.group_openid, plan.when)
        if self.xiucai_trigger:
            try:
                if self.markdown_images is None:
                    self.markdown_images = MarkdownImageStore(self.http)
                url = await self.markdown_images.get_url(choose_xiucai_image())
                await self._send_active_group_markdown(plan.group_openid, f"![图片]({url})")
            except Exception:
                logger.exception("闹钟附带的秀才图片发送失败。")

    async def _append_xiucai(self, replies: ReplySession):
        if not self.xiucai_trigger:
            return
        try:
            await replies.image(choose_xiucai_image(), append_xiucai=False)
        except Exception as exc:
            # 附图失败只记日志，不追加错误回复，避免重复触发。
            logger.warning("秀才图片发送失败：%s", exc)

    async def _reply_pvp(self, replies: ReplySession):
        try:
            battle = get_today_battlefield()
            text = (f"今日战场：{battle['name']}\n\n"
                    f"{battle['time_until_rotation']}后轮换至{battle['next_name']}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("读取战场信息失败：%s", exc)
            await replies.text("战场信息暂不可用，请稍后再试。")
            return

        try:
            await replies.image_with_text(resolve_image_path(battle["image"]), text)
        except Exception as exc:
            logger.warning("战场图文发送失败：%s", exc)
            await replies.text(text)


def load_config():
    # 按脚本路径寻找配置，从其他目录启动时也能读取 .env。
    load_dotenv(Path(__file__).with_name(".env"))
    app_id = os.getenv("AppID", "").strip()
    app_secret = os.getenv("AppSecret", "").strip()
    if not app_id or not app_secret:
        raise ValueError("请在 .env 中填写 AppID 和 AppSecret。")
    sandbox = os.getenv("QQ_BOT_SANDBOX", "false").strip().lower()
    if sandbox not in {"true", "false"}:
        raise ValueError("QQ_BOT_SANDBOX 只能为 true 或 false。")
    return app_id, app_secret, sandbox == "true"


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
    )
    try:
        app_id, app_secret, sandbox = load_config()
        client = HelloBot(
            intents=botpy.Intents(public_messages=True, public_guild_messages=True),
            is_sandbox=sandbox,
            timeout=20,
            log_level=logging.INFO,
            ext_handlers=False,
        )
        client.run(appid=app_id, secret=app_secret)
    except Exception as exc:
        logger.error("机器人启动失败（%s）：%s", type(exc).__name__, exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
