import asyncio
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import botpy
from botpy.message import C2CMessage, GroupMessage, Message
from PIL import Image

from bot import HelloBot
from local_images import read_image, upload_name
from xiucai import choose_xiucai_image


class SelectionTests(unittest.TestCase):
    def test_selects_only_image_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes.txt").write_text("ignored")
            (root / "nested.png").mkdir()
            image = root / "photo.GIF"
            image.write_bytes(b"fixture")
            with patch("xiucai.XIUCAI_DIR", root):
                self.assertEqual(choose_xiucai_image(), image)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("xiucai.XIUCAI_DIR", Path(directory)):
                with self.assertRaises(FileNotFoundError):
                    choose_xiucai_image()

    def test_animated_gif_and_webp_keep_original_bytes_and_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            for extension in ("gif", "webp"):
                with self.subTest(extension=extension):
                    path = Path(directory) / f"photo.{extension}"
                    Image.new("RGB", (3, 3), "red").save(
                        path, save_all=True, append_images=[Image.new("RGB", (3, 3), "blue")],
                        duration=100, loop=0,
                    )
                    source = path.read_bytes()
                    uploaded = read_image(path)
                    self.assertEqual(uploaded, source)
                    with Image.open(BytesIO(uploaded)) as result:
                        self.assertEqual(result.format.lower(), extension)
                        self.assertEqual(result.n_frames, 2)
                    self.assertEqual(upload_name(path), path.name)
                    self.assertEqual(path.read_bytes(), source)


class TriggerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = AsyncMock()
        self.http = AsyncMock()
        self.http.request.return_value = {"file_info": "file", "ttl": 300}
        self.client = HelloBot(intents=botpy.Intents(public_messages=True), ext_handlers=False, xiucai_trigger=False)
        self.client.api = self.api
        self.client.http = self.http
        self.client.markdown_images = AsyncMock()
        self.client.markdown_images.get_url.return_value = "qqbot-media://image/v1/battle"
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.picture = Path(self.directory.name) / "random.png"
        Image.new("RGB", (2, 2), "blue").save(self.picture)
        self.choice_patch = patch("bot.choose_xiucai_image", return_value=self.picture)
        self.choice = self.choice_patch.start()
        self.addCleanup(self.choice_patch.stop)
        self.battle_patch = patch("bot.get_today_battlefield", return_value={
            "name": "test", "image": str(self.picture),
            "next_name": "next", "time_until_rotation": "1小时0分钟0秒"})
        self.battle_patch.start()
        self.addCleanup(self.battle_patch.stop)

    def group(self, content="/pvp", msg_id="msg"):
        return GroupMessage(self.api, "event", {
            "id": msg_id, "content": content, "group_openid": "group",
        })

    async def test_disabled_trigger_does_not_append_image(self):
        self.assertFalse(self.client.xiucai_trigger)
        await self.client.on_group_at_message_create(self.group())
        self.choice.assert_not_called()
        self.http.request.assert_not_awaited()
        self.assertEqual(self.api.post_group_message.await_count, 1)

    async def test_toggle_reports_new_state_and_disable_stops_images(self):
        await self.client.on_group_at_message_create(self.group("<@!123> /xiucai", "on"))
        self.assertTrue(self.client.xiucai_trigger)
        first = self.api.post_group_message.await_args_list
        self.assertEqual(first[0].kwargs["markdown"]["content"], "xiucai_trigger：已开启")
        self.assertEqual([call.kwargs["msg_seq"] for call in first], [1, 2])
        self.assertEqual(first[1].kwargs["msg_type"], 2)
        await self.client.on_group_at_message_create(self.group("/xiucai", "off"))
        self.assertFalse(self.client.xiucai_trigger)
        self.assertEqual(self.api.post_group_message.await_args.kwargs["markdown"]["content"], "xiucai_trigger：已关闭")
        self.assertEqual(self.api.post_group_message.await_count, 3)
        self.choice.assert_called_once()

    async def test_enabled_normal_reply_has_exactly_one_followup(self):
        self.client.xiucai_trigger = True
        await self.client.on_group_at_message_create(self.group())
        calls = self.api.post_group_message.await_args_list
        self.assertEqual([call.kwargs["msg_type"] for call in calls], [2, 2])
        self.assertEqual([call.kwargs["msg_seq"] for call in calls], [1, 2])
        self.choice.assert_called_once()
        self.assertEqual(self.client.markdown_images.get_url.await_count, 2)
        self.assertIn("今日战场：test", calls[0].kwargs["markdown"]["content"])
        self.assertEqual(calls[1].kwargs["markdown"]["content"], "![图片 #2px #2px](qqbot-media://image/v1/battle)")
        self.assertTrue(all("content" not in call.kwargs and "media" not in call.kwargs for call in calls))
        self.http.request.assert_not_awaited()

    async def test_gif_followup_uses_markdown_material_reference(self):
        self.client.xiucai_trigger = True
        path = self.picture.with_suffix(".gif")
        Image.new("RGB", (3, 3), "red").save(
            path, save_all=True, append_images=[Image.new("RGB", (3, 3), "blue")],
            duration=100, loop=0,
        )
        self.choice.return_value = path
        await self.client.on_group_at_message_create(self.group())
        self.client.markdown_images.get_url.assert_awaited_with(path)
        reply = self.api.post_group_message.await_args.kwargs
        self.assertEqual(reply["msg_type"], 2)
        self.assertEqual(reply["markdown"]["content"], "![图片 #3px #3px](qqbot-media://image/v1/battle)")
        self.assertNotIn("media", reply)

    async def test_webp_channel_multipart_keeps_original_data_and_type(self):
        self.client.xiucai_trigger = False
        path = self.picture.with_suffix(".webp")
        Image.new("RGB", (3, 3), "red").save(
            path, save_all=True, append_images=[Image.new("RGB", (3, 3), "blue")],
            duration=100, loop=0,
        )
        self.choice.return_value = path
        message = Message(self.api, "event", {
            "id": "channel-msg", "content": "/xiucai", "channel_id": "channel",
        })
        await self.client.on_at_message_create(message)
        writer = AsyncMock()
        await self.http.request.await_args.kwargs["data"]().write(writer)
        body = b"".join(call.args[0] for call in writer.write.await_args_list)
        self.assertIn(b'filename="random.webp"', body)
        self.assertIn(b"Content-Type: image/webp", body)
        self.assertIn(path.read_bytes(), body)

    async def test_combined_pvp_has_one_followup(self):
        self.client.xiucai_trigger = True
        battle = {"name": "test", "image": str(self.picture),
                  "next_name": "next", "time_until_rotation": "1小时0分钟0秒"}
        with patch("bot.get_today_battlefield", return_value=battle):
            await self.client.on_group_at_message_create(self.group("/pvp"))
        calls = self.api.post_group_message.await_args_list
        self.assertEqual([call.kwargs["msg_type"] for call in calls], [2, 2])
        self.assertEqual([call.kwargs["msg_seq"] for call in calls], [1, 2])
        self.assertIn("今日战场：test", calls[0].kwargs["markdown"]["content"])
        self.assertIn("1小时0分钟0秒后轮换至next", calls[0].kwargs["markdown"]["content"])
        self.choice.assert_called_once()

    async def test_c2c_pvp_and_followup_use_two_replies(self):
        self.client.xiucai_trigger = True
        message = C2CMessage(self.api, "event", {
            "id": "c2c", "content": "/pvp", "author": {"user_openid": "user"},
        })
        with patch("bot.get_today_battlefield", return_value={"name": "test", "image": str(self.picture),
                   "next_name": "next", "time_until_rotation": "1小时0分钟0秒"}):
            await self.client.on_c2c_message_create(message)
        calls = self.api.post_c2c_message.await_args_list
        self.assertEqual([call.kwargs["msg_seq"] for call in calls], [1, 2])
        self.assertTrue(all(call.kwargs["openid"] == "user" for call in calls))

    async def test_channel_reply_and_image_do_not_loop(self):
        self.client.xiucai_trigger = False
        message = Message(self.api, "event", {
            "id": "channel-msg", "content": "/xiucai", "channel_id": "channel",
        })
        await self.client.on_at_message_create(message)
        self.api.post_message.assert_awaited_once()
        self.http.request.assert_awaited_once()
        self.choice.assert_called_once()
        message.author.bot = True
        await self.client.on_at_message_create(message)
        self.api.post_message.assert_awaited_once()
        self.http.request.assert_awaited_once()

    async def test_failed_primary_reply_does_not_trigger(self):
        self.client.xiucai_trigger = True
        self.api.post_group_message.side_effect = RuntimeError("send failed")
        with self.assertLogs("hello_bot", level="WARNING"), self.assertRaises(RuntimeError):
            await self.client.on_group_at_message_create(self.group())
        self.choice.assert_not_called()

    async def test_missing_folder_does_not_replace_normal_reply(self):
        self.client.xiucai_trigger = True
        self.choice.side_effect = FileNotFoundError("missing")
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.client.on_group_at_message_create(self.group())
        self.assertEqual(self.api.post_group_message.await_count, 1)
        self.http.request.assert_not_awaited()

    async def test_followup_failure_does_not_emit_another_reply(self):
        self.client.xiucai_trigger = True
        self.client.markdown_images.get_url.side_effect = RuntimeError("upload failed")
        with self.assertLogs("hello_bot", level="WARNING"):
            await self.client.on_group_at_message_create(self.group())
        self.assertEqual(self.api.post_group_message.await_count, 1)
        self.choice.assert_called_once()

    async def test_c2c_text_and_picture_both_use_markdown(self):
        self.client.xiucai_trigger = False
        message = C2CMessage(self.api, "event", {
            "id": "c2c", "content": "/xiucai", "author": {"user_openid": "user"},
        })
        await self.client.on_c2c_message_create(message)
        calls = self.api.post_c2c_message.await_args_list
        self.assertEqual([call.kwargs["msg_type"] for call in calls], [2, 2])
        self.assertEqual([call.kwargs["msg_seq"] for call in calls], [1, 2])
        self.assertEqual(calls[0].kwargs["markdown"]["content"], "xiucai_trigger：已开启")
        self.assertTrue(all(call.kwargs["openid"] == "user" and "content" not in call.kwargs for call in calls))

    async def test_concurrent_inbound_messages_have_separate_sequences(self):
        self.client.xiucai_trigger = True
        await asyncio.gather(*(self.client.on_group_at_message_create(self.group(msg_id=msg_id))
                               for msg_id in ("one", "two")))
        for msg_id in ("one", "two"):
            calls = [call for call in self.api.post_group_message.await_args_list
                     if call.kwargs["msg_id"] == msg_id]
            self.assertEqual([call.kwargs["msg_seq"] for call in calls], [1, 2])


if __name__ == "__main__":
    unittest.main()
