import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from markdown_images import MarkdownImageStore


class MarkdownImageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "battle.png"
        self.data = b"\x89PNG\r\n\x1a\nmaterial-fixture"
        self.path.write_bytes(self.data)
        self.cache = Path(self.directory.name) / ".cache" / "images.json"
        self.url = "qqbot-media://image/v1/reference"
        self.http = SimpleNamespace(_token=SimpleNamespace(app_id="bot-one"), is_sandbox=False,
                                    request=AsyncMock())
        self.http.request.side_effect = [
            {"upload_id": "task", "presigned_url": "https://upload.example.com/image"},
            {"url": self.url, "image_id": "image-one", "ttl": 7776000},
        ]
        self.store = MarkdownImageStore(self.http, self.cache)
        self.put_patch = patch("markdown_images.put_image", new_callable=AsyncMock,
                               return_value=hashlib.md5(self.data).hexdigest())
        self.put = self.put_patch.start()
        self.addCleanup(self.put_patch.stop)

    async def test_upload_and_cache_survive_store_restart(self):
        self.assertEqual(await self.store.get_url(self.path), self.url)
        prepare, complete = self.http.request.await_args_list
        self.assertEqual(prepare.args[0].path, "/v2/media-images/prepare")
        self.assertEqual(prepare.kwargs["json"], {
            "file_name": "battle.png", "file_size": len(self.data), "content_type": "image/png",
            "md5": hashlib.md5(self.data).hexdigest(), "sha1": hashlib.sha1(self.data).hexdigest(),
        })
        self.put.assert_awaited_once_with("https://upload.example.com/image", self.data, "image/png")
        self.assertEqual(complete.args[0].path, "/v2/media-images/complete")
        self.assertEqual(complete.kwargs["json"], {"upload_id": "task", "md5": hashlib.md5(self.data).hexdigest()})
        self.assertEqual(await MarkdownImageStore(self.http, self.cache).get_url(self.path), self.url)
        self.assertEqual(self.http.request.await_count, 2)

    async def test_expired_cache_reuploads(self):
        await self.store.get_url(self.path)
        cache = json.loads(self.cache.read_text(encoding="utf-8"))
        for entry in cache.values():
            entry["expires_at"] = 0
        self.cache.write_text(json.dumps(cache), encoding="utf-8")
        self.http.request.side_effect = [
            {"upload_id": "new-task", "presigned_url": "https://upload.example.com/new-image"},
            {"url": "qqbot-media://image/v1/new", "ttl": 7776000},
        ]
        self.assertEqual(await self.store.get_url(self.path), "qqbot-media://image/v1/new")
        self.assertEqual(self.put.await_count, 2)

    async def test_different_bot_cannot_reuse_cached_reference(self):
        await self.store.get_url(self.path)
        self.http._token.app_id = "bot-two"
        self.http.request.side_effect = [
            {"upload_id": "task-two", "presigned_url": "https://upload.example.com/bot-two"},
            {"url": "qqbot-media://image/v1/bot-two", "ttl": 7776000},
        ]
        self.assertEqual(await self.store.get_url(self.path), "qqbot-media://image/v1/bot-two")
        self.assertEqual(self.put.await_count, 2)

    async def test_bad_etag_never_completes_or_caches(self):
        self.put.return_value = "wrong-etag"
        with self.assertRaises(ValueError):
            await self.store.get_url(self.path)
        self.assertEqual(self.http.request.await_count, 1)
        self.assertFalse(self.cache.exists())

    async def test_failed_prepare_never_uploads(self):
        self.http.request.side_effect = None
        self.http.request.return_value = None
        with self.assertRaises(RuntimeError):
            await self.store.get_url(self.path)
        self.put.assert_not_awaited()

    async def test_gif_and_webp_material_upload_keeps_animated_file_bytes(self):
        for extension in ("gif", "webp"):
            with self.subTest(extension=extension):
                path = self.path.with_suffix(f".{extension}")
                Image.new("RGB", (3, 3), "red").save(
                    path, save_all=True, append_images=[Image.new("RGB", (3, 3), "blue")],
                    duration=100, loop=0,
                )
                data = path.read_bytes()
                md5 = hashlib.md5(data).hexdigest()
                self.put.reset_mock()
                self.put.return_value = md5
                self.http.request.reset_mock()
                self.http.request.side_effect = [
                    {"upload_id": extension, "presigned_url": f"https://upload.example.com/{extension}"},
                    {"url": f"qqbot-media://image/v1/{extension}", "ttl": 7776000},
                ]
                self.assertEqual(await self.store.get_url(path), f"qqbot-media://image/v1/{extension}")
                prepare = self.http.request.await_args_list[0].kwargs["json"]
                self.assertEqual(prepare["file_name"], path.name)
                self.assertEqual(prepare["content_type"], f"image/{extension}")
                self.assertEqual(prepare["file_size"], len(data))
                self.put.assert_awaited_once_with(f"https://upload.example.com/{extension}", data, f"image/{extension}")


if __name__ == "__main__":
    unittest.main()
