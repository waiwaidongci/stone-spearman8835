"""精确 Kendall τ-b（保留并列修正）与逐批剔除（leave-one-batch-out）核算。

规模约束：十万试件、两千批。全体统计只做一次 O(n log n) 扫描；
每批剔除的调整代价为 O(m_b log m_b)（m_b 为批内试件数），
不按每批重扫或重排全体。

数学要点：
  τ-b = (P - Q) / sqrt((n0 - n1)(n0 - n2))
  P/Q 为严格协和/冲突对数；n1/n2 为 x/y 并列对数（含双重并列）。
  剔除批次 b 时：
    P' = P - (Σ_{i∈b} C_i - P_int(b))   C_i 为 i 的全体协和伙伴数，P_int(b) 为批内协和对
    n1' = n1 - Σ_g [C(t_g,2) - C(t_g - c_gb,2)]   仅遍历 b 触到的并列组
"""
import math


def compress(values):
    """数值序列 → 并列秩（0..g-1）与各组大小。O(n log n)。"""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0] * len(values)
    sizes = []
    i = 0
    while i < len(values):
        j = i + 1
        v = values[order[i]]
        while j < len(values) and values[order[j]] == v:
            j += 1
        r = len(sizes)
        for k in range(i, j):
            ranks[order[k]] = r
        sizes.append(j - i)
        i = j
    return ranks, sizes


def pair_counts(xr, yr, y_groups):
    """每元素的 (协和伙伴数, 冲突伙伴数)。两次 BIT 扫描，O(n log n)。

    仅统计严格不等的对；x 或 y 并列的对既非协和也非冲突。
    """
    n = len(xr)
    conc = [0] * n
    disc = [0] * n
    if n < 2:
        return conc, disc
    order = sorted(range(n), key=lambda i: (xr[i], yr[i]))
    ox = [xr[i] for i in order]
    oy = [yr[i] for i in order]
    size = y_groups + 1
    # 前向：严格更小 x 组中的 SW（y 更小，协和）与 NW（y 更大，冲突）
    bit = [0] * size
    prior = 0
    k = 0
    while k < n:
        j = k + 1
        xk = ox[k]
        while j < n and ox[j] == xk:
            j += 1
        for t in range(k, j):
            y = oy[t]
            p = y + 1
            le = 0
            while p > 0:
                le += bit[p]
                p -= p & -p
            p = y
            lt = 0
            while p > 0:
                lt += bit[p]
                p -= p & -p
            i = order[t]
            conc[i] += lt
            disc[i] += prior - le
        for t in range(k, j):
            p = oy[t] + 1
            while p < size:
                bit[p] += 1
                p += p & -p
        prior += j - k
        k = j
    # 后向：严格更大 x 组中的 NE（y 更大，协和）与 SE（y 更小，冲突）
    bit = [0] * size
    later = 0
    k = n
    while k > 0:
        s = k - 1
        xk = ox[s]
        while s > 0 and ox[s - 1] == xk:
            s -= 1
        for t in range(s, k):
            y = oy[t]
            p = y + 1
            le = 0
            while p > 0:
                le += bit[p]
                p -= p & -p
            p = y
            lt = 0
            while p > 0:
                lt += bit[p]
                p -= p & -p
            i = order[t]
            conc[i] += later - le
            disc[i] += lt
        for t in range(s, k):
            p = oy[t] + 1
            while p < size:
                bit[p] += 1
                p += p & -p
        later += k - s
        k = s
    return conc, disc


def compute_global(xs, ys):
    """全体一次性统计：并列秩、每元素伙伴数、P/Q/n0/n1/n2。O(n log n)。"""
    n = len(xs)
    xr, tx = compress(xs)
    yr, ty = compress(ys)
    conc, disc = pair_counts(xr, yr, len(ty))
    p = sum(conc) // 2
    q = sum(disc) // 2
    return {
        'n': n, 'xr': xr, 'yr': yr, 'tx': tx, 'ty': ty,
        'conc': conc, 'disc': disc, 'P': p, 'Q': q,
        'n0': n * (n - 1) // 2,
        'n1': sum(t * (t - 1) // 2 for t in tx),
        'n2': sum(u * (u - 1) // 2 for u in ty),
    }


def tau_b(n, p, q, n1, n2, min_n):
    """由精确对计数求 τ-b；返回 (tau 或 None, 标记列表)。

    标记：insufficient 余样不足；constant_x / constant_y 余样该列常量（并列修正后分母为 0）。
    """
    flags = []
    if n < min_n:
        flags.append('insufficient')
    n0 = n * (n - 1) // 2
    a = n0 - n1
    b = n0 - n2
    if n >= 2:
        if a == 0:
            flags.append('constant_x')
        if b == 0:
            flags.append('constant_y')
    if n < 2 or a <= 0 or b <= 0:
        return None, flags
    return (p - q) / math.sqrt(a * b), flags


def sign(tau):
    if tau is None:
        return None
    return (tau > 0) - (tau < 0)


def direction(tau):
    s = sign(tau)
    return {1: 'positive', 0: 'zero', -1: 'negative'}.get(s, 'undefined')


def verdict(full_tau, tau):
    """对照全样本方向，给出 (方向, 是否反向, 是否方向变化)。"""
    fs = sign(full_tau)
    s = sign(tau)
    reversed_ = fs not in (None, 0) and s is not None and s == -fs
    changed = s is not None and fs is not None and s != fs
    return direction(tau), reversed_, changed


def leave_one_out(ctx, xs, ys, members, min_n):
    """剔除 members（全体下标列表）后的精确统计。O(m log m)，m 为该批大小。"""
    n = ctx['n']
    m = len(members)
    conc = ctx['conc']
    disc = ctx['disc']
    sum_c = 0
    sum_d = 0
    gx = {}
    gy = {}
    xr = ctx['xr']
    yr = ctx['yr']
    for i in members:
        sum_c += conc[i]
        sum_d += disc[i]
        r = xr[i]
        gx[r] = gx.get(r, 0) + 1
        r = yr[i]
        gy[r] = gy.get(r, 0) + 1
    # 批内对（两端都在被剔批次内）：在 ΣC_i 中计了两次，需补回一次
    if m >= 2:
        bxr, _ = compress([xs[i] for i in members])
        byr, bty = compress([ys[i] for i in members])
        bc, bd = pair_counts(bxr, byr, len(bty))
        p_int = sum(bc) // 2
        q_int = sum(bd) // 2
    else:
        p_int = q_int = 0
    p2 = ctx['P'] - (sum_c - p_int)
    q2 = ctx['Q'] - (sum_d - q_int)
    tx = ctx['tx']
    n1 = ctx['n1']
    for r, c in gx.items():
        t = tx[r]
        n1 -= t * (t - 1) // 2 - (t - c) * (t - c - 1) // 2
    ty = ctx['ty']
    n2 = ctx['n2']
    for r, c in gy.items():
        u = ty[r]
        n2 -= u * (u - 1) // 2 - (u - c) * (u - c - 1) // 2
    remaining = n - m
    tau, flags = tau_b(remaining, p2, q2, n1, n2, min_n)
    return {
        'n_removed': m, 'n_remaining': remaining,
        'concordant': p2, 'discordant': q2,
        'tau': tau, 'flags': flags,
    }


def leave_one_batch_out(xs, ys, keys, min_n):
    """一次性内存版：全样本 + 逐批剔除。keys 为每行所属批次（可哈希）。

    返回 {'full': {...}, 'batches': [(key, res), ...]}，按 key 出现顺序。
    """
    ctx = compute_global(xs, ys)
    full_tau, full_flags = tau_b(ctx['n'], ctx['P'], ctx['Q'], ctx['n1'], ctx['n2'], min_n)
    groups = {}
    order = []
    for i, k in enumerate(keys):
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(i)
    batches = []
    for k in order:
        res = leave_one_out(ctx, xs, ys, groups[k], min_n)
        res['direction'], res['reversed'], res['direction_changed'] = verdict(full_tau, res['tau'])
        batches.append((k, res))
    full = {
        'n': ctx['n'], 'n_batches': len(order),
        'concordant': ctx['P'], 'discordant': ctx['Q'],
        'tie_pairs_x': ctx['n1'], 'tie_pairs_y': ctx['n2'],
        'tau': full_tau, 'flags': full_flags, 'direction': direction(full_tau),
    }
    return {'full': full, 'batches': batches}
