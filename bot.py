"""QQ 机器人：战场查询和随机秀才图片。"""

import logging
import os
from pathlib import Path

import botpy
from botpy.message import C2CMessage, GroupMessage, Message
from dotenv import load_dotenv

from markdown_images import MarkdownImageStore
from pvp import get_today_battlefield, parse_command, resolve_image_path
from replies import ReplySession
from xiucai import choose_xiucai_image


logger = logging.getLogger("hello_bot")


class HelloBot(botpy.Client):
    def __init__(self, *args, xiucai_trigger=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.xiucai_trigger = xiucai_trigger
        self.markdown_images = None

    async def _bot_login(self, token):
        await super()._bot_login(token)
        # SDK 1.2.1 的群作者模型丢弃 bot 标记；保留它以忽略机器人消息。
        self._connection.parser["group_at_message_create"] = self._parse_group_message

    def _parse_group_message(self, payload):
        data = payload.get("d", {})
        message = GroupMessage(self.api, payload.get("id"), data)
        author = data.get("author", {})
        message.author.bot = author.get("bot", False)
        self.ws_dispatch("group_at_message_create", message)

    async def on_ready(self):
        logger.info("机器人已上线：%s；等待消息。", self.robot.name)

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
