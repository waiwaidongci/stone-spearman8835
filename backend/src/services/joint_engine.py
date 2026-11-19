"""联合核算（逐批剔除）的分阶段计数引擎，与持久化层解耦。

阶段与检查点：
  1. global  —— 校验冻结快照 SHA256，全体 O(n log n) 统计，写入检查点；
  2. batches —— 逐批剔除调整，按 chunk 事务提交（已提交即"已确认进度"）；
  3. finalize —— 仅当批次结果数 == 冻结批次数时汇总并置完成。

中断恢复：worker 崩溃/重试后重新 execute()，从检查点与已确认批次续跑；
批次结果按 (run_id, study_id) 幂等覆盖，进度由 COUNT(*) 派生，重试不重复计入。

repo 协议（由 SQLAlchemy 仓储或测试仓储实现）：
  load_rows(run_id)        -> [(study_id, source_key, x, y)]  稳定顺序
  load_batches(run_id)     -> [study_id]                      按 study_id 升序
  get_checksum(run_id)     -> str
  load_global(run_id)      -> dict | None
  save_global(run_id, ctx)
  completed_batch_keys(run_id) -> set
  save_batch_results(run_id, [(study_id, res)])               幂等覆盖 + 提交
  count_batch_results(run_id)  -> int
  load_batch_results(run_id)   -> [(study_id, res)]
  finalize(run_id, full, summary)
"""
from src.services import kendall
from src.utils.serializers import checksum


class Interrupted(Exception):
    """计数被中断：已提交的批次结果保留，可从已确认进度续跑。"""


def payload_checksum(batch_keys, min_n, rows):
    """冻结内容的规范校验和：批次选择、参数与逐行测值。"""
    return checksum({'batches': list(batch_keys), 'min_n': min_n,
                     'rows': [list(r) for r in rows]})


def _verify(repo, run_id, min_n, rows, batches):
    if payload_checksum(batches, min_n, rows) != repo.get_checksum(run_id):
        raise ValueError('冻结快照校验失败')


def execute(repo, run_id, min_n, should_stop=None, chunk_size=100):
    """执行或续跑一次联合核算。全部批次齐全并 finalize 后返回 True。"""
    stop = should_stop or (lambda *args: False)
    ctx = repo.load_global(run_id)
    rows = None
    batches = repo.load_batches(run_id)
    if ctx is None:
        rows = repo.load_rows(run_id)
        _verify(repo, run_id, min_n, rows, batches)
        ctx = kendall.compute_global([r[2] for r in rows], [r[3] for r in rows])
        repo.save_global(run_id, ctx)
        if stop('global', 0, 1):
            raise Interrupted('global')
    done = repo.completed_batch_keys(run_id)
    missing = [b for b in batches if b not in done]
    if missing:
        if rows is None:
            rows = repo.load_rows(run_id)
            _verify(repo, run_id, min_n, rows, batches)
        xs = [r[2] for r in rows]
        ys = [r[3] for r in rows]
        members = {b: [] for b in batches}
        for i, r in enumerate(rows):
            members[r[0]].append(i)
        chunk = []
        for bi, b in enumerate(missing):
            chunk.append((b, kendall.leave_one_out(ctx, xs, ys, members[b], min_n)))
            if len(chunk) >= chunk_size:
                repo.save_batch_results(run_id, chunk)
                chunk = []
                if stop('batches', bi + 1, len(missing)):
                    raise Interrupted('batches')
        if chunk:
            repo.save_batch_results(run_id, chunk)
    total = repo.count_batch_results(run_id)
    if total != len(batches):
        return False  # 未齐全：等待续跑，不开放查看
    full_tau, full_flags = kendall.tau_b(ctx['n'], ctx['P'], ctx['Q'], ctx['n1'], ctx['n2'], min_n)
    results = dict(repo.load_batch_results(run_id))
    summary = {'reversed_count': 0, 'changed_count': 0, 'reversed_batches': []}
    for b in batches:
        r = results[b]
        _, reversed_, changed = kendall.verdict(full_tau, r['tau'])
        if reversed_:
            summary['reversed_count'] += 1
            summary['reversed_batches'].append(b)
        if changed:
            summary['changed_count'] += 1
    full = {
        'n': ctx['n'], 'n_batches': len(batches),
        'concordant': ctx['P'], 'discordant': ctx['Q'],
        'tie_pairs_x': ctx['n1'], 'tie_pairs_y': ctx['n2'],
        'tau': full_tau, 'flags': full_flags, 'direction': kendall.direction(full_tau),
    }
    repo.finalize(run_id, full, summary)
    return True
