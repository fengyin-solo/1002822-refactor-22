"""园建设施业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "facility"
REQUIRED_FIELDS = ["设施编号", "设施名称", "设施类型"]
OPTIONAL_FIELDS = ["所在绿地", "安装日期", "上次检修", "损坏描述"]
STATUS_ORDER = ["完好", "轻微损坏", "严重损坏", "已修复"]
ACTIONS = ["登记损坏", "安排修复", "验收修复"]

# 统一损坏等级判定口径：登记损坏、安排修复、验收修复三处共用这一份，
# 损坏描述命中严重关键词就是严重损坏，否则按轻微损坏处理。
SEVERE_DAMAGE_KEYWORDS = ["断裂", "倒塌", "坍塌", "脱落", "倾斜", "无法使用", "严重"]


def judge_damage_level(description: Any) -> str:
    """按统一口径判定损坏等级：三个动作只调这一处，不再各判各的。"""
    text = str(description or "")
    if any(word in text for word in SEVERE_DAMAGE_KEYWORDS):
        return "严重损坏"
    return "轻微损坏"


def _last_record(records: list[dict[str, Any]], action: str) -> dict[str, Any] | None:
    for record in reversed(records):
        if record.get("动作") == action:
            return record
    return None


def recheck_entry(entry: dict[str, Any]) -> None:
    """按统一口径重算当前等级：最后一次验收结论优先，检修日期缺填时取安排修复时间。

    只回写当前状态字段，检修记录保持原样。
    """
    records = entry.setdefault("检修记录", [])
    scheduled = _last_record(records, "安排修复")
    if scheduled is not None and not str(entry.get("上次检修") or "").strip():
        entry["上次检修"] = str(scheduled.get("时间") or "")
    last_accept = _last_record(records, "验收修复")
    if last_accept is not None and records and records[-1] is last_accept:
        # 等级冲突时以最后一次验收的结论为准
        if str(last_accept.get("结论") or "") == "不通过":
            level = judge_damage_level(last_accept.get("损坏描述"))
        else:
            level = "已修复"
    elif records or str(entry.get("损坏描述") or "").strip():
        level = judge_damage_level(entry.get("损坏描述"))
    else:
        level = "完好"
    entry["status"] = level
    entry["设施状态"] = level
    entry["pending"] = level != STATUS_ORDER[-1]
    # 运营概览等其他模块直接读 abnormal，异常量跟着明细等级走
    entry["abnormal"] = level == "严重损坏"


class FacilityService:
    def __init__(self) -> None:
        # 存量数据按新口径回填一遍：只重算当前等级与检修日期，旧检修记录不改
        self.backfill_damage_levels()

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
        for field in OPTIONAL_FIELDS:
            entry[field] = values.get(field) or ""
        entry["设施状态"] = STATUS_ORDER[0]
        entry["检修记录"] = []
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"园建设施 {entry_id} 不存在或已归档"
        if action not in ACTIONS:
            return None, f"动作「{action}」不属于园建设施可执行范围"
        values = values or {}
        description = str(values.get("损坏描述") or "").strip()
        if description:
            entry["损坏描述"] = description
        happened = str(values.get("检修日期") or "").strip() or date.today().isoformat()
        conclusion = str(values.get("验收结论") or "").strip()
        if action == "验收修复" and not conclusion:
            conclusion = "通过"
        # 三个动作都按同一份口径判定，验收结论为通过时记为已修复
        if action == "验收修复" and conclusion != "不通过":
            level = "已修复"
        else:
            level = judge_damage_level(entry.get("损坏描述"))
        entry.setdefault("检修记录", []).append({
            "时间": happened,
            "动作": action,
            "损坏描述": str(entry.get("损坏描述") or ""),
            "判定等级": level,
            "结论": conclusion,
        })
        recheck_entry(entry)
        return entry, f"园建设施已{action}，损坏等级按统一口径判定为「{entry['status']}」"

    def backfill_damage_levels(self) -> int:
        """按新口径回填一遍存量设施：只重算当前等级，旧检修记录保持原样。"""
        rows = store.rows(MODULE)
        for row in rows:
            recheck_entry(row)
        return len(rows)
