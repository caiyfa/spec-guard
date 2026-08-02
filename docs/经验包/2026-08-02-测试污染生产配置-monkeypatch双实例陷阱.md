# 经验包：测试污染生产配置（monkeypatch 双实例陷阱）

> 日期：2026-08-02 ｜ 现象来源：T-306 开发自测 ｜ 影响：systems/tdm/config/env.sit.yaml 被测试覆盖（已恢复）

## 现象

为环境配置写端点写测试（`test_reference_envs.py`），测试通过后 `git status` 发现
`systems/tdm/config/env.sit.yaml` 被**截断为 2 行**（原 56 行）——测试的 PUT 请求
把真实环境配置覆盖了。

## 证据链

1. 测试代码：`from workbench.backend.routers import reference` + `monkeypatch.setattr(reference, "SYSTEMS_TDM", tmp_path)`
2. 实际写入路径却是真实文件——monkeypatch 未生效
3. 根因验证（脚本实测）：
   ```
   import workbench.backend.routers.reference as a
   import routers.reference as b
   a is b  # False —— 两个不同模块实例！
   ```
   仓库根 sys.path 导入 `workbench.backend.routers.reference`，BACKEND_DIR sys.path 导入
   `routers.reference`——**同一文件两个模块对象**。main.py 用的是后者（`from routers import reference`），
   测试 monkeypatch 了前者 → PUT 端点（main 的实例）读到的仍是真实 `SYSTEMS_TDM` → 写真实文件。

## 根因

**环节：测试基建**——monkeypatch 目标模块与运行时代码使用的模块不是同一实例
（sys.path 双路径导入同一文件产生两个模块对象），monkeypatch 静默失效。

## 修复

1. 立即 `git checkout -- systems/tdm/config/env.sit.yaml` 恢复被覆盖文件
2. 测试改用与 main 同实例的导入：`from routers import reference`（BACKEND_DIR 已在 sys.path）
3. 重跑测试并 `git status` 确认工作区无污染（双重验证）

## 预防

- **涉及写盘端点的测试，monkeypatch 必须与运行时同模块实例**——先验证 `模块 a is 模块 b`
- **写盘测试跑完必须查 `git status`**：工作区出现未预期的配置/场景文件改动 = monkeypatch 失效信号
- 仓库内跨包导入统一入口（workbench 后端一律 `from routers import ...` / `from services import ...`，
  不要混用 `workbench.backend.routers` 与 `routers` 两种路径）
