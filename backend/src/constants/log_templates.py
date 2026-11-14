"""审计动作 -> 中文标签。"""
from __future__ import annotations

ACTIONS: dict[str, str] = {
    "auth.login": "登录",
    "team.update": "调整团队预算",
    "run.create": "发起成本运行",
    "run.complete": "成本运行完成",
    "alert.review": "处置预算告警",
    "export.charges": "导出分摊账单",
    "http.mutation": "写请求",
    "bill.import": "导入供应商账单",
    "bill.reconcile": "发起账单核对",
    "bill.finding.resolve": "处置核对差异",
    "bill.confirm": "确认发布账单",
}
