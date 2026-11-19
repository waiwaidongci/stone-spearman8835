"""联合核算演示数据（纯标准库，固定种子，可复现）。

13 批常规批次：孔隙率/吸水率弱负相关；
第 07 批为"杠杆批"：整体水平偏高且强正相关。
合并后全样本 Kendall τ-b 为正，剔除第 07 批后结论反转为负——
正好回答"少了哪一批，结论会反向"。
"""
import random

LEVERAGE_NAME = '澄石·联测批次-07'


def joint_batches():
    """返回 [(批次名, [{'porosity':..,'absorption':..}, ...]), ...]，共 14 批。"""
    rng = random.Random(20261119)
    batches = []
    for idx in range(1, 15):
        name = f'澄石·联测批次-{idx:02d}'
        rows = []
        if idx == 7:
            for _ in range(260):
                x = round(rng.uniform(30, 38), 1)
                y = round(0.5 * (x - 30) + 9 + rng.gauss(0, 0.8), 2)
                rows.append({'porosity': x, 'absorption': y})
        else:
            for _ in range(90):
                x = round(rng.uniform(4, 28), 1)
                y = round(max(0.0, 8 - 0.10 * x + rng.gauss(0, 1.2)), 2)
                rows.append({'porosity': x, 'absorption': y})
        batches.append((name, rows))
    return batches
