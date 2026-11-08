import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import botpy
from botpy.message import GroupMessage

from apex_rank import get_rank_rotation, parse_rank_time
from bot import HelloBot


class RankRotationTests(unittest.TestCase):
    def test_short_year_with_optional_minutes_and_full_year_compatibility(self):
        for value in ("26-11-08-23", "26-11-08-23:30", "28-02-29-9:05"):
            with self.subTest(value=value):
                self.assertEqual(parse_rank_time(value), parse_rank_time("20" + value))
        self.assertEqual(parse_rank_time("00-02-29-0").year, 2000)
        self.assertEqual(parse_rank_time("99-12-31-23:59").year, 2099)
        self.assertEqual(parse_rank_time("0026-11-08-23").year, 26)
        for value in ("6-11-08-23", "026-11-08-23", "26-02-29-9", "26-11-08-23:60"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_rank_time(value)

    def test_boundaries_and_cycle(self):
        cases = [
            ("2026-11-08-18:30", "风暴点", "4小时30分钟0秒"),
            ("2026-11-08-22:59", "风暴点", "0小时1分钟0秒"),
            ("2026-11-08-23", "电气区", "4小时30分钟0秒"),
            ("2026-11-09-03:30", "残月", "4小时30分钟0秒"),
            ("2026-11-09-08", "风暴点", "4小时30分钟0秒"),
            ("2026-11-09-12:30", "电气区", "4小时30分钟0秒"),
        ]
        for value, name, countdown in cases:
            with self.subTest(value=value):
                result = get_rank_rotation(parse_rank_time(value))
                self.assertEqual(result["name"], name)
                self.assertEqual(result["time_until_rotation"], countdown)

    def test_timezone_and_subsecond_boundary(self):
        result = get_rank_rotation(datetime(2026, 11, 8, 15, tzinfo=timezone.utc))
        self.assertEqual(result["name"], "电气区")
        when = parse_rank_time("2026-11-08-22:59").replace(second=59, microsecond=999999)
        self.assertEqual(get_rank_rotation(when)["time_until_rotation"], "0小时0分钟1秒")

    def test_invalid_times(self):
        for value in ("2026-11-08-24", "2026-02-30-11", "2026-11-08-23:60", "hello"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_rank_time(value)
        with self.assertRaises(ValueError):
            get_rank_rotation(datetime(2026, 11, 8))


class RankCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_specified_invalid_and_xiucai(self):
        client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False,
                          xiucai_trigger=False)
        client.http = AsyncMock()
        client.markdown_images = AsyncMock()
        api = AsyncMock()

        async def send(content):
            message = GroupMessage(api, "event", {
                "id": "msg", "content": content, "group_openid": "group"})
            await client.on_group_at_message_create(message)
            return api.post_group_message.await_args.kwargs["markdown"]["content"]

        result = {"name": "风暴点", "next_name": "电气区", "time_until_rotation": "1小时0分钟0秒",
                  "image": get_rank_rotation(parse_rank_time("26-11-08-20"))["image"]}
        with patch("bot.get_rank_rotation", return_value=result) as query:
            self.assertIn("当前排位地图：风暴点", await send("<@!123> /rank"))
            query.assert_called_once_with(None)
            self.assertIn("![战场图片 #", api.post_group_message.await_args.kwargs["markdown"]["content"])
        self.assertIn("此时排位地图：残月", await send("/rank 2026-11-09-03:30"))
        self.assertIn("查询时间：2026-11-09 03:30（北京时间）", await send("/rank 26-11-09-03:30"))
        self.assertIn("日期或时间无效", await send("/rank 2026-11-08-24"))
        self.assertIn("用法：/rank", await send("/rank a b"))
        with patch.object(client, "_append_xiucai", new_callable=AsyncMock) as append:
            await send("/rank")
            append.assert_awaited_once()
        with patch("bot.get_rank_rotation", side_effect=ValueError("bad config")):
            self.assertEqual(await send("/rank"), "排位地图信息暂不可用，请稍后再试。")
