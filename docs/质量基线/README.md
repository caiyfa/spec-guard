# 质量基线报告索引

> 首批基线：2026-08-14。规则见 AGENTS.md「质量基线与顺手修复」——**修改某文件前查这里的记录，碰过的文件顺手修掉对应问题，修完重跑命令刷新报告**。
> 本目录只存工具原始输出（快照会过期，以复跑为准）；本文件维护摘要与判读结论。

## 摘要表

| 工具 | 报告文件 | 基线摘要 | 复现命令 |
|------|---------|---------|---------|
| oxlint（前端 lint） | `oxlint-baseline.txt` | 60 文件：**8 errors**（correctness，优先清）+ 3100 warnings | `cd workbench/frontend && npm run lint` |
| ruff（Python lint） | `ruff-baseline.txt`（明细）`ruff-statistics.txt`（分布） | **1331 项**（869 可 `--fix` 自动修）；F 类 175 F401 + 28 F841 是真 bug 信号，优先 | `ruff check` / `ruff check --statistics` |
| knip（前端死代码） | `knip-baseline.txt` | 1 未用文件（`src/pages/LarkBinding.tsx`）、2 幽灵依赖（`@types/js-yaml`、`recharts`）、14 未用导出、25 未用导出类型 | `cd workbench/frontend && npx knip` |
| jscpd（全仓查重） | `jscpd-baseline.txt` | 36 处克隆，总重复率 0.97%（健康）；**YAML 13.93%（5 处，场景库复制流）是主要热点**；Python 0.85% / TSX 0.49% | `npm run dup:scan`（仓库根） |
| vulture（Python 死代码） | `vulture-baseline.txt` | 8 行（min-confidence 80），量小可人工判读；registry 装饰器注册函数属预期误报 | `vulture engine specstd agent mcp_server workbench/backend --min-confidence 80` |
| pytest-cov（覆盖率） | `coverage-engine.txt`、`coverage-specstd.txt` | engine **46%**；specstd **87%** | 见下方「覆盖率命令」 |

## 判读结论（首批）

- **ruff 分布**：I001 导入排序 408（机械）、F401 未用导入 175、UP045 156、B904 raise 缺 from 117、E402 81、UP015 70、B008 63（已配置 FastAPI `Depends`/`Query` 等白名单，剩余需人工判）、SIM105 50。`--fix` 可清 869 项，但属批量改动，何时做由总控人拍板。
- **oxlint 8 个 error** 是 correctness 类（可能真 bug），是全部基线里优先级最高的清理对象；3100 warnings 多为 suspicious/perf 类，随功能开发顺手降。
- **YAML 查重 13.93%**：场景「复制上个场景改字段」模式所致，部分属设计内相似（同类接口的正反向用例），修复方式是提炼公共结构而非强行去重，逐案判读。
- **存量发现（与本次工具链无关，2026-08-14 实测）**：`test_specstd` **全套件跑有 94 个存量 error**——`TestAttributionREST` 等 9 个 REST 测试文件；单文件跑全绿、全套件出错 = 套件内顺序/隔离污染；报错为 `FeishuWatcher._schedule_chat_proofread` 闭包任务无法被 apscheduler 序列化；加不加 `--cov` 均复现。`test_engine` / `test_suites` 不受影响（pre-push 门禁干净）。总控 v1.24 记录 2026-08-13 全量 1399 全绿，该回归疑与飞书二期 watcher 变更或当前在途 WIP 有关，建议独立排障（单文件逐一加跑跑二分可定位污染源）。

## 覆盖率命令（按套件分开跑，与 AGENTS.md 惯例一致）

```powershell
python -m pytest test_engine --cov=engine --cov-report=term-missing
python -m pytest test_specstd --cov=specstd --cov-report=term-missing
```

## 工具配套配置位置

- oxlint：`workbench/frontend/.oxlintrc.json`（correctness=error / suspicious+perf=warn）
- ruff：`ruff.toml`（E/F/W/I/UP/B/SIM/C4，py314，FastAPI 不可变调用白名单）
- knip：`workbench/frontend/knip.json`（`@testing-library/*` 为组件测试预留，已豁免）
- jscpd：`.jscpd.json`（threshold=100 永不卡关，只出报告）
- lefthook：`lefthook.yml`（pre-push 挂 release_check + 离线测试；lint 清零前不进 pre-commit）
