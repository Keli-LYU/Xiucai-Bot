"""按当前模式地图池查询下一次入场时间。"""

import json
import re
from datetime import datetime, timedelta

from apex_rank import DATA_DIR
from pvp import BEIJING


class ApexMapMatchError(ValueError):
    """地图名称未匹配或存在歧义，可直接显示给用户。"""


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def get_next_apex_rotation(query: str, *, config_name: str, lookup,
                           when: datetime | None = None) -> dict:
    when = when if when is not None else datetime.now(BEIJING)
    # 复用相应模式的配置验证、图片选择和显示名称。
    lookup(when)
    with (DATA_DIR / "info.json").open(encoding="utf-8-sig") as file:
        info = json.load(file)
    with (DATA_DIR / config_name).open(encoding="utf-8-sig") as file:
        config = json.load(file)
    order = config["order"]
    maps = list(dict.fromkeys(entry if isinstance(entry, str) else entry["map"] for entry in order))
    needle = _normalize(query)
    aliases = {}
    for name in maps:
        entry = info[name]
        nicknames = entry.get("nickname", [])
        if isinstance(nicknames, str):
            nicknames = [nicknames]
        values = [name, entry["zh-CN"], entry.get("zh-TW", ""), *nicknames]
        aliases[name] = [_normalize(value) for value in values if isinstance(value, str) and value.strip()]
    matches = [name for name in maps if needle and needle in aliases[name]]
    if not matches:
        matches = [name for name in maps if needle and any(needle in alias for alias in aliases[name])]
    if not matches:
        names = "、".join(info[name]["zh-CN"] for name in maps)
        raise ApexMapMatchError(f"未找到地图“{query}”。当前模式地图：{names}。")
    if len(matches) > 1:
        names = "、".join(info[name]["zh-CN"] for name in matches)
        raise ApexMapMatchError(f"地图名称匹配多项：{names}，请使用更完整的名称。")
    selected = matches[0]
    anchor = datetime.fromisoformat(config["anchor_time"])
    interval = timedelta(minutes=config["interval_minutes"])
    turns = (when.astimezone(BEIJING) - anchor) // interval
    position = (config["anchor_index"] + turns) % len(order)
    current_entry = order[position]
    current_map = current_entry if isinstance(current_entry, str) else current_entry["map"]
    for offset in range(1, len(order) + 1):
        entry = order[(position + offset) % len(order)]
        name = entry if isinstance(entry, str) else entry["map"]
        if name == selected:
            next_time = anchor + (turns + offset) * interval
            result = lookup(next_time)
            return {**result, "next_rotation_time": next_time,
                    "is_current": current_map == selected}
    raise ValueError("地图不在轮换配置中。")
