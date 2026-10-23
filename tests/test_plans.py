import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import botpy
from botpy.message import C2CMessage, GroupMessage

from bot import HelloBot
from plans import PlanManager, display_plan_time, parse_plan_time
from pvp import BEIJING


class TimeTests(unittest.TestCase):
    def test_2400_and_0000_mean_next_midnight(self):
        now = datetime(2026, 12, 31, 22, tzinfo=BEIJING)
        expected = datetime(2027, 1, 1, tzinfo=BEIJING)
        self.assertEqual(parse_plan_time("2400", now), expected)
        self.assertEqual(parse_plan_time("0000", now), expected)

    def test_future_and_passed_times(self):
        now = datetime(2026, 10, 23, 22, 30, tzinfo=BEIJING)
        self.assertEqual(parse_plan_time("2330", now), now.replace(hour=23, minute=30))
        self.assertEqual(parse_plan_time("2230", now), now + timedelta(days=1))
        self.assertEqual(parse_plan_time("0030", now), datetime(2026, 10, 24, 0, 30, tzinfo=BEIJING))

    def test_host_timezone_does_not_change_target(self):
        now = datetime(2026, 10, 23, 22, tzinfo=BEIJING)
        self.assertEqual(parse_plan_time("2400", now), parse_plan_time("2400", now.astimezone(timezone.utc)))

    def test_invalid_times(self):
        now = datetime(2026, 10, 23, 22, tzinfo=BEIJING)
        for value in ("2401", "2460", "2360", "2500", "1261", "-100", "930", "24:00", "abcd", "２４００"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_plan_time(value, now)
        with self.assertRaises(ValueError):
            parse_plan_time("2400", now.replace(tzinfo=None))


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "plans.json"
        self.now = datetime(2026, 10, 23, 22, tzinfo=BEIJING)
        self.notify = AsyncMock()
        self.manager = PlanManager(self.notify, self.path, now=lambda: self.now)
        self.addAsyncCleanup(self.manager.close)

    async def set_plan(self, time="2330", group="group", name="小明"):
        return await self.manager.set(group, "user", name, parse_plan_time(time, self.now))

    async def test_later_overwrites_earlier_and_equal_preserve_old_owner(self):
        accepted, first = await self.set_plan()
        self.assertTrue(accepted)
        old_task = self.manager.tasks["group"]
        accepted, current = await self.set_plan("2300", name="小红")
        self.assertFalse(accepted)
        self.assertEqual(current, first)
        self.assertEqual(current.owner_name, "小明")
        accepted, current = await self.set_plan("2330", name="小红")
        self.assertFalse(accepted)
        self.assertEqual(current, first)
        accepted, later = await self.set_plan("2400", name="小红")
        self.assertTrue(accepted)
        self.assertGreater(later.when, first.when)
        self.assertEqual(later.owner_name, "小红")
        self.assertIsNot(old_task, self.manager.tasks["group"])
        self.now = first.when
        self.assertFalse(await self.manager._fire(first))
        self.notify.assert_not_awaited()

    async def test_groups_are_independent_and_cancel_does_not_fire(self):
        _, one = await self.set_plan(group="one")
        _, two = await self.set_plan("2400", group="two")
        self.assertEqual(await self.manager.cancel("one"), one)
        self.assertIsNone(await self.manager.cancel("one"))
        self.assertEqual(self.manager.plans, {"two": two})
        self.now = two.when
        self.assertFalse(await self.manager._fire(one))
        self.assertTrue(await self.manager._fire(two))
        self.notify.assert_awaited_once_with(two)

    async def test_future_time_fires_once_and_is_removed_from_disk(self):
        _, plan = await self.set_plan()
        self.assertFalse(await self.manager._fire(plan))
        self.now = plan.when
        self.assertTrue(await self.manager._fire(plan))
        self.assertFalse(await self.manager._fire(plan))
        self.notify.assert_awaited_once_with(plan)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["plans"], [])

    async def test_timer_wakes_and_sends_without_waiting_in_real_time(self):
        triggered = asyncio.Event()

        async def notify(plan):
            triggered.set()

        async def advance(seconds):
            self.now += timedelta(seconds=seconds)

        self.manager.notify = notify
        with patch("plans.asyncio.sleep", side_effect=advance):
            await self.manager.set("group", "user", "小明", self.now + timedelta(seconds=1))
            await asyncio.wait_for(triggered.wait(), timeout=1)
        self.assertEqual(self.manager.plans, {})

    async def test_restart_restores_future_alarm(self):
        _, plan = await self.set_plan()
        await self.manager.close()
        restored = PlanManager(self.notify, self.path, now=lambda: self.now)
        self.addAsyncCleanup(restored.close)
        await restored.start()
        self.assertEqual(restored.plans["group"], plan)
        self.assertEqual(len(restored.tasks), 1)
        await restored.start()
        self.assertEqual(len(restored.tasks), 1)
        self.now = plan.when
        self.assertTrue(await restored._fire(plan))
        self.notify.assert_awaited_once_with(plan)

    async def test_restart_skips_expired_alarm(self):
        _, plan = await self.set_plan()
        await self.manager.close()
        self.now = plan.when + timedelta(minutes=1)
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.manager.start()
        self.assertEqual(self.manager.plans, {})
        self.notify.assert_not_awaited()

    async def test_failed_write_keeps_old_alarm_and_task(self):
        _, plan = await self.set_plan()
        task = self.manager.tasks["group"]
        with patch.object(self.manager, "_save", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                await self.set_plan("2400")
            with self.assertRaises(OSError):
                await self.manager.cancel("group")
        self.assertEqual(self.manager.plans["group"], plan)
        self.assertIs(self.manager.tasks["group"], task)
        self.assertFalse(task.cancelled())

    async def test_send_failure_is_not_retried_or_left_pending(self):
        _, plan = await self.set_plan()
        self.notify.side_effect = RuntimeError("QQ refused")
        self.now = plan.when
        with self.assertRaises(RuntimeError):
            await self.manager._fire(plan)
        self.assertFalse(await self.manager._fire(plan))
        self.notify.assert_awaited_once()

    async def test_corrupted_state_is_not_overwritten(self):
        self.path.write_text("bad json", encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.set_plan()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "bad json")


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = datetime(2026, 10, 23, 22, tzinfo=BEIJING)
        self.api = AsyncMock()
        self.http = AsyncMock()
        self.http.request.return_value = {"id": "sent"}
        self.client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False, xiucai_trigger=False)
        self.client.api = self.api
        self.client.http = self.http
        self.client.markdown_images = AsyncMock()
        self.client.markdown_images.get_url.return_value = "qqbot-media://image/v1/xiucai"
        self.client.plan_manager = PlanManager(self.client._send_plan_notification,
            Path(self.directory.name) / "plans.json", now=lambda: self.now)
        self.addAsyncCleanup(self.client.plan_manager.close)
        self.clock_patch = patch("plans.beijing_now", side_effect=lambda: self.now)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)

    def message(self, content, name="小明", group="group"):
        message = GroupMessage(self.api, "event", {
            "id": "msg", "group_openid": group, "content": content,
            "author": {"member_openid": "user"},
        })
        message.author.username = name
        return message

    def latest_reply(self):
        return self.api.post_group_message.await_args.kwargs["markdown"]["content"]

    async def test_set_conflict_replace_and_cancel_commands(self):
        await self.client.on_group_at_message_create(self.message("/plan 2330"))
        self.assertIn("已设置10月23日 23:30", self.latest_reply())
        await self.client.on_group_at_message_create(self.message("/plan 2300", name="小红"))
        self.assertEqual(self.latest_reply(), "小明 已设置10月23日 23:30（北京时间） 的闹钟")
        await self.client.on_group_at_message_create(self.message("/plan 2330", name="小红"))
        self.assertEqual(self.client.plan_manager.plans["group"].owner_name, "小明")
        await self.client.on_group_at_message_create(self.message("/plan 2400", name="小红"))
        self.assertEqual(self.client.plan_manager.plans["group"].owner_name, "小红")
        self.assertIn("10月24日 00:00", self.latest_reply())
        await self.client.on_group_at_message_create(self.message("/plan cancel"))
        self.assertEqual(self.latest_reply(), "已取消当前闹钟。")
        await self.client.on_group_at_message_create(self.message("/plan cancel"))
        self.assertEqual(self.latest_reply(), "当前没有待触发的闹钟。")

    async def test_invalid_command_does_not_change_existing_alarm(self):
        await self.client.on_group_at_message_create(self.message("/plan 2400"))
        plan = self.client.plan_manager.plans["group"]
        for command in ("/plan", "/plan 2401", "/plan 12:00", "/plan cancel extra"):
            await self.client.on_group_at_message_create(self.message(command))
            self.assertEqual(self.client.plan_manager.plans["group"], plan)

    async def test_alarm_uses_actual_all_tag_without_expired_reply_id(self):
        await self.client.on_group_at_message_create(self.message("/plan 2400"))
        plan = self.client.plan_manager.plans["group"]
        self.now = plan.when
        await self.client.plan_manager._fire(plan)
        self.http.request.assert_awaited_once()
        call = self.http.request.await_args
        self.assertEqual(call.args[0].url, "https://api.sgroup.qq.com/v2/groups/group/messages")
        payload = call.kwargs["json"]
        self.assertEqual(payload["msg_type"], 2)
        self.assertIn("<qqbot-at-everyone />", payload["markdown"]["content"])
        self.assertIn(display_plan_time(plan.when), payload["markdown"]["content"])
        for field in ("msg_id", "event_id", "msg_seq"):
            self.assertNotIn(field, payload)

    async def test_successful_alarm_appends_one_xiucai_when_enabled(self):
        _, plan = await self.client.plan_manager.set("group", "user", "小明", parse_plan_time("2400", self.now))
        self.client.xiucai_trigger = True
        with patch("bot.choose_xiucai_image", return_value=Path("picture.gif")) as choose:
            await self.client._send_plan_notification(plan)
        self.assertEqual(self.http.request.await_count, 2)
        choose.assert_called_once()
        second = self.http.request.await_args.kwargs["json"]["markdown"]["content"]
        self.assertEqual(second, "![图片](qqbot-media://image/v1/xiucai)")

    async def test_failed_alarm_does_not_append_image(self):
        _, plan = await self.client.plan_manager.set("group", "user", "小明", parse_plan_time("2400", self.now))
        self.client.xiucai_trigger = True
        self.http.request.return_value = None
        with patch("bot.choose_xiucai_image") as choose, self.assertRaises(RuntimeError):
            await self.client._send_plan_notification(plan)
        choose.assert_not_called()

    async def test_sdk_parser_preserves_username(self):
        with patch.object(self.client, "ws_dispatch") as dispatch:
            self.client._parse_named_group_message({"id": "event", "d": {
                "id": "msg", "group_openid": "group", "content": "/plan 2400",
                "author": {"member_openid": "user", "username": "小明", "bot": False},
            }})
        event_name, message = dispatch.call_args.args
        self.assertEqual(event_name, "group_at_message_create")
        self.assertEqual(message.author.username, "小明")
        self.assertFalse(message.author.bot)

    async def test_private_chat_has_no_group_alarm(self):
        private = C2CMessage(self.api, "event", {"id": "msg", "content": "/plan 2400",
                                               "author": {"user_openid": "user"}})
        await self.client.on_c2c_message_create(private)
        self.assertEqual(self.api.post_c2c_message.await_args.kwargs["markdown"]["content"], "/plan 仅支持QQ群。")
        self.assertEqual(self.client.plan_manager.plans, {})

    async def test_owner_name_is_escaped_in_conflict_response(self):
        await self.client.on_group_at_message_create(self.message("/plan 2400", name="<qqbot-at-everyone />"))
        await self.client.on_group_at_message_create(self.message("/plan 2300"))
        self.assertNotIn("<qqbot-at-everyone />", self.latest_reply())
        self.assertIn("&lt;qqbot", self.latest_reply())


if __name__ == "__main__":
    unittest.main()
