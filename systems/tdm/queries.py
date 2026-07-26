"""TDM 校对查询库：全景档案相关的 DB 直查（hr_center schema，只读）。"""

import json


class TdmQueries:
    # tdm_snap_profile 的 14 个 JSON 快照字段（以 SIT 实际 DDL 为准：eval360_primary 无第二下划线）
    SNAPSHOT_JSON_FIELDS = [
        "basic_info", "work_internal", "work_external", "education",
        "attendance", "other_info", "cap_data", "grid_data", "eval_data",
        "eval_360_data", "eval360_primary", "reserve_data", "annual_perf", "exp_tags",
    ]

    def __init__(self, db):
        self.db = db

    # ── 员工表 ────────────────────────────────────────────
    def get_employee(self, emp_no):
        return self.db.query_one(
            "SELECT * FROM tdm_emp_employee WHERE emp_no = %s AND deleted = 0",
            (emp_no,))

    # ── 快照表 ────────────────────────────────────────────
    def get_snapshots(self, emp_no):
        """人员全部快照（按 snapshot_time 降序）"""
        return self.db.query(
            "SELECT sp.* FROM tdm_snap_profile sp "
            "JOIN tdm_emp_employee e ON sp.emp_id = e.id "
            "WHERE e.emp_no = %s AND sp.deleted = 0 "
            "ORDER BY sp.snapshot_time DESC",
            (emp_no,), max_rows=50)

    def get_latest_snapshot(self, emp_no):
        rows = self.get_snapshots(emp_no)
        return rows[0] if rows else None

    def get_latest_snapshot_by_type(self, emp_no, snapshot_type="RESULT"):
        """按类型取该人员最新快照（切片场景优先用 RESULT：字段完整，
        LOCK 快照的盘点结果字段通常为 NULL——锁定时结果尚未导入）"""
        rows = self.db.query(
            "SELECT sp.* FROM tdm_snap_profile sp "
            "JOIN tdm_emp_employee e ON sp.emp_id = e.id "
            "WHERE e.emp_no = %s AND sp.snapshot_type = %s AND sp.deleted = 0 "
            "ORDER BY sp.snapshot_time DESC",
            (emp_no, snapshot_type), max_rows=10)
        return rows[0] if rows else None

    def get_snapshot(self, emp_no, activity_id, snapshot_type=None):
        """按活动取快照；snapshot_type 为空时按 RESULT > HISTORY > LOCK 优先级取最优"""
        rows = self.db.query(
            "SELECT sp.* FROM tdm_snap_profile sp "
            "JOIN tdm_emp_employee e ON sp.emp_id = e.id "
            "WHERE e.emp_no = %s AND sp.activity_id = %s AND sp.deleted = 0 "
            "ORDER BY sp.snapshot_time DESC",
            (emp_no, activity_id), max_rows=10)
        if not rows:
            return None
        if snapshot_type:
            for r in rows:
                if r.get("snapshot_type") == snapshot_type:
                    return r
            return None
        for t in ("RESULT", "HISTORY", "LOCK"):
            for r in rows:
                if r.get("snapshot_type") == t:
                    return r
        return rows[0]

    def parse_snapshot_json(self, snapshot_row):
        """解析快照行的 14 个 JSON 字段 → {field: parsed_obj}"""
        result = {}
        for field in self.SNAPSHOT_JSON_FIELDS:
            raw = snapshot_row.get(field)
            if raw is None:
                result[field] = None
            else:
                try:
                    result[field] = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    result[field] = raw
        return result

    # ── DHR 源表 ──────────────────────────────────────────
    def get_dhr_employee(self, emp_no):
        """DHR 员工最新分区记录（可能多行，取首行）"""
        return self.db.query_one(
            "SELECT * FROM dhr_employee "
            "WHERE emp_no = %s AND dt_date = (SELECT MAX(dt_date) FROM dhr_employee) "
            "LIMIT 1",
            (emp_no,))

    # ── 工号池校验辅助 ────────────────────────────────────
    def count_snapshot_corps(self, emp_no):
        return self.db.scalar(
            "SELECT COUNT(DISTINCT sp.corp_code) FROM tdm_snap_profile sp "
            "JOIN tdm_emp_employee e ON sp.emp_id = e.id "
            "WHERE e.emp_no = %s AND sp.deleted = 0",
            (emp_no,))

    def get_vertical_manager_record(self, emp_no):
        """use_vertical_manager='Y' 的盘点人员记录"""
        return self.db.query_one(
            "SELECT * FROM tdm_inv_person "
            "WHERE emp_no = %s AND use_vertical_manager = 'Y' AND deleted = 0 LIMIT 1",
            (emp_no,))

    def get_activity_inventory_date(self, activity_id):
        return self.db.scalar(
            "SELECT inventory_date FROM tdm_inv_activity WHERE id = %s",
            (activity_id,))

    def get_activity_inventory_dates(self, activity_ids):
        """批量取活动盘点时间：{activity_id(int): inventory_date 或 None}。"""
        ids = [int(a) for a in (activity_ids or []) if a is not None]
        if not ids:
            return {}
        marks = ",".join(["%s"] * len(ids))
        rows = self.db.query(
            f"SELECT id, inventory_date FROM tdm_inv_activity WHERE id IN ({marks})",
            tuple(ids), max_rows=max(len(ids) * 2, 100))
        return {int(r["id"]): r.get("inventory_date") for r in rows}
