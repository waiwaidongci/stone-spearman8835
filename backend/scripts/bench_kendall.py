"""规模基准：十万试件 × 两千批的逐批剔除核算。

全体统计一次 O(n log n)；每批调整 O(m_b log m_b)。
对照暴力 O(n²)（每批约需数小时级）不可行，故正确性由 tests/ 的
暴力 oracle 与恒等式保证，此处校验规模耗时与内部恒等式。

运行：cd backend && python3 -m scripts.bench_kendall
"""
import random
import time

from src.services import kendall


def generate(n_batches, per_batch, seed=42):
    rng = random.Random(seed)
    xs, ys, keys = [], [], []
    for b in range(n_batches):
        shift = rng.gauss(0, 3)
        for _ in range(per_batch):
            x = rng.gauss(shift, 1.0)
            if rng.random() < 0.1:
                x = round(x)  # 约 10% 取整，制造并列
            xs.append(x)
            ys.append(0.35 * x + rng.gauss(0, 1.0))
            keys.append(b)
    return xs, ys, keys


def joint_ties(xs, ys):
    groups = {}
    for x, y in zip(xs, ys):
        groups[(x, y)] = groups.get((x, y), 0) + 1
    return sum(v * (v - 1) // 2 for v in groups.values())


def run_scale(n_batches, per_batch):
    xs, ys, keys = generate(n_batches, per_batch)
    n = len(xs)
    t0 = time.perf_counter()
    ctx = kendall.compute_global(xs, ys)
    t1 = time.perf_counter()
    members = {}
    for i, k in enumerate(keys):
        members.setdefault(k, []).append(i)
    results = []
    for b, idx in members.items():
        results.append(kendall.leave_one_out(ctx, xs, ys, idx, min_n=5))
    t2 = time.perf_counter()
    # 内部恒等式校验
    n3 = joint_ties(xs, ys)
    assert ctx['P'] + ctx['Q'] == ctx['n0'] - ctx['n1'] - ctx['n2'] + n3, '对计数恒等式失败'
    assert sum(ctx['conc']) == 2 * ctx['P'] and sum(ctx['disc']) == 2 * ctx['Q']
    per_batch_ms = (t2 - t1) / n_batches * 1000
    print(f'批次={n_batches:>5} 试件={n:>7} | 全体统计 {t1 - t0:6.2f}s | '
          f'逐批剔除合计 {t2 - t1:6.2f}s（每批 {per_batch_ms:5.2f}ms）| τ-b={results and kendall.tau_b(n, ctx["P"], ctx["Q"], ctx["n1"], ctx["n2"], 5)[0]:+.4f}')
    return t1 - t0, t2 - t1


def main():
    print('Kendall τ-b 逐批剔除规模基准（全体一次扫描 + 批级增量调整）')
    for n_batches, per_batch in [(500, 50), (1000, 50), (2000, 50)]:
        run_scale(n_batches, per_batch)
    print('说明：每批代价只随批内试件数增长，不随全体规模增长；未按批重扫或重排全体。')


if __name__ == '__main__':
    main()
