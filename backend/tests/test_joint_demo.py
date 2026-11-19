"""联合演示数据：全样本为正、剔除杠杆批后反转——演示"少了哪一批结论会反向"。"""
import unittest

from scripts.joint_demo_data import LEVERAGE_NAME, joint_batches
from src.services import kendall


class JointDemoTest(unittest.TestCase):
    def test_leverage_batch_reverses_conclusion(self):
        xs, ys, keys = [], [], []
        for name, rows in joint_batches():
            for r in rows:
                xs.append(r['porosity'])
                ys.append(r['absorption'])
                keys.append(name)
        res = kendall.leave_one_batch_out(xs, ys, keys, min_n=5)
        self.assertEqual(res['full']['n'], len(xs))
        self.assertGreater(res['full']['tau'], 0, '演示设定：全样本 τ-b 应为正')
        by_name = dict(res['batches'])
        lev = by_name[LEVERAGE_NAME]
        self.assertTrue(lev['reversed'], '杠杆批剔除后结论应反向')
        self.assertLess(lev['tau'], 0)
        # 至少存在一个反向批次；汇总口径与逐批一致
        self.assertGreaterEqual(sum(1 for _, r in res['batches'] if r['reversed']), 1)


if __name__ == '__main__':
    unittest.main()
