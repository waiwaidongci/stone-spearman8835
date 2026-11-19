# 验证记录（联合核算 · 逐批剔除 Kendall τ-b）

日期：2026-11-19。本环境仅有 Python 3.11 标准库（无 docker/pip/第三方包），
因此算法与计数引擎以纯标准库实现并在本地完整验证；FastAPI/MySQL/Redis 集成层
沿用既有模式，经静态检查与编译校验，端到端需在 `docker compose up` 环境复核。

## 已执行验证

### 1. 单元测试（全部通过）
```
cd backend && python3 -m unittest discover -s tests -v
→ Ran 12 tests ... OK (skipped=1: scipy oracle，仅 docker 镜像内执行)
```
- `tests/test_kendall.py`
  - 80 组强并列随机数据：全体 τ-b 与 O(n²) 暴力参照逐一相等（12 位小数）；
    恒等式 P+Q==n0−n1−n2+n3、ΣC_i==2P、ΣD_i==2Q 全部成立。
  - 40 组随机分批：逐批剔除 τ-b 与"删除该批后暴力重算"逐一相等。
  - 标记：余样常量（constant_x/constant_y）、余样不足（insufficient）触发正确，τ 为 None。
  - 反向判定：构造主体负相关+杠杆批数据，全样本为正、剔除杠杆批为负，`reversed` 正确。
  - scipy.stats.kendalltau oracle：本地跳过，docker 内自动启用。
- `tests/test_engine.py`（标准库 sqlite3 仓储，对应生产 SQLAlchemy 仓储协议）
  - 完整执行：14 项断言与一次性内存计算一致。
  - 断点续跑：第 2 个分块提交后注入中断 → 已确认 4/7 批保留、状态未完成；
    续跑只补算缺失 3 批，结果与一次性计算一致。
  - 重试幂等：完成后重复 execute，批次结果逐字节不变、计数不重复。
  - global 检查点：全体统计落库后崩溃，续跑直接复用检查点。
  - 快照校验：冻结行被篡改 → ValueError。
  - 空批次：仍登记并产出结果行（τ=全样本值），保证"齐全"口径。
- `tests/test_joint_demo.py`：演示数据全样本 τ-b>0，剔除杠杆批后反转为负。

### 2. 规模基准（满足"不能按每批重扫或重排全体"）
```
cd backend && python3 -m scripts.bench_kendall
批次= 500 试件= 25000 | 全体统计 0.11s | 逐批剔除合计 0.07s（每批 0.14ms）
批次=1000 试件= 50000 | 全体统计 0.24s | 逐批剔除合计 0.15s（每批 0.15ms）
批次=2000 试件=100000 | 全体统计 0.58s | 逐批剔除合计 0.32s（每批 0.16ms）
```
每批代价不随全体规模增长（0.14→0.16ms），全体 O(n log n) 一次扫描 + 批级增量调整。

### 3. 引擎全流程模拟（演示数据，中断→续跑→开放）
冻结 1430 件/14 批；第 3 个分块后中断（已确认 6/14，状态未开放）→ 续跑完成 14/14。
全样本 τ-b=+0.0950（正向，并列对 x=3192/y=1427 已修正）；
逐批剔除仅"澄石·联测批次-07"使结论反向（τ-b=−0.3260），其余批次剔除后仍为 +0.11~+0.12。

### 4. 静态检查
- 后端全部新增/修改文件 `python3 -m py_compile` 通过。
- 前端全部新增/修改 JS `node --check` 通过。

## 待 docker 环境复核
- FastAPI 路由（POST/GET /joint-runs、/results 的 409 门控、/resume）与 MySQL 表结构创建；
- Redis 队列 `joint:{id}` 分发、worker 崩溃恢复（启动时重投 queued/running）；
- seed 写入 14 个联测批次；前端"联合核算"页与分析执行页多选表单的实际渲染。
