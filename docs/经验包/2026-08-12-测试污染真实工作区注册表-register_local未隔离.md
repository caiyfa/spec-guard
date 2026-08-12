# 2026-08-12-测试污染真实工作区注册表-register_local未隔离

## 现象

会话 `20260812_184441_9b7aec0f`（requirement_interview / tdm 工作区）提示工作区不可用，AgentChat 报「工作区不可用（未激活或不存在）」。排查发现 `specstd/workspaces/registry.yaml` 被清空：`active: ''`、`workspaces: []`——tdm 工作区注册条目消失，但克隆目录 `specstd/workspaces/_clones/tdm` 完好（git remote / branch / HEAD 均在）。

## 证据链

- `registry.yaml` 内容（2026-08-12 19:33 被写空，30 字节）：`active: ''` + `workspaces: []`
- `_clones/tdm` 完好：`origin http://gitlab.fehorizon.com/hr/TDM/ifelc-spec-tdm.git`、branch `master`、HEAD `437a474`——数据零丢失，仅注册条目被删
- 污染链条（`test_specstd/test_delta_doc_writer.py` 第一版 fixture）：
  - `repo(tmp_path)` fixture **未依赖 `db` fixture** → `monkeypatch REGISTRY_PATH → tmp` 未生效，`register_local("tdm", tmp_path/repo, activate=True)` 写入**真实** `registry.yaml`，把原 git 型 tdm 条目覆盖为临时 local 路径
  - 测试 teardown 执行 `unregister("tdm")` → 把真实注册表里的 tdm 条目**删除**
  - 修复测试隔离（fixture 改为依赖 `db`）后污染不再发生，但破坏已在首轮 13 个失败测试运行时造成
- 同类先例：`2026-08-12-pytest端到端测试污染真实会话目录.md`（TestClient 未隔离 SESSIONS_ROOT/DB_PATH）、`2026-08-02-测试污染生产配置-monkeypatch双实例陷阱.md`

## 根因

**测试基建缺失**：register_local/unregister 测试未隔离 `specstd.workspace.REGISTRY_PATH`，且 fixture 依赖注入顺序错误——`repo` 不依赖 `db` 导致 monkeypatch 在注册后/注销前未生效；注册名 `tdm` 与真实工作区同名，覆盖真实条目后 teardown 删除。

## 修复

1. 无损重建 `registry.yaml`：git 型 tdm 条目写回（url / branch=master / local_path=`specstd/workspaces/_clones/tdm` / last_commit=437a474 / active=tdm），**复用现有克隆不重新 clone**
2. `test_delta_doc_writer.py` / `test_delta_committer.py` 的 `repo`/`git_repo` fixture 改为**依赖 `db` fixture**（monkeypatch REGISTRY_PATH/CLONES_DIR 生效后再 register），测试名避开真实工作区名（用 test-mcp 等非冲突名更稳）
3. 验证：`get_workspace('tdm')` → active=tdm → `read_spec` 正常返回 AGENTS.md；新增测试 22+18 例全绿

## 预防

- 新增任何 `register_local/register_git` 测试前，确认 `REGISTRY_PATH`/`CLONES_DIR` 已 monkeypatch 到 tmp，且 fixture 依赖注入顺序保证 monkeypatch **先于** register 执行（repo 依赖 db）
- 测试注册的工作区名禁止与真实工作区同名（tdm/test-mcp 以外的独立命名空间）
- 跑完含 register/unregister 的测试后查 `git status` + `specstd/workspaces/registry.yaml` 内容，确认零污染
- 经验包登记规则：凡是「测试写入真实仓库/注册表」的污染事件，一律登记并互相引用（三篇同类已互链）
