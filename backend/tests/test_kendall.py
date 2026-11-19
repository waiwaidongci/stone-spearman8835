"""Kendall τ-b 与逐批剔除的正确性测试：以 O(n²) 暴力实现为独立 oracle。"""
import math
import random
import unittest

from src.services import kendall


def brute_tau_b(xs, ys):
    """独立暴力参照：直接按定义数对。"""
    n = len(xs)
    p = q = n1 = n2 = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = (xs[i] > xs[j]) - (xs[i] < xs[j])
            dy = (ys[i] > ys[j]) - (ys[i] < ys[j])
            if dx == 0:
                n1 += 1
            if dy == 0:
                n2 += 1
            if dx and dy:
                if dx == dy:
                    p += 1
                else:
                    q += 1
    a = n * (n - 1) // 2 - n1
    b = n * (n - 1) // 2 - n2
    if n < 2 or a == 0 or b == 0:
        return None
    return (p - q) / math.sqrt(a * b)


def brute_joint_ties(xs, ys):
    """双重并列对数 n3，用于恒等式校验。"""
    n3 = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if xs[i] == xs[j] and ys[i] == ys[j]:
                n3 += 1
    return n3


class GlobalTauTest(unittest.TestCase):
    def test_matches_brute_with_heavy_ties(self):
        rng = random.Random(7)
        for _ in range(80):
            n = rng.randint(2, 60)
            xs = [rng.randint(0, 5) + rng.choice([0, 0.5]) for _ in range(n)]
            ys = [rng.randint(0, 5) + rng.choice([0, 0.5]) for _ in range(n)]
            ctx = kendall.compute_global(xs, ys)
            tau, _ = kendall.tau_b(n, ctx['P'], ctx['Q'], ctx['n1'], ctx['n2'], 2)
            expected = brute_tau_b(xs, ys)
            if expected is None:
                self.assertIsNone(tau)
            else:
                self.assertAlmostEqual(tau, expected, places=12)
            # 恒等式：P+Q == n0-n1-n2+n3；每元素计数求和为对数两倍
            self.assertEqual(ctx['P'] + ctx['Q'], ctx['n0'] - ctx['n1'] - ctx['n2'] + brute_joint_ties(xs, ys))
            self.assertEqual(sum(ctx['conc']), 2 * ctx['P'])
            self.assertEqual(sum(ctx['disc']), 2 * ctx['Q'])

    def test_scipy_oracle_when_available(self):
        try:
            from scipy import stats
        except ImportError:
            self.skipTest('scipy 不在当前环境（docker 镜像内执行）')
        rng = random.Random(13)
        for _ in range(20):
            n = rng.randint(5, 80)
            xs = [round(rng.gauss(0, 3), rng.choice([0, 1, 3])) for _ in range(n)]
            ys = [round(0.4 * x + rng.gauss(0, 2), rng.choice([0, 1, 3])) for x in xs]
            ctx = kendall.compute_global(xs, ys)
            tau, _ = kendall.tau_b(n, ctx['P'], ctx['Q'], ctx['n1'], ctx['n2'], 2)
            self.assertAlmostEqual(tau, stats.kendalltau(xs, ys).statistic, places=12)


class LeaveOneOutTest(unittest.TestCase):
    def test_matches_brute_per_batch(self):
        rng = random.Random(11)
        for _ in range(40):
            n_batches = rng.randint(2, 6)
            xs, ys, keys = [], [], []
            for b in range(n_batches):
                for _ in range(rng.randint(1, 12)):
                    xs.append(rng.randint(0, 4) * 1.0 + rng.choice([0, 0.25]))
                    ys.append(rng.randint(0, 4) * 1.0 + rng.choice([0, 0.25]))
                    keys.append(b)
            res = kendall.leave_one_batch_out(xs, ys, keys, min_n=3)
            self.assertEqual(len(res['batches']), n_batches)
            for b, r in res['batches']:
                rx = [x for i, x in enumerate(xs) if keys[i] != b]
                ry = [y for i, y in enumerate(ys) if keys[i] != b]
                expected = brute_tau_b(rx, ry)
                if expected is None:
                    self.assertIsNone(r['tau'], f'batch {b}')
                else:
                    self.assertAlmostEqual(r['tau'], expected, places=12, msg=f'batch {b}')
                self.assertEqual(r['n_remaining'], len(rx))
                self.assertEqual(r['n_removed'], len(xs) - len(rx))

    def test_constant_and_insufficient_flags(self):
        # 剔除 b 后 x 全部并列 → constant_x，tau 未定义
        res = kendall.leave_one_batch_out([1.0, 1.0, 1.0, 2.0], [1.0, 2.0, 3.0, 4.0],
                                          ['a', 'a', 'a', 'b'], min_n=2)
        d = dict(res['batches'])
        self.assertIn('constant_x', d['b']['flags'])
        self.assertIsNone(d['b']['tau'])
        self.assertNotIn('constant_x', d['a']['flags'])
        # 剔除后余样不足 min_n：剔除 a 余 1 件（不足 2），剔除 b 余 4 件（足够）
        res = kendall.leave_one_batch_out([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 1.0, 4.0, 3.0, 5.0],
                                          ['a', 'a', 'a', 'a', 'b'], min_n=2)
        d = dict(res['batches'])
        self.assertIn('insufficient', d['a']['flags'])
        self.assertNotIn('insufficient', d['b']['flags'])
        # 全样本 y 常量 → constant_y
        res = kendall.leave_one_batch_out([1.0, 2.0, 3.0], [7.0, 7.0, 7.0], ['a', 'a', 'b'], min_n=2)
        self.assertIn('constant_y', res['full']['flags'])
        self.assertIsNone(res['full']['tau'])

    def test_reversal_verdict(self):
        # 主体负相关 + 杠杆批（高水平强正相关）→ 全体为正，剔除杠杆批后反转为负
        xs, ys, keys = [], [], []
        rng = random.Random(3)
        for _ in range(40):
            x = rng.uniform(0, 10)
            xs.append(x)
            ys.append(5 - 0.4 * x + rng.gauss(0, 0.5))
            keys.append('bulk')
        for _ in range(20):
            x = rng.uniform(20, 24)
            xs.append(x)
            ys.append(20 + (x - 20) + rng.gauss(0, 0.3))
            keys.append('leverage')
        res = kendall.leave_one_batch_out(xs, ys, keys, min_n=5)
        d = dict(res['batches'])
        self.assertGreater(res['full']['tau'], 0)
        self.assertTrue(d['leverage']['reversed'])
        self.assertLess(d['leverage']['tau'], 0)
        self.assertFalse(d['bulk']['reversed'])
        # 与暴力参照的符号判断一致
        rx = [x for i, x in enumerate(xs) if keys[i] != 'leverage']
        ry = [y for i, y in enumerate(ys) if keys[i] != 'leverage']
        self.assertLess(brute_tau_b(rx, ry), 0)


if __name__ == '__main__':
    unittest.main()
