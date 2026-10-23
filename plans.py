"""每个 QQ 群一个闹钟，按北京时间计时并持久化待触发记录。"""

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pvp import BEIJING


STATE_PATH = Path(__file__).resolve().parent / ".data" / "plans.json"
logger = logging.getLogger("hello_bot")


def beijing_now() -> datetime:
    return datetime.now(BEIJING)


def parse_plan_time(value: str, now: datetime | None = None) -> datetime:
    now = now if now is not None else beijing_now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("闹钟时间必须包含时区。")
    now = now.astimezone(BEIJING)
    if not re.fullmatch(r"[0-9]{4}", value):
        raise ValueError("时间格式为四位 HHMM，例如 /plan 2330 或 /plan 2400。")
    hour, minute = int(value[:2]), int(value[2:])
    if hour > 24 or minute > 59 or (hour == 24 and minute != 0):
        raise ValueError("时间无效：小时为 00–23，分钟为 00–59，另支持 2400。")
    if hour == 24:
        return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def display_plan_time(when: datetime) -> str:
    return when.astimezone(BEIJING).strftime("%m月%d日 %H:%M（北京时间）")


@dataclass(frozen=True)
class Plan:
    group_openid: str
    owner_id: str
    owner_name: str
    when: datetime
    token: str

    def serialize(self):
        return {**asdict(self), "when": self.when.isoformat()}

    @classmethod
    def deserialize(cls, data):
        if not isinstance(data, dict):
            raise ValueError("闹钟记录必须为对象。")
        for field in ("group_openid", "owner_id", "owner_name", "when", "token"):
            if not isinstance(data.get(field), str) or not data[field]:
                raise ValueError(f"闹钟记录缺少 {field}。")
        when = datetime.fromisoformat(data["when"])
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("保存的闹钟缺少时区。")
        return cls(data["group_openid"], data["owner_id"], data["owner_name"],
                   when.astimezone(BEIJING), data["token"])


class PlanManager:
    def __init__(self, notify, state_path: Path = STATE_PATH, now=beijing_now):
        self.notify = notify
        self.state_path = state_path
        self.now = now
        self.plans: dict[str, Plan] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()
        self.started = False

    def _save(self, plans):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "plans": [p.serialize() for p in plans.values()]},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    async def start(self):
        async with self.lock:
            if self.started:
                return
            restored = {}
            expired = False
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("plans"), list):
                    raise ValueError("闹钟状态文件格式无效。")
                for item in data["plans"]:
                    plan = Plan.deserialize(item)
                    if plan.when > self.now():
                        restored[plan.group_openid] = plan
                    else:
                        expired = True
                        logger.warning("跳过停机期间已过期的闹钟：%s %s", plan.group_openid, plan.when)
            if expired:
                self._save(restored)
            self.plans = restored
            self.started = True
            for plan in restored.values():
                self._schedule(plan)

    def _schedule(self, plan):
        task = asyncio.create_task(self._wait(plan), name=f"plan:{plan.group_openid}")
        self.tasks[plan.group_openid] = task

        def finished(completed):
            if self.tasks.get(plan.group_openid) is completed:
                self.tasks.pop(plan.group_openid, None)
        task.add_done_callback(finished)

    async def set(self, group_openid: str, owner_id: str, owner_name: str, when: datetime):
        await self.start()
        async with self.lock:
            if when.tzinfo is None or when.utcoffset() is None or when <= self.now():
                raise ValueError("闹钟必须设置在未来。")
            old = self.plans.get(group_openid)
            if old is not None and old.when > self.now() and when <= old.when:
                return False, old
            plan = Plan(group_openid, owner_id, owner_name, when.astimezone(BEIJING), uuid4().hex)
            updated = {**self.plans, group_openid: plan}
            # 先保存成功，再取消旧任务，写入失败时保留旧闹钟。
            self._save(updated)
            previous_task = self.tasks.get(group_openid)
            if previous_task is not None:
                previous_task.cancel()
            self.plans = updated
            self._schedule(plan)
            return True, plan

    async def cancel(self, group_openid: str):
        await self.start()
        async with self.lock:
            old = self.plans.get(group_openid)
            if old is None:
                return None
            updated = {key: plan for key, plan in self.plans.items() if key != group_openid}
            self._save(updated)
            self.plans = updated
            task = self.tasks.pop(group_openid, None)
            if task is not None:
                task.cancel()
            return old

    async def _wait(self, plan):
        try:
            while (seconds := (plan.when - self.now()).total_seconds()) > 0:
                await asyncio.sleep(min(seconds, 60))
            await self._fire(plan)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("闹钟触发或发送失败：%s %s", plan.group_openid, plan.when)

    async def _fire(self, plan):
        async with self.lock:
            if self.plans.get(plan.group_openid) != plan or plan.when > self.now():
                return False
            updated = {key: value for key, value in self.plans.items() if key != plan.group_openid}
            # 到点先领取并移除记录，防止重复发送；开始发送后取消不会撤回消息。
            self._save(updated)
            self.plans = updated
        await self.notify(plan)
        return True

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.started = False
