"""按北京时间每日 23:00 切换的八日战场轮换。"""

import json
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).resolve().parent / "pvp-info"


class BattlefieldMatchError(ValueError):
    """用户输入未能唯一匹配战场。"""


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


def parse_predict_time(value: str) -> datetime:
    """将查询时间按北京时间的整点解析；小时支持一位或两位数字。"""
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{1,2}", value):
        raise ValueError("格式：/predict yyyy-mm-dd-hh，例如 /predict 2026-10-28-23；时间为北京时间。")
    try:
        year, month, day, hour = map(int, value.split("-"))
        return datetime(year, month, day, hour, tzinfo=BEIJING)
    except ValueError:
        raise ValueError("日期或小时无效，请输入有效日期，小时为 0–23，例如 /predict 2026-10-28-23。") from None


def _load_rotation():
    with (DATA_DIR / "info.json").open(encoding="utf-8-sig") as file:
        info = json.load(file)
    with (DATA_DIR / "rotation.json").open(encoding="utf-8-sig") as file:
        rotation = json.load(file)

    anchor = datetime.fromisoformat(rotation["anchor_time"])
    if anchor.utcoffset() != timedelta(hours=8) or anchor.time().isoformat() != "23:00:00":
        raise ValueError("轮换基准时间必须为北京时间 23:00。")
    order = rotation["order"]
    index = rotation["anchor_index"]
    if (not isinstance(order, list) or not order or type(index) is not int or not 0 <= index < len(order)
            or not isinstance(info, dict) or any(not isinstance(key, str) or key not in info for key in order)):
        raise ValueError("轮换顺序或基准索引无效。")
    return info, anchor, order, index


def match_battlefield(query: str, info: dict) -> str:
    """先精确匹配，再按 name/nickname 子串联想；昵称支持字符串或字符串列表。"""
    def normalize(value):
        return unicodedata.normalize("NFKC", value).strip().casefold()

    query = normalize(query)
    if not query:
        raise BattlefieldMatchError("请输入战场名称或昵称，例如 /predict cf、/predict 草原。")
    exact, partial = [], []
    for key, battle in info.items():
        name = battle.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("战场 name 配置无效。")
        nicknames = battle.get("nickname", [])
        if isinstance(nicknames, str):
            nicknames = [nicknames]
        if not isinstance(nicknames, list) or any(not isinstance(n, str) for n in nicknames):
            raise ValueError("战场 nickname 必须为字符串或字符串列表。")
        terms = [normalize(value) for value in [name, *nicknames] if value.strip()]
        if query in terms:
            exact.append(key)
        elif any(query in term for term in terms):
            partial.append(key)
    matches = exact or partial
    if not matches:
        raise BattlefieldMatchError("未找到匹配战场，请输入部分名称或昵称，例如 /predict cf、/predict 草原。")
    if len(matches) > 1:
        names = "\n".join(info[key]["name"] for key in matches)
        raise BattlefieldMatchError(f"匹配到多个战场，请输入更完整的名称或昵称：\n{names}")
    return matches[0]


def get_next_battlefield_rotation(query: str, now: datetime | None = None) -> dict:
    """查询严格晚于当前时刻的下一次轮换入场时间，即使该战场正在进行。"""
    now = now if now is not None else datetime.now(BEIJING)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("战场查询时间必须包含时区。")
    info, anchor, order, index = _load_rotation()
    key = match_battlefield(query, info)
    days = (now.astimezone(BEIJING) - anchor).days
    position = (index + days) % len(order)
    for offset in range(1, len(order) + 1):
        if order[(position + offset) % len(order)] == key:
            try:
                when = anchor + timedelta(days=days + offset)
            except OverflowError:
                raise ValueError("下一次轮换时间超出支持的日期范围。") from None
            return {**info[key], "next_rotation_time": when, "is_current": order[position] == key}
    raise ValueError("该战场未配置到轮换顺序中。")


def get_today_battlefield(now: datetime | None = None) -> dict[str, str]:
    """读取配置并计算当前战场；now 必须带时区，避免依赖主机时区。"""
    now = now if now is not None else datetime.now(BEIJING)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("战场查询时间必须包含时区。")
    info, anchor, order, index = _load_rotation()
    # timedelta.days 向下取整，因此基准之前的日期也能正确逆推。
    elapsed = now.astimezone(BEIJING) - anchor
    days = elapsed.days
    position = (index + days) % len(order)
    battle = info[order[position]]
    next_name = info[order[(position + 1) % len(order)]]["name"]
    if not all(isinstance(battle.get(key), str) and battle[key].strip() for key in ("name", "image")):
        raise ValueError("战场信息必须包含非空的 name 和 image。")
    if not isinstance(next_name, str) or not next_name.strip():
        raise ValueError("下一战场必须包含非空的 name。")
    # 向上取整，切换前不足一秒时显示 1 秒；23:00 整点已进入新轮次。
    # 用时长计算，避免查询 9999-12-31 时构造下一天而溢出。
    seconds = math.ceil((timedelta(days=days + 1) - elapsed).total_seconds())
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    countdown = f"{hours}小时" if hours else ""
    if hours or minutes:
        countdown += f"{minutes}分钟"
    countdown += f"{seconds}秒"
    return {**battle, "next_name": next_name, "time_until_rotation": countdown}
