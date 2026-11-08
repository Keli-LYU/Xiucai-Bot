"""Apex 混战模式轮换，输入和输出均为北京时间。"""

import json
import math
from datetime import datetime, timedelta

from apex_rank import DATA_DIR, parse_rank_time, resolve_apex_image_path
from pvp import BEIJING

USAGE = "用法：/mixtape 查询当前混战地图；/mixtape 地图名称 查询下次轮换，例如 /mixtape 雷霆堡、/mixtape Skull Town；/mixtape yyyy-mm-dd-hh 或 /mixtape yyyy-mm-dd-hh:mm 查询指定时间，年份支持两位简写，例如 /mixtape 26-11-08-20:45。时间为北京时间。"
MODE_NAMES = {"Team Deathmatch": "团队死斗", "Control": "控制", "Gun Run": "子弹时间"}


def parse_mixtape_time(value: str) -> datetime:
    return parse_rank_time(value, usage=USAGE)


def get_mixtape_rotation(when: datetime | None = None) -> dict:
    when = when if when is not None else datetime.now(BEIJING)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("混战查询时间必须包含时区。")
    with (DATA_DIR / "info.json").open(encoding="utf-8-sig") as file:
        info = json.load(file)
    with (DATA_DIR / "mixtape.json").open(encoding="utf-8-sig") as file:
        config = json.load(file)
    anchor = datetime.fromisoformat(config["anchor_time"])
    order, index, minutes = config["order"], config["anchor_index"], config["interval_minutes"]
    if (anchor.utcoffset() != timedelta(hours=8) or not isinstance(order, list) or not order
            or type(index) is not int or not 0 <= index < len(order)
            or type(minutes) is not int or minutes <= 0 or not isinstance(info, dict)):
        raise ValueError("混战轮换配置无效。")
    for entry in order:
        if (not isinstance(entry, dict) or entry.get("map") not in info
                or entry.get("mode") not in MODE_NAMES
                or not isinstance(entry.get("image"), str) or not entry["image"].strip()
                or not isinstance(info[entry["map"]], dict)
                or not isinstance(info[entry["map"]].get("zh-CN"), str)):
            raise ValueError("混战地图配置无效。")
    elapsed = when.astimezone(BEIJING) - anchor
    interval = timedelta(minutes=minutes)
    turns = elapsed // interval
    position = (index + turns) % len(order)
    seconds = math.ceil(((turns + 1) * interval - elapsed).total_seconds())
    hours, seconds = divmod(seconds, 3600)
    mins, seconds = divmod(seconds, 60)

    def label(entry):
        return f"{info[entry['map']]['zh-CN']} - {MODE_NAMES[entry['mode']]}"

    entry = order[position]
    return {"name": label(entry), "next_name": label(order[(position + 1) % len(order)]),
            "time_until_rotation": f"{hours}小时{mins}分钟{seconds}秒",
            "image": str(resolve_apex_image_path(entry["image"]))}
