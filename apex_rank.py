"""Apex 排位地图轮换，所有输入和显示时间均为北京时间。"""

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from pvp import BEIJING

DATA_DIR = Path(__file__).resolve().parent / "apex-info"
USAGE = "用法：/rank 查询当前排位地图；/rank yyyy-mm-dd-hh 或 /rank yyyy-mm-dd-hh:mm 查询指定时间，年份支持两位简写，例如 /rank 26-11-08-23:30。时间为北京时间。"


def parse_rank_time(value: str, *, usage: str = USAGE) -> datetime:
    if not re.fullmatch(r"(?:[0-9]{2}|[0-9]{4})-[0-9]{2}-[0-9]{2}-[0-9]{1,2}(?::[0-9]{2})?", value):
        raise ValueError(usage)
    try:
        date, clock = value.rsplit("-", 1)
        year, month, day = map(int, date.split("-"))
        if len(date.split("-", 1)[0]) == 2:
            year += 2000
        hour, minute = map(int, (clock if ":" in clock else clock + ":00").split(":"))
        return datetime(year, month, day, hour, minute, tzinfo=BEIJING)
    except ValueError:
        raise ValueError("日期或时间无效。" + usage) from None


def resolve_apex_image_path(value: str) -> Path:
    path = (DATA_DIR / value).resolve()
    if not path.is_relative_to(DATA_DIR.resolve()):
        raise ValueError("Apex 图片路径必须位于 apex-info 目录内。")
    return path


def get_rank_rotation(when: datetime | None = None) -> dict:
    when = when if when is not None else datetime.now(BEIJING)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("排位查询时间必须包含时区。")
    with (DATA_DIR / "info.json").open(encoding="utf-8-sig") as file:
        info = json.load(file)
    with (DATA_DIR / "rotation.json").open(encoding="utf-8-sig") as file:
        config = json.load(file)
    anchor = datetime.fromisoformat(config["anchor_time"])
    order, index, minutes = config["order"], config["anchor_index"], config["interval_minutes"]
    if (anchor.utcoffset() != timedelta(hours=8)
            or not isinstance(order, list) or not order
            or type(index) is not int or not 0 <= index < len(order)
            or type(minutes) is not int or minutes <= 0
            or not isinstance(info, dict)):
        raise ValueError("排位轮换配置无效。")
    for key in order:
        if (not isinstance(key, str) or key not in info or not isinstance(info[key], dict)
                or not isinstance(info[key].get("zh-CN"), str) or not info[key]["zh-CN"].strip()):
            raise ValueError("排位地图名称配置无效。")
    elapsed = when.astimezone(BEIJING) - anchor
    interval = timedelta(minutes=minutes)
    turns = elapsed // interval
    position = (index + turns) % len(order)
    seconds = math.ceil(((turns + 1) * interval - elapsed).total_seconds())
    hours, seconds = divmod(seconds, 3600)
    mins, seconds = divmod(seconds, 60)
    return {
        "name": info[order[position]]["zh-CN"],
        "next_name": info[order[(position + 1) % len(order)]]["zh-CN"],
        "time_until_rotation": f"{hours}小时{mins}分钟{seconds}秒",
        "image": str(resolve_apex_image_path(info[order[position]]["image"])),
    }
