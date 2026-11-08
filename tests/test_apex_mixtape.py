import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import botpy
from botpy.message import C2CMessage, GroupMessage, Message
from PIL import Image

from apex_images import MAX_IMAGE_BYTES, prepare_apex_image
from apex_mixtape import get_mixtape_rotation, parse_mixtape_time
from apex_rank import get_rank_rotation, parse_rank_time
from bot import HelloBot


class MixtapeRotationTests(unittest.TestCase):
    def test_nine_slot_order_boundaries_and_images(self):
        anchor = parse_mixtape_time("26-11-08-20:30")
        expected = ["纪念碑 - 子弹时间", "雷霆堡 - 团队死斗", "制造厂 - 控制",
                    "骷髅镇 - 子弹时间", "碎片镇 - 团队死斗", "晴雨表 - 控制",
                    "沃特森的电塔 - 子弹时间", "骷髅镇 - 团队死斗", "雷霆堡 - 控制"]
        for turn in range(-9, 19):
            with self.subTest(turn=turn):
                when = anchor + timedelta(minutes=15 * turn)
                result = get_mixtape_rotation(when)
                self.assertEqual(result["name"], expected[turn % 9])
                self.assertEqual(result["next_name"], expected[(turn + 1) % 9])
                self.assertEqual(result["time_until_rotation"], "0小时15分钟0秒")
                self.assertTrue(Path(result["image"]).is_file())
                before = get_mixtape_rotation(when - timedelta(microseconds=1))
                self.assertEqual(before["name"], expected[(turn - 1) % 9])
                self.assertEqual(before["time_until_rotation"], "0小时0分钟1秒")

    def test_screenshot_fixed_utc_plus_one(self):
        when = datetime(2026, 11, 8, 13, 30, tzinfo=timezone(timedelta(hours=1)))
        result = get_mixtape_rotation(when)
        self.assertEqual(result["name"], "纪念碑 - 子弹时间")
        self.assertEqual(result["next_name"], "雷霆堡 - 团队死斗")
        self.assertEqual(get_rank_rotation(when)["name"], "风暴点")
        self.assertEqual(get_rank_rotation(when)["time_until_rotation"], "2小时30分钟0秒")

    def test_parser_and_invalid_dates(self):
        self.assertEqual(parse_mixtape_time("26-11-08-20:45"), parse_rank_time("2026-11-08-20:45"))
        for value in ("hello", "26-11-08-24", "26-02-29-20", "26-11-08-20:60"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "/mixtape"):
                parse_mixtape_time(value)
        with self.assertRaises(ValueError):
            get_mixtape_rotation(datetime(2026, 11, 8))


class ApexImageTests(unittest.TestCase):
    def test_large_images_get_cached_copies_and_originals_stay_intact(self):
        root = Path(__file__).resolve().parents[1] / "apex-info/image"
        with tempfile.TemporaryDirectory() as directory:
            for name in ("Fragment East", "Thunderdome"):
                source = root / "Team Deathmatch" / (name + ".jpg")
                original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                result = prepare_apex_image(source, Path(directory))
                self.assertNotEqual(source, result)
                self.assertLessEqual(result.stat().st_size, MAX_IMAGE_BYTES)
                with Image.open(result) as image:
                    self.assertEqual(image.format, "JPEG")
                    self.assertLessEqual(max(image.size), 1600)
                modified = result.stat().st_mtime_ns
                self.assertEqual(prepare_apex_image(source, Path(directory)).stat().st_mtime_ns, modified)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
            small = root / "Gun Run/Monument.jpg"
            self.assertEqual(prepare_apex_image(small, Path(directory)), small)


class ApexCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_text_in_all_chat_types_and_one_followup(self):
        for command in ("/rank 26-11-08-20:45", "/mixtape 26-11-08-20:45", "/mixtape"):
            for message_type, method, payload, endpoint in (
                (GroupMessage, "on_group_at_message_create", {"group_openid": "group"}, "post_group_message"),
                (C2CMessage, "on_c2c_message_create", {"author": {"user_openid": "user"}}, "post_c2c_message"),
                (Message, "on_at_message_create", {"channel_id": "channel"}, None),
            ):
                with self.subTest(command=command, message_type=message_type):
                    client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False, xiucai_trigger=False)
                    client.http = AsyncMock()
                    client.markdown_images = AsyncMock()
                    client.markdown_images.get_url.return_value = "qqbot-media://image/test"
                    api = AsyncMock()
                    message = message_type(api, "event", {"id": "msg", "content": command, **payload})
                    with patch.object(client, "_append_xiucai", new_callable=AsyncMock) as append:
                        await getattr(client, method)(message)
                        append.assert_awaited_once()
                    if endpoint:
                        text = getattr(api, endpoint).await_args.kwargs["markdown"]["content"]
                        self.assertIn("![战场图片 #", text)
                        self.assertIn("后轮换至", text)
                        if "20:45" in command:
                            self.assertIn("2026-11-08 20:45（北京时间）", text)
                    else:
                        client.http.request.assert_awaited_once()

    async def test_usage_and_missing_image_or_upload_fallback(self):
        client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False, xiucai_trigger=False)
        client.http = AsyncMock()
        client.markdown_images = AsyncMock()
        api = AsyncMock()

        async def send(content):
            await client.on_group_at_message_create(GroupMessage(api, "event", {
                "id": "msg", "content": content, "group_openid": "group"}))
            return api.post_group_message.await_args.kwargs["markdown"]["content"]

        self.assertIn("用法：/mixtape", await send("/mixtape a b"))
        self.assertIn("/mixtape", await send("/mixtape invalid"))
        with patch("bot.get_mixtape_rotation", side_effect=ValueError("bad config")):
            self.assertEqual(await send("/mixtape"), "混战地图信息暂不可用，请稍后再试。")
        for command in ("/rank", "/mixtape"):
            with patch("bot.prepare_apex_image", side_effect=FileNotFoundError("missing")):
                text = await send(command)
                self.assertIn("后轮换至", text)
                self.assertNotIn("![", text)
            client.markdown_images.get_url.side_effect = RuntimeError("upload failed")
            text = await send(command)
            self.assertIn("后轮换至", text)
            self.assertNotIn("![", text)
