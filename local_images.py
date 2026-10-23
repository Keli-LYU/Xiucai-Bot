"""通过 QQ 文件接口上传本地图片，复用 SDK 的鉴权和沙箱配置。"""

import base64
from pathlib import Path

import aiohttp
from botpy.http import BotHttp, Route


IMAGE_MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}


def read_image(path: Path) -> bytes:
    if path.suffix.lower() not in IMAGE_MIME_TYPES:
        raise ValueError("本地图片必须为 PNG、JPG、GIF 或 WebP。")
    # 当前文件接口要求直接上传的文件在 5 MB 以内。
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("本地图片超过 5 MB，请先缩小图片。")
    data = path.read_bytes()
    if not data:
        raise ValueError("本地图片为空。")
    return data


def upload_name(path: Path) -> str:
    return path.name


async def upload_local_image(
    http: BotHttp, path: Path, *, group_openid: str | None = None, openid: str | None = None,
):
    if (group_openid is None) == (openid is None):
        raise ValueError("图片上传必须指定一个群或单聊目标。")
    if group_openid is not None:
        route = Route("POST", "/v2/groups/{group_openid}/files", group_openid=group_openid)
    else:
        route = Route("POST", "/v2/users/{openid}/files", openid=openid)
    # qq-botpy 1.2.1 的文件方法尚无 file_data 参数，复用其 HTTP 客户端。
    return await http.request(route, json={
        "file_type": 1,
        "file_name": upload_name(path),
        "file_data": base64.b64encode(read_image(path)).decode("ascii"),
        "srv_send_msg": False,
    })


async def post_channel_image(http: BotHttp, path: Path, *, channel_id: str, msg_id: str, content: str):
    # 使用标准 FormData，避开 SDK _FormData 与新版 aiohttp 的兼容问题。
    form = aiohttp.FormData()
    form.add_field("content", content)
    form.add_field("msg_id", msg_id)
    name = upload_name(path)
    form.add_field("file_image", read_image(path), filename=name,
                   content_type=IMAGE_MIME_TYPES[path.suffix.lower()])
    route = Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    return await http.request(route, data=form)
