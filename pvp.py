"""按北京时间每日 23:00 切换的八日战场轮换。"""

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).resolve().parent / "pvp-info"


def resolve_image_path(image: str) -> Path:
    """相对路径以 info.json 所在目录为基准，也支持本地绝对路径。"""
    if image.lower().startswith(("http://", "https://")):
        raise ValueError("image 必须填写本地图片路径。")
    path = Path(image).expanduser()
    return (path if path.is_absolute() else DATA_DIR / path).resolve()


def parse_command(content: str | None) -> str:
    # 频道事件可能保留开头的 <@机器人ID> 或 <@!机器人ID>。
    command = re.sub(r"^(?:\s*<@!?\d+>)*\s*", "", content or "")
    return command.strip()


def is_pvp_command(content: str | None) -> bool:
    return parse_command(content) == "/pvp"


def get_today_battlefield(now: datetime | None = None) -> dict[str, str]:
    """读取配置并计算当前战场；now 必须带时区，避免依赖主机时区。"""
    now = now if now is not None else datetime.now(BEIJING)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("战场查询时间必须包含时区。")
    with (DATA_DIR / "info.json").open(encoding="utf-8-sig") as file:
        info = json.load(file)
    with (DATA_DIR / "rotation.json").open(encoding="utf-8-sig") as file:
        rotation = json.load(file)

    anchor = datetime.fromisoformat(rotation["anchor_time"])
    if anchor.utcoffset() != timedelta(hours=8) or anchor.time().isoformat() != "23:00:00":
        raise ValueError("轮换基准时间必须为北京时间 23:00。")
    order = rotation["order"]
    index = rotation["anchor_index"]
    if not order or type(index) is not int or not 0 <= index < len(order):
        raise ValueError("轮换顺序或基准索引无效。")
    # timedelta.days 向下取整，因此基准之前的日期也能正确逆推。
    days = (now.astimezone(BEIJING) - anchor).days
    position = (index + days) % len(order)
    battle = info[order[position]]
    next_name = info[order[(position + 1) % len(order)]]["name"]
    if not all(isinstance(battle.get(key), str) and battle[key].strip() for key in ("name", "image")):
        raise ValueError("战场信息必须包含非空的 name 和 image。")
    if not isinstance(next_name, str) or not next_name.strip():
        raise ValueError("下一战场必须包含非空的 name。")
    next_rotation = anchor + timedelta(days=days + 1)
    # 向上取整，切换前不足一秒时显示 1 秒；23:00 整点已进入新轮次。
    seconds = math.ceil((next_rotation - now.astimezone(BEIJING)).total_seconds())
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    countdown = f"{hours}小时" if hours else ""
    if hours or minutes:
        countdown += f"{minutes}分钟"
    countdown += f"{seconds}秒"
    return {**battle, "next_name": next_name, "time_until_rotation": countdown}
