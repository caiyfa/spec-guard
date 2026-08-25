"""db_access 单测：守卫链（_guard + SQL_DENY_RE 并集）+ 插值 + 缓存键。

全部离线可跑（不连真实 DB）：守卫拒绝在连接建立前触发；DB 未配置走
DbAccessError 分支。
"""
import pytest


def test_guard_rejects_non_select():
    from sg_core.db_access import DbAccessError, _guard_sql
    with pytest.raises(DbAccessError, match="非查询语句"):
        _guard_sql("DELETE FROM t")


def test_guard_rejects_for_update():
    from sg_core.db_access import DbAccessError, _guard_sql
    with pytest.raises(DbAccessError, match="危险子句"):
        _guard_sql("SELECT * FROM t FOR UPDATE")


def test_guard_rejects_lock_in_share_mode():
    # SQL_DENY_RE 黑名单项（ReadOnlyDb._FORBIDDEN_SELECT 不含，必须并集生效）
    from sg_core.db_access import DbAccessError, _guard_sql
    with pytest.raises(DbAccessError, match="危险子句"):
        _guard_sql("SELECT * FROM t LOCK IN SHARE MODE")


def test_guard_rejects_multi_statement():
    from sg_core.db_access import DbAccessError, _guard_sql
    with pytest.raises(DbAccessError, match="多语句"):
        _guard_sql("SELECT 1; SELECT 2")


def test_guard_passes_normal_select():
    from sg_core.db_access import _guard_sql
    assert _guard_sql("SELECT 1") is None


def test_interpolate_missing_var_names_variable():
    from sg_core.db_access import DbAccessError, _interpolate
    with pytest.raises(DbAccessError, match="变量未定义.*emp\\.no"):
        _interpolate("SELECT {{emp.no}}", {"x": 1})


def test_interpolate_no_vars_noop():
    # vars=None：跳过插值（db_evidence 现状语义——带 {{}} 的 SQL 原样执行）
    from sg_core.db_access import _interpolate
    assert _interpolate("SELECT {{x}}", None) == "SELECT {{x}}"


def test_interpolate_renders_known_vars():
    from sg_core.db_access import _interpolate
    assert _interpolate("SELECT {{a}}-{{b}}", {"a": 1, "b": 2}) == "SELECT 1-2"


def test_execute_readonly_no_db_config_raises(tmp_path, monkeypatch):
    # 无 env db 段 → DbAccessError（含 hint），不炸原始异常
    from sg_core import db_access
    monkeypatch.setattr(db_access, "_load_env_cfg",
                        lambda env: {})
    monkeypatch.setattr(db_access, "_resolve_system", lambda: "tdm")
    with pytest.raises(db_access.DbAccessError, match="db 段"):
        db_access.execute_readonly("SELECT 1", env_name="sit", _bypass_cache=True)
