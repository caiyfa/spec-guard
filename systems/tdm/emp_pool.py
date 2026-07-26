"""工号池：角色化候选工号 + 执行前 DB 校验 + 动态选择。

emp-pool.yaml 结构：
roles:
  snapshot_rich:
    description: 有快照记录的人员
    candidates: ["90024713", ...]
    check:
      sql: SELECT ... WHERE emp_no = %s ...   # 返回数值
      min: 1                                   # 校验通过阈值（>=）
    # check 为 null 时免校验（如 nonexistent 固定假工号）

select(role) 遍历候选执行 check SQL，返回首个满足者；
全部不满足 → 抛 SkipScenario（场景标记 SKIP 而非 FAIL）。
"""

import os

import yaml

from engine.scenario_runner import SkipScenario

_POOL_FILE = os.path.join(os.path.dirname(__file__), "config", "emp-pool.yaml")


class EmpPool:
    def __init__(self, db, pool_file=None):
        self.db = db
        with open(pool_file or _POOL_FILE, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        self.roles = raw.get("roles") or {}

    def select(self, role, exclude=None):
        """按角色选择可用工号，返回 {"no": 工号, "role": 角色, "check_value": 校验值}
    
        exclude: 需跳过的工号集合（已被独占租约的候选）；全部被排除 → SkipScenario(pool_leased_out)
        """
        if self.db is None:
            raise SkipScenario(f"工号池角色 {role} 需要数据库连接，但当前环境 DB 不可用")
        cfg = self.roles.get(role)
        if cfg is None:
            raise SkipScenario(f"工号池未定义角色: {role}（已定义: {sorted(self.roles)}）")
        candidates = cfg.get("candidates") or []
        check = cfg.get("check")
        if not candidates:
            raise SkipScenario(
                f"工号池角色 {role}（{cfg.get('description', '')}）无候选工号，"
                f"请在 systems/tdm/config/emp-pool.yaml 补充")
        exclude = exclude or set()
        if check is None:
            for emp_no in candidates:
                if emp_no not in exclude:
                    return {"no": emp_no, "role": role, "check_value": None}
            raise SkipScenario(
                f"工号池角色 {role}（{cfg.get('description', '')}）候选均已被独占租出"
                f"（{len(exclude)} 个被租），请扩充 emp-pool.yaml",
                category="pool_leased_out")
        sql, min_val = check.get("sql"), check.get("min", 1)
        failures = []
        for emp_no in candidates:
            if emp_no in exclude:
                failures.append(f"{emp_no}(已被独占租约)")
                continue
            try:
                val = self.db.scalar(sql, (emp_no, emp_no)) if sql.count("%s") == 2 \
                    else self.db.scalar(sql, (emp_no,))
            except Exception as e:
                failures.append(f"{emp_no}(校验异常:{e})")
                continue
            if val is not None and int(val) >= min_val:
                return {"no": emp_no, "role": role, "check_value": int(val)}
            failures.append(f"{emp_no}(値:{val}<min:{min_val})")
        leased_note = f"（其中 {len(exclude)} 个被独占租约）" if exclude else ""
        raise SkipScenario(
            f"工号池角色 {role}（{cfg.get('description', '')}）全部候选不满足校验{leased_note}："
            f"{'、'.join(failures)}。请补充候选工号")
