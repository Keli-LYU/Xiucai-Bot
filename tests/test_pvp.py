import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import botpy
from botpy.message import C2CMessage, GroupMessage, Message
from PIL import Image

from bot import HelloBot
from local_images import read_image
from pvp import BEIJING, DATA_DIR, get_today_battlefield, is_pvp_command, parse_predict_time, resolve_image_path


class RotationTests(unittest.TestCase):
    def test_predict_parses_beijing_hour_and_leap_day(self):
        self.assertEqual(parse_predict_time("2028-02-29-9"), datetime(2028, 2, 29, 9, tzinfo=BEIJING))
        self.assertEqual(parse_predict_time("2028-02-29-09"), parse_predict_time("2028-02-29-9"))
        self.assertEqual(parse_predict_time("2026-10-28-00").astimezone(timezone.utc),
                         datetime(2026, 10, 27, 16, tzinfo=timezone.utc))

    def test_predict_rejects_invalid_dates_hours_and_formats(self):
        for value in ("2026-02-29-9", "2026-04-31-9", "2026-10-28-24", "0000-01-01-0",
                      "2026-13-01-9", "2026-10-28--1", "2026-1-01-9", "2026-10-28",
                      "2026-10-28-09:00", "２０２６-10-28-9"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_predict_time(value)

    def test_predict_supported_date_endpoints_do_not_overflow(self):
        for value in ("0001-01-01-0", "9999-12-31-22", "9999-12-31-23"):
            with self.subTest(value=value):
                battle = get_today_battlefield(parse_predict_time(value))
                self.assertTrue(battle["name"])
                self.assertIn(battle["time_until_rotation"], ("1小时0分钟0秒", "23小时0分钟0秒", "24小时0分钟0秒"))

    def test_configured_local_images_exist(self):
        info = json.loads((DATA_DIR / "info.json").read_text(encoding="utf-8-sig"))
        for battle in info.values():
            with self.subTest(name=battle["name"]):
                path = resolve_image_path(battle["image"])
                self.assertEqual(path.parent, DATA_DIR / "image")
                self.assertTrue(read_image(path).startswith(b"\x89PNG\r\n\x1a\n"))

    def test_local_path_resolution(self):
        self.assertEqual(resolve_image_path("image/test.png"), DATA_DIR / "image" / "test.png")
        absolute = DATA_DIR / "image" / "test.png"
        self.assertEqual(resolve_image_path(str(absolute)), absolute)
        with self.assertRaises(ValueError):
            resolve_image_path("https://example.com/image.png")

    def test_anchor_and_daily_boundary(self):
        cases = {
            "2026-10-22T22:59:59+08:00": "周边遗迹群（阵地战）",
            "2026-10-22T23:00:00+08:00": "昂萨哈凯尔（竞争战）",
            "2026-10-23T00:00:00+08:00": "昂萨哈凯尔（竞争战）",
            "2026-10-23T22:59:59.999999+08:00": "昂萨哈凯尔（竞争战）",
            "2026-10-23T23:00:00+08:00": "沃刻其特（演习战）",
            "2026-10-24T23:00:00+08:00": "尘封秘岩（争夺战）",
        }
        for timestamp, expected in cases.items():
            with self.subTest(timestamp=timestamp):
                self.assertEqual(get_today_battlefield(datetime.fromisoformat(timestamp))["name"], expected)

    def test_full_cycle_and_negative_offsets(self):
        anchor = datetime(2026, 10, 22, 23, tzinfo=BEIJING)
        names = ["昂萨哈凯尔（竞争战）", "沃刻其特（演习战）", "尘封秘岩（争夺战）",
                 "荣誉野（碎冰战）", "昂萨哈凯尔（竞争战）", "沃刻其特（演习战）",
                 "尘封秘岩（争夺战）", "周边遗迹群（阵地战）"]
        for offset in range(-16, 17):
            with self.subTest(offset=offset):
                battle = get_today_battlefield(anchor + timedelta(days=offset))
                self.assertEqual(battle["name"], names[offset % 8])
                self.assertEqual(battle["next_name"], names[(offset + 1) % 8])
                self.assertEqual(battle["time_until_rotation"], "24小时0分钟0秒")

    def test_countdown_and_next_battle_at_rotation_boundary(self):
        cases = [
            ("2026-10-22T22:59:59+08:00", "1秒", "昂萨哈凯尔（竞争战）"),
            ("2026-10-23T20:44:30+08:00", "2小时15分钟30秒", "沃刻其特（演习战）"),
            ("2026-10-23T22:30:00+08:00", "30分钟0秒", "沃刻其特（演习战）"),
            ("2026-10-23T22:59:59.999999+08:00", "1秒", "沃刻其特（演习战）"),
            ("2026-10-23T23:00:00+08:00", "24小时0分钟0秒", "尘封秘岩（争夺战）"),
            ("2026-10-24T00:00:00+08:00", "23小时0分钟0秒", "尘封秘岩（争夺战）"),
        ]
        for timestamp, remaining, next_name in cases:
            with self.subTest(timestamp=timestamp):
                battle = get_today_battlefield(datetime.fromisoformat(timestamp))
                self.assertEqual(battle["time_until_rotation"], remaining)
                self.assertEqual(battle["next_name"], next_name)

    def test_same_instant_in_other_timezones(self):
        now = datetime(2026, 10, 23, 23, tzinfo=BEIJING)
        for tz in (timezone.utc, timezone(timedelta(hours=2)), timezone(timedelta(hours=-7))):
            self.assertEqual(get_today_battlefield(now), get_today_battlefield(now.astimezone(tz)))

    def test_rejects_naive_time(self):
        with self.assertRaises(ValueError):
            get_today_battlefield(datetime(2026, 10, 23))

    def test_command_matching(self):
        for text in ("/pvp", " /pvp\n", "<@123> /pvp", "<@!123>/pvp"):
            self.assertTrue(is_pvp_command(text), text)
        for text in (None, "hello", "/pvpx", "/pvp tomorrow", "hello /pvp", "<@123> hello"):
            self.assertFalse(is_pvp_command(text), text)


class ReplyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = AsyncMock()
        self.http = AsyncMock()
        self.http.request.return_value = {"file_info": "group-file", "ttl": 300}
        self.client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False, xiucai_trigger=False)
        self.client.api = self.api
        self.client.http = self.http
        self.client.markdown_images = AsyncMock()
        self.client.markdown_images.get_url.return_value = "qqbot-media://image/v1/battle"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.image_path = Path(self.temp_dir.name) / "test.png"
        Image.new("RGB", (800, 250), "blue").save(self.image_path)
        self.image_data = self.image_path.read_bytes()
        self.battle = {"name": "昂萨哈凯尔（竞争战）", "image": str(self.image_path),
                       "next_name": "沃刻其特（演习战）", "time_until_rotation": "2小时15分钟30秒"}
        self.reply_text = "今日战场：昂萨哈凯尔（竞争战）\n\n2小时15分钟30秒后轮换至沃刻其特（演习战）"
        self.group = GroupMessage(self.api, "event", {"id": "msg", "content": "/pvp", "group_openid": "group"})
        self.c2c = C2CMessage(self.api, "event", {"id": "msg", "content": "/pvp", "author": {"user_openid": "user"}})
        self.channel = Message(self.api, "event", {"id": "msg", "content": "<@!123> /pvp", "channel_id": "channel"})
        self.config_patch = patch("bot.get_today_battlefield", return_value=self.battle)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    async def test_group_combines_image_and_text_in_one_markdown(self):
        await self.client.on_group_at_message_create(self.group)
        self.client.markdown_images.get_url.assert_awaited_once_with(self.image_path)
        self.api.post_group_message.assert_awaited_once_with(
            group_openid="group", msg_id="msg", msg_type=2, msg_seq=1,
            markdown={"content": f"![战场图片 #800px #250px](qqbot-media://image/v1/battle)\n\n{self.reply_text}",
                      "force_verify_image_resource": True},
        )
        self.http.request.assert_not_awaited()

    async def test_predict_group_uses_requested_hour_and_rotation_boundary(self):
        for hour, name, next_name, remaining in (
                (22, "昂萨哈凯尔（竞争战）", "沃刻其特（演习战）", "1小时0分钟0秒"),
                (23, "沃刻其特（演习战）", "尘封秘岩（争夺战）", "24小时0分钟0秒")):
            with self.subTest(hour=hour):
                self.api.post_group_message.reset_mock()
                self.group.content = f"<@!123> /predict 2026-10-23-{hour}"
                def battle_at(when):
                    return {**get_today_battlefield(when), "image": str(self.image_path)}
                with patch("bot.get_today_battlefield", side_effect=battle_at) as lookup:
                    await self.client.on_group_at_message_create(self.group)
                lookup.assert_called_once_with(datetime(2026, 10, 23, hour, tzinfo=BEIJING))
                content = self.api.post_group_message.await_args.kwargs["markdown"]["content"]
                self.assertIn(f"查询时间：2026-10-23 {hour}:00（北京时间）", content)
                self.assertIn(f"此时战场：{name}", content)
                self.assertIn(f"{remaining}后轮换至{next_name}", content)
                self.assertIn("![战场图片 #800px #250px]", content)
                self.api.post_group_message.assert_awaited_once()

    async def test_predict_private_reply_and_image_failure_keep_query_time(self):
        self.c2c.content = "/predict 2028-02-29-9"
        self.client.markdown_images.get_url.side_effect = RuntimeError("image unavailable")
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.client.on_c2c_message_create(self.c2c)
        reply = self.api.post_c2c_message.await_args.kwargs
        self.assertIn("查询时间：2028-02-29 09:00（北京时间）", reply["markdown"]["content"])
        self.assertIn(f"此时战场：{self.battle['name']}", reply["markdown"]["content"])
        self.assertEqual(reply["msg_seq"], 2)

    async def test_invalid_predict_never_loads_battlefield_or_image(self):
        for command in ("/predict", "/predict 2026-10-28-23 extra", "/predict 2026-02-29-9", "/predict 2026-10-28-24"):
            with self.subTest(command=command):
                self.api.post_group_message.reset_mock()
                self.group.content = command
                with patch("bot.get_today_battlefield") as lookup:
                    await self.client.on_group_at_message_create(self.group)
                lookup.assert_not_called()
                self.client.markdown_images.get_url.assert_not_awaited()
                self.api.post_group_message.assert_awaited_once()
                self.assertIn("/predict", self.api.post_group_message.await_args.kwargs["markdown"]["content"])

    async def test_c2c_combines_image_and_text(self):
        await self.client.on_c2c_message_create(self.c2c)
        self.api.post_c2c_message.assert_awaited_once()
        reply = self.api.post_c2c_message.await_args.kwargs
        self.assertEqual((reply["openid"], reply["msg_id"], reply["msg_type"], reply["msg_seq"]),
                         ("user", "msg", 2, 1))
        self.assertIn("今日战场：昂萨哈凯尔（竞争战）", reply["markdown"]["content"])
        self.assertIn("2小时15分钟30秒后轮换至沃刻其特（演习战）", reply["markdown"]["content"])
        self.assertIn("qqbot-media://image/v1/battle", reply["markdown"]["content"])
        self.assertIn("![战场图片 #800px #250px]", reply["markdown"]["content"])

    async def test_channel_combines_image_and_text(self):
        await self.client.on_at_message_create(self.channel)
        self.http.request.assert_awaited_once()
        upload = self.http.request.await_args
        self.assertEqual(upload.args[0].url, "https://api.sgroup.qq.com/channels/channel/messages")
        # 实际序列化 multipart，能发现 SDK 与新版 aiohttp 的表单兼容问题。
        writer = AsyncMock()
        await upload.kwargs["data"]().write(writer)
        body = b"".join(call.args[0] for call in writer.write.await_args_list)
        self.assertIn(b'name="file_image"; filename="test.png"', body)
        self.assertIn(self.image_data, body)
        self.assertIn("今日战场：昂萨哈凯尔（竞争战）".encode("utf-8"), body)
        self.assertIn("2小时15分钟30秒后轮换至沃刻其特（演习战）".encode("utf-8"), body)
        self.assertIn(b'name="msg_id"\r\n\r\nmsg', body)
        self.api.post_message.assert_not_awaited()

    async def test_upload_failure_still_sends_name(self):
        self.client.markdown_images.get_url.side_effect = RuntimeError("image unavailable")
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.client.on_group_at_message_create(self.group)
        self.api.post_group_message.assert_awaited_once_with(group_openid="group", msg_id="msg",
            markdown={"content": self.reply_text}, msg_type=2, msg_seq=2)

    async def test_missing_upload_result_still_sends_name(self):
        self.client.markdown_images.get_url.side_effect = RuntimeError("missing material result")
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.client.on_group_at_message_create(self.group)
        self.assertEqual(self.api.post_group_message.await_count, 1)
        self.assertEqual(self.api.post_group_message.await_args.kwargs["msg_type"], 2)

    async def test_media_send_failure_still_sends_name(self):
        self.api.post_group_message.side_effect = [RuntimeError("send failed"), {"id": "reply"}]
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.client.on_group_at_message_create(self.group)
        self.assertEqual(self.api.post_group_message.await_args_list[-1].kwargs["msg_seq"], 2)

    async def test_invalid_config_gets_explicit_error(self):
        with patch("bot.get_today_battlefield", side_effect=ValueError("invalid JSON")):
            with self.assertLogs("hello_bot", level="ERROR"):
                await self.client.on_group_at_message_create(self.group)
        self.http.request.assert_not_awaited()
        self.api.post_group_message.assert_awaited_once_with(group_openid="group", msg_id="msg",
            markdown={"content": "战场信息暂不可用，请稍后再试。"}, msg_type=2, msg_seq=1)

    async def test_unknown_command_does_not_reply(self):
        self.group.content = "/pvpx"
        await self.client.on_group_at_message_create(self.group)
        self.http.request.assert_not_awaited()
        self.api.post_group_message.assert_not_awaited()

    async def test_missing_local_image_still_sends_name(self):
        self.image_path.unlink()
        self.client.markdown_images = None
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.client.on_group_at_message_create(self.group)
        self.http.request.assert_not_awaited()
        self.api.post_group_message.assert_awaited_once_with(group_openid="group", msg_id="msg",
            markdown={"content": self.reply_text}, msg_type=2, msg_seq=2)


if __name__ == "__main__":
    unittest.main()
