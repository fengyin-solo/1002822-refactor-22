"""园建设施业务规则：损坏等级统一口径、检修记录与回填都收在这里。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "facility"
REQUIRED_FIELDS = ["设施编号", "设施名称", "设施类型"]
STATUS_ORDER = ["完好", "轻微损坏", "严重损坏", "已修复"]
ACTIONS = ["登记损坏", "安排修复", "验收修复"]

# 损坏等级统一口径：登记损坏、安排修复、验收修复都按这一份判定
DAMAGE_LEVELS = ["完好", "轻微损坏", "严重损坏"]
DAMAGE_KEYWORDS = {
    "严重损坏": ("坍塌", "倒塌", "断裂", "严重", "危险", "无法使用"),
    "轻微损坏": ("轻微", "裂纹", "裂缝", "松动", "锈蚀", "掉漆", "磨损"),
}

# 设施损坏等级 → 树木支撑状态：另一个业务模块的损坏等级跟着明细变
SUPPORT_STATUS_BY_LEVEL = {"严重损坏": "损坏", "轻微损坏": "松动", "完好": "稳固"}

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")


def normalize_text(value: Any) -> str:
    """损坏描述统一写法：收敛空白、去掉末尾句号。"""
    return " ".join(str(value or "").split()).rstrip("。.")


def normalize_date(value: Any) -> str | None:
    """检修日期统一写法：YYYY-MM-DD；缺填或写法认不出来时返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def judge_damage_level(description: Any = "", explicit: Any = "") -> str:
    """统一口径：显式等级优先，其次按损坏描述关键词判定，默认完好。"""
    level = str(explicit or "").strip()
    if level in DAMAGE_LEVELS:
        return level
    text = normalize_text(description)
    for candidate in ("严重损坏", "轻微损坏"):  # 先重后轻，避免轻词盖住重词
        if any(keyword in text for keyword in DAMAGE_KEYWORDS[candidate]):
            return candidate
    return "完好"


class FacilityService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设施编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["设施状态"] = STATUS_ORDER[0]
        entry["损坏等级"] = DAMAGE_LEVELS[0]
        entry["检修记录"] = []
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"园建设施 {entry_id} 不存在或已归档"
        if action not in ACTIONS:
            return None, f"动作「{action}」不属于园建设施可执行范围"
        values = values or {}
        today = date.today().isoformat()
        if action == "登记损坏":
            message = self._register_damage(entry, values, today)
        elif action == "安排修复":
            message = self._schedule_repair(entry, values, today)
        else:
            message = self._accept_repair(entry, values, today)
        self._sync_support(entry)
        return entry, message

    def backfill(self) -> dict[str, Any]:
        """按统一口径回填全部设施：旧检修记录不改，只追加一条回填记录。"""
        today = date.today().isoformat()
        changed: list[dict[str, Any]] = []
        synced = 0
        rows = store.rows(MODULE)
        for entry in rows:
            before = (entry.get("status"), self._current_level(entry), entry.get("上次检修"))
            status, level = self._resolved_state(entry)
            # 检修日期统一写法；缺填时以安排修复的时间为准
            repaired_on = normalize_date(entry.get("上次检修")) or normalize_date(entry.get("安排修复时间"))
            entry["上次检修"] = repaired_on
            entry["损坏等级"] = level
            entry["status"] = status
            entry["设施状态"] = status
            entry["pending"] = status != STATUS_ORDER[-1]
            entry["abnormal"] = level == DAMAGE_LEVELS[-1]
            if before != (status, level, repaired_on):
                changed.append({"id": entry.get("id"), "设施编号": entry.get("设施编号"), "损坏等级": level, "设施状态": status})
                self._append_record(
                    entry,
                    action="口径回填",
                    level=level,
                    description=normalize_text(entry.get("损坏描述")),
                    repaired_on=repaired_on,
                    at=today,
                )
            synced += self._sync_support(entry)
        return {"total": len(rows), "changed": len(changed), "support_synced": synced, "items": changed}

    def _register_damage(self, entry: dict[str, Any], values: dict[str, Any], today: str) -> str:
        description = normalize_text(values.get("损坏描述")) or normalize_text(entry.get("损坏描述"))
        if description:
            entry["损坏描述"] = description
        repaired_on = normalize_date(values.get("检修日期"))
        if repaired_on:
            entry["上次检修"] = repaired_on
        level = judge_damage_level(description, values.get("损坏等级"))
        self._apply_level(entry, level)
        self._append_record(
            entry,
            action="登记损坏",
            level=level,
            description=description,
            repaired_on=normalize_date(entry.get("上次检修")),
            at=today,
        )
        return f"园建设施已登记损坏，损坏等级按统一口径判定为{level}"

    def _schedule_repair(self, entry: dict[str, Any], values: dict[str, Any], today: str) -> str:
        scheduled_on = normalize_date(values.get("日期")) or today
        entry["安排修复时间"] = scheduled_on
        if normalize_date(entry.get("上次检修")) is None:
            # 检修日期缺填时以安排修复的时间为准
            entry["上次检修"] = scheduled_on
        description = normalize_text(values.get("损坏描述"))
        if description:
            entry["损坏描述"] = description
        explicit = str(values.get("损坏等级") or "").strip()
        if description or explicit:
            level = judge_damage_level(description or entry.get("损坏描述"), explicit)
        else:
            level = self._current_level(entry)
        self._apply_level(entry, level)
        self._append_record(
            entry,
            action="安排修复",
            level=level,
            description=normalize_text(entry.get("损坏描述")),
            repaired_on=normalize_date(entry.get("上次检修")),
            at=scheduled_on,
        )
        return f"园建设施已安排修复（{scheduled_on}），损坏等级按统一口径判定为{level}"

    def _accept_repair(self, entry: dict[str, Any], values: dict[str, Any], today: str) -> str:
        conclusion = normalize_text(values.get("验收结论")) or "合格"
        accepted_on = normalize_date(values.get("日期")) or today
        entry["最后验收结论"] = conclusion
        entry["最后验收时间"] = accepted_on
        if conclusion == "合格":
            level = DAMAGE_LEVELS[0]
            entry["损坏等级"] = level
            entry["status"] = STATUS_ORDER[-1]
            entry["设施状态"] = STATUS_ORDER[-1]
            entry["pending"] = False
            entry["abnormal"] = False
        else:
            description = normalize_text(values.get("损坏描述")) or normalize_text(entry.get("损坏描述"))
            level = judge_damage_level(description, values.get("损坏等级"))
            self._apply_level(entry, level)
        self._append_record(
            entry,
            action="验收修复",
            level=level,
            description=normalize_text(entry.get("损坏描述")),
            repaired_on=normalize_date(entry.get("上次检修")),
            at=accepted_on,
            conclusion=conclusion,
        )
        return f"园建设施验收{conclusion}，损坏等级以最后一次验收为准判定为{level}"

    def _apply_level(self, entry: dict[str, Any], level: str) -> None:
        entry["损坏等级"] = level
        entry["status"] = level
        entry["设施状态"] = level
        entry["pending"] = True
        entry["abnormal"] = level == DAMAGE_LEVELS[-1]

    def _current_level(self, entry: dict[str, Any]) -> str:
        for key in ("损坏等级", "status"):
            level = str(entry.get(key) or "").strip()
            if level in DAMAGE_LEVELS:
                return level
        return judge_damage_level(entry.get("损坏描述"))

    def _resolved_state(self, entry: dict[str, Any]) -> tuple[str, str]:
        """统一重算 (status, 损坏等级)：有验收记录时以最后一次验收的结论为准。"""
        for record in reversed(entry.get("检修记录") or []):
            if record.get("动作") != "验收修复":
                continue
            level = record.get("损坏等级") if record.get("损坏等级") in DAMAGE_LEVELS else DAMAGE_LEVELS[0]
            status = STATUS_ORDER[-1] if record.get("验收结论") == "合格" else level
            return status, level
        level = self._current_level(entry)
        return level, level

    def _append_record(
        self,
        entry: dict[str, Any],
        *,
        action: str,
        level: str,
        description: str,
        repaired_on: str | None,
        at: str,
        conclusion: str = "",
    ) -> None:
        """检修记录只追加不修改，旧记录保持原样。"""
        records = entry.setdefault("检修记录", [])
        record: dict[str, Any] = {
            "序号": len(records) + 1,
            "动作": action,
            "损坏等级": level,
            "损坏描述": description,
            "检修日期": repaired_on,
            "登记时间": at,
        }
        if conclusion:
            record["验收结论"] = conclusion
        records.append(record)

    def _sync_support(self, entry: dict[str, Any]) -> int:
        """树木支撑的损坏等级跟着设施明细变，返回同步的行数。"""
        target = SUPPORT_STATUS_BY_LEVEL.get(self._current_level(entry))
        if target is None:
            return 0
        code = str(entry.get("设施编号") or "").strip()
        suffix = code.rsplit("-", 1)[-1] if "-" in code else ""
        synced = 0
        for row in store.rows("support"):
            support_code = str(row.get("支撑编号") or "").strip()
            linked = bool(code) and row.get("设施编号") == code
            if not linked and suffix:
                linked = support_code.rsplit("-", 1)[-1] == suffix
            if not linked:
                continue
            row["status"] = target
            row["支撑状态"] = target
            row["pending"] = target != "已拆除"
            row["abnormal"] = target == "损坏"
            synced += 1
        return synced
