"""将本地图片上传为 Markdown 素材，并缓存与机器人绑定的引用。"""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

import aiohttp
from botpy.http import Route

from local_images import IMAGE_MIME_TYPES, read_image


CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "markdown-images.json"
logger = logging.getLogger("hello_bot")


async def put_image(url: str, data: bytes, content_type: str) -> str:
    """预签名地址自行鉴权，此处不携带 QQ 机器人访问凭证。"""
    if not url.startswith("https://"):
        raise ValueError("素材上传地址必须为 HTTPS。")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.put(url, data=data, headers={"Content-Type": content_type},
                                   allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"素材直传失败，HTTP {response.status}。")
                etag = response.headers.get("ETag", "").strip('"')
                if not etag:
                    raise RuntimeError("素材直传没有返回 ETag。")
                return etag
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise RuntimeError(f"素材直传连接失败（{type(exc).__name__}）。") from None


class MarkdownImageStore:
    def __init__(self, http, cache_path: Path = CACHE_PATH):
        self.http = http
        self.cache_path = cache_path
        self.lock = asyncio.Lock()

    async def get_url(self, path: Path) -> str:
        data = read_image(path)
        sha1 = hashlib.sha1(data).hexdigest()
        md5 = hashlib.md5(data).hexdigest()
        content_type = IMAGE_MIME_TYPES[path.suffix.lower()]
        app_id = self.http._token.app_id
        namespace = f"{app_id}:{bool(self.http.is_sandbox)}"
        key = f"{namespace}:{sha1}"
        async with self.lock:
            try:
                cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if not isinstance(cache, dict):
                    cache = {}
            except (OSError, ValueError):
                cache = {}
            entry = cache.get(key, {})
            if (isinstance(entry, dict) and isinstance(entry.get("url"), str)
                    and entry["url"].startswith("qqbot-media://image/")
                    and isinstance(entry.get("expires_at"), (int, float))
                    and entry["expires_at"] > time.time() + 60):
                return entry["url"]

            prepared = await self.http.request(Route("POST", "/v2/media-images/prepare"), json={
                "file_name": path.name, "file_size": len(data), "content_type": content_type,
                "md5": md5, "sha1": sha1,
            })
            if not isinstance(prepared, dict) or not all(prepared.get(k) for k in ("upload_id", "presigned_url")):
                raise RuntimeError("申请 Markdown 图片上传失败。")
            etag = await put_image(prepared["presigned_url"], data, content_type)
            if etag.lower() != md5:
                raise ValueError("Markdown 图片上传后的校验值不一致。")
            completed = await self.http.request(Route("POST", "/v2/media-images/complete"), json={
                "upload_id": prepared["upload_id"], "md5": etag,
            })
            url = completed.get("url") if isinstance(completed, dict) else None
            if not isinstance(url, str) or not url.startswith("qqbot-media://image/"):
                raise RuntimeError("完成上传未返回有效的 Markdown 图片引用。")
            ttl = completed.get("ttl", 7776000)
            if isinstance(ttl, (int, float)) and ttl > 0:
                cache[key] = {"url": url, "image_id": completed.get("image_id"),
                              "expires_at": time.time() + ttl}
                try:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.cache_path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                    temporary.replace(self.cache_path)
                except OSError:
                    logger.warning("Markdown 图片缓存无法写入，下次查询可能需要重新上传。")
            return url
