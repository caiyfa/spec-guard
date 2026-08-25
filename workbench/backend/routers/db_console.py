"""DB 证据面板 API（设计 2026-08-25 §A2）。

无 RBAC 门槛（登录即可用——menu_guard 未绑定前缀默认放行）；
每次 query 落审计（action=db_query，失败不阻断——T-082 纪律）。
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import get_current_user

router = APIRouter(prefix="/api/db", tags=["db-console"])


class QueryBody(BaseModel):
    sql: str
    schema: str = ""
    vars: dict | None = None


@router.get("/schemas")
def list_schemas(user=Depends(get_current_user)):
    """当前工作区 env 配置的 schema 清单（名称 + default 标记 + 探活态）。"""
    from sg_core import db_access
    try:
        dbs, default_name = db_access.get_db_connections()
        return {"schemas": [
            {"name": n, "is_default": n == default_name, "alive": True}
            for n in sorted(dbs)
        ], "default": default_name}
    except db_access.DbAccessError:
        return {"schemas": [], "default": ""}
    except Exception:
        return {"schemas": [], "default": ""}


@router.post("/query")
def query(body: QueryBody, user=Depends(get_current_user)):
    """只读查询（守卫→插值→执行）；守卫/配置/执行错误统一 400 + 明细。"""
    from sg_core import db_access

    t_start = time.time()
    try:
        out = db_access.execute_readonly(
            body.sql, schema=body.schema or "", vars=body.vars)
    except db_access.DbAccessError as e:
        detail = str(e)
        if e.hint:
            detail = f"{detail}（{e.hint}）"
        raise HTTPException(status_code=400, detail=detail)

    # 审计（失败静默不阻断——T-082 纪律）
    try:
        from sg_core import user_store as _us
        _us.audit(
            user.emp_no, "db_query", target=body.schema or "default",
            detail=json.dumps({
                "sql": body.sql[:500], "rows": out["row_count"],
                "elapsed_ms": out["elapsed_ms"],
            }, ensure_ascii=False),
            db_path=_us.DB_PATH)
    except Exception:
        pass

    return {
        "rows": out["rows"],
        "row_count": out["row_count"],
        "truncated": out["truncated"],
        "elapsed_ms": out["elapsed_ms"],
        "sql_rendered": out["sql_rendered"],
        "total_ms": int((time.time() - t_start) * 1000),
    }
