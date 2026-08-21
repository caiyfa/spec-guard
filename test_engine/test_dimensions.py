"""T-981：Scenario.dimensions 只读 property（引擎加载层透传 doc 层维度标注）。"""

from engine.scenario_loader import Scenario


class TestScenarioDimensions:
    def test_dimensions_from_doc(self):
        s = Scenario(id="X-001", doc={"covers": ["FR-1"], "dimensions": ["happy-path", "state"]})
        assert s.dimensions == ["happy-path", "state"]
        assert s.covers == ["FR-1"]  # 既有行为不受影响

    def test_dimensions_default_empty(self):
        assert Scenario(id="X-002", doc={"covers": []}).dimensions == []
        assert Scenario(id="X-003", doc={}).dimensions == []
        assert Scenario(id="X-004").dimensions == []

    def test_dimensions_not_in_contract_surface(self):
        """dimensions 是 doc 层标注——加载层只透传，不进契约字段（指纹零漂移由
        test_specstd/test_dimensions 的存量回归 + release_check T6 双重保证）。"""
        s = Scenario(id="X-005", doc={"dimensions": ["negative"]})
        assert s.produces == [] and s.verify == []  # 契约面不含 doc 标注
