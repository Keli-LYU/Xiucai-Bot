import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import botpy
from botpy.message import C2CMessage, GroupMessage, Message

from apex_lookup import ApexMapMatchError, get_next_apex_rotation
from apex_mixtape import get_mixtape_rotation
from apex_rank import get_rank_rotation, parse_rank_time
from bot import HelloBot


def next_map(query, when, *, mixtape=False):
    return get_next_apex_rotation(query, when=when,
                                 config_name="mixtape.json" if mixtape else "rotation.json",
                                 lookup=get_mixtape_rotation if mixtape else get_rank_rotation)


class NextMapTests(unittest.TestCase):
    def test_rank_chinese_english_partial_alias_and_current(self):
        now = parse_rank_time("26-11-08-20:30")
        cases = [("风暴点", "26-11-09-08", True), ("Storm Point", "26-11-09-08", True),
                 ("storm", "26-11-09-08", True), ("电力区域", "26-11-08-23", False),
                 ("E District", "26-11-08-23", False), ("残", "26-11-09-03:30", False)]
        for query, expected, current in cases:
            with self.subTest(query=query):
                result = next_map(query, now)
                self.assertEqual(result["next_rotation_time"], parse_rank_time(expected))
                self.assertEqual(result["is_current"], current)
                self.assertTrue(Path(result["image"]).is_file())

    def test_strictly_future_at_boundary_and_subsecond(self):
        boundary = parse_rank_time("26-11-08-23")
        self.assertEqual(next_map("电气区", boundary)["next_rotation_time"], parse_rank_time("26-11-09-12:30"))
        before = boundary - timedelta(microseconds=1)
        self.assertEqual(next_map("电气区", before)["next_rotation_time"], boundary)
        self.assertEqual(next_map("电气区", before.astimezone(timezone.utc))["next_rotation_time"], boundary)

    def test_mixtape_uses_nearest_mode_and_skips_current_slot(self):
        cases = [("雷霆堡", "20:30", "20:45", "团队死斗", False),
                 ("雷霆堡", "20:45", "22:30", "控制", True),
                 ("Skull Town", "20:30", "21:15", "子弹时间", False),
                 ("骷髅镇", "21:15", "22:15", "团队死斗", True),
                 ("纪念碑", "20:30", "22:45", "子弹时间", True)]
        for query, clock, expected, mode, current in cases:
            with self.subTest(query=query, clock=clock):
                result = next_map(query, parse_rank_time("26-11-08-" + clock), mixtape=True)
                self.assertEqual(result["next_rotation_time"], parse_rank_time("26-11-08-" + expected))
                self.assertTrue(result["name"].endswith(mode))
                self.assertEqual(result["is_current"], current)
                self.assertTrue(Path(result["image"]).is_file())
        now = parse_rank_time("26-11-08-23:59")
        self.assertEqual(next_map("Monument", now, mixtape=True)["next_rotation_time"], parse_rank_time("26-11-09-01"))

    def test_mode_pool_no_match_and_ambiguity(self):
        now = parse_rank_time("26-11-08-20:30")
        for query in ("雷霆堡", "不存在", "---", ""):
            with self.subTest(query=query), self.assertRaisesRegex(ApexMapMatchError, "未找到地图"):
                next_map(query, now)
        with self.assertRaisesRegex(ApexMapMatchError, "匹配多项.*碎片镇.*骷髅镇"):
            next_map("镇", now, mixtape=True)
        with self.assertRaises(ValueError):
            next_map("风暴点", datetime(2026, 11, 8))


class NextMapCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_query_combines_image_time_and_one_followup_in_all_chats(self):
        now = parse_rank_time("26-11-08-20:30")
        for command, expected in (("/rank Storm Point", "2026-11-09 08:00"),
                                  ("/mixtape 雷霆堡", "2026-11-08 20:45")):
            for kind, handler, payload, endpoint in (
                (GroupMessage, "on_group_at_message_create", {"group_openid": "group"}, "post_group_message"),
                (C2CMessage, "on_c2c_message_create", {"author": {"user_openid": "user"}}, "post_c2c_message"),
                (Message, "on_at_message_create", {"channel_id": "channel"}, None),
            ):
                with self.subTest(command=command, kind=kind):
                    client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False, xiucai_trigger=False)
                    client.http = AsyncMock()
                    client.markdown_images = AsyncMock()
                    client.markdown_images.get_url.return_value = "qqbot-media://image/test"
                    api = AsyncMock()
                    message = kind(api, "event", {"id": "msg", "content": command, **payload})
                    with patch("apex_lookup.datetime", wraps=datetime) as clock, patch.object(
                            client, "_append_xiucai", new_callable=AsyncMock) as append:
                        clock.now.return_value = now
                        await getattr(client, handler)(message)
                        append.assert_awaited_once()
                    if endpoint:
                        text = getattr(api, endpoint).await_args.kwargs["markdown"]["content"]
                        self.assertIn("![战场图片 #", text)
                        self.assertIn(f"下次轮换：{expected}（北京时间）", text)
                        self.assertEqual("当前正在进行" in text, command.startswith("/rank"))
                    else:
                        client.http.request.assert_awaited_once()

    async def test_name_errors_date_errors_and_image_fallback(self):
        client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False, xiucai_trigger=False)
        client.http = AsyncMock()
        client.markdown_images = AsyncMock()
        api = AsyncMock()

        async def send(command):
            await client.on_group_at_message_create(GroupMessage(api, "event", {
                "id": "msg", "content": command, "group_openid": "group"}))
            return api.post_group_message.await_args.kwargs["markdown"]["content"]

        self.assertIn("未找到地图", await send("/rank 雷霆堡"))
        self.assertIn("匹配多项", await send("/mixtape 镇"))
        self.assertIn("日期或时间无效", await send("/mixtape 26-11-08-24"))
        for command in ("/rank 风暴", "/mixtape 雷霆"):
            with patch("bot.prepare_apex_image", side_effect=FileNotFoundError("missing")):
                text = await send(command)
                self.assertIn("下次轮换：", text)
                self.assertNotIn("![", text)
