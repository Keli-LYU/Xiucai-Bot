"""为一次收到的消息管理回复顺序，并在回复成功后运行附加功能。"""

from pathlib import Path

from botpy.message import GroupMessage, Message

from local_images import post_channel_image
from markdown_images import MarkdownImageStore, format_markdown_image


class ReplySession:
    def __init__(self, http, message, after_send=None, image_store=None):
        self.http = http
        self.message = message
        self.after_send = after_send
        self.next_seq = 1
        self.image_store = image_store if image_store is not None else MarkdownImageStore(http)

    def _reserve_sequence(self):
        if isinstance(self.message, Message):
            return {}
        # 单聊最多回复 4 次，群聊最多 5 次。
        limit = 5 if isinstance(self.message, GroupMessage) else 4
        if self.next_seq > limit:
            raise RuntimeError("本条消息的回复次数已用完。")
        sequence = self.next_seq
        self.next_seq += 1
        return {"msg_seq": sequence}

    async def _finished(self, result, append_xiucai):
        if result is None:
            raise RuntimeError("QQ 接口未返回发送结果。")
        if append_xiucai and self.after_send is not None:
            await self.after_send(self)

    async def text(self, content: str, *, append_xiucai=True):
        options = self._reserve_sequence()
        if isinstance(self.message, Message):
            result = await self.message.reply(content=content, **options)
        else:
            result = await self.message.reply(msg_type=2, markdown={"content": content}, **options)
        await self._finished(result, append_xiucai)

    async def image(self, path: Path, *, content=" ", append_xiucai=True, alt_text="图片"):
        options = self._reserve_sequence()
        if isinstance(self.message, Message):
            result = await post_channel_image(
                self.http, path, channel_id=self.message.channel_id,
                msg_id=self.message.id, content=content,
            )
        else:
            url = await self.image_store.get_url(path)
            markdown_content = format_markdown_image(path, url, alt_text)
            if content.strip():
                markdown_content += f"\n\n{content}"
            result = await self.message.reply(
                msg_type=2,
                markdown={"content": markdown_content, "force_verify_image_resource": True},
                **options,
            )
        await self._finished(result, append_xiucai)

    async def image_with_text(self, path: Path, content: str):
        await self.image(path, content=content, alt_text="战场图片")
