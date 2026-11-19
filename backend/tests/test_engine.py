"""分阶段计数引擎测试：断点续跑、重试幂等、齐全才开放、快照校验。"""
import json
import random
import sqlite3
import unittest

from src.services import joint_engine, kendall


class SqliteRepo:
    """引擎 repo 协议的标准库实现（对应生产 SQLAlchemy 仓储）。"""

    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
            CREATE TABLE runs(id INTEGER PRIMARY KEY, checksum TEXT, status TEXT, result TEXT);
            CREATE TABLE rows(run_id INT, ord INT, study_id INT, source_key TEXT, x REAL, y REAL);
            CREATE TABLE batches(run_id INT, study_id INT);
            CREATE TABLE results(run_id INT, study_id INT, payload TEXT, PRIMARY KEY(run_id, study_id));
            CREATE TABLE checkpoints(run_id INT, stage TEXT, payload TEXT, PRIMARY KEY(run_id, stage));
        ''')

    def add_run(self, run_id, batch_keys, min_n, rows):
        ck = joint_engine.payload_checksum(batch_keys, min_n, rows)
        self.db.execute('INSERT INTO runs VALUES(?,?,?,?)', (run_id, ck, 'queued', None))
        self.db.executemany('INSERT INTO rows VALUES(?,?,?,?,?,?)',
                            [(run_id, i, *r) for i, r in enumerate(rows)])
        self.db.executemany('INSERT INTO batches VALUES(?,?)', [(run_id, b) for b in batch_keys])
        self.db.commit()

    # ---- 引擎 repo 协议 ----
    def load_rows(self, run_id):
        return self.db.execute('SELECT study_id, source_key, x, y FROM rows WHERE run_id=? ORDER BY ord',
                               (run_id,)).fetchall()

    def load_batches(self, run_id):
        return [r[0] for r in self.db.execute('SELECT study_id FROM batches WHERE run_id=? ORDER BY study_id',
                                              (run_id,))]

    def get_checksum(self, run_id):
        return self.db.execute('SELECT checksum FROM runs WHERE id=?', (run_id,)).fetchone()[0]

    def load_global(self, run_id):
        row = self.db.execute('SELECT payload FROM checkpoints WHERE run_id=? AND stage=?',
                              (run_id, 'global')).fetchone()
        return json.loads(row[0]) if row else None

    def save_global(self, run_id, ctx):
        self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',
                        (run_id, 'global', json.dumps(ctx)))
        self.db.commit()

    def completed_batch_keys(self, run_id):
        return {r[0] for r in self.db.execute('SELECT study_id FROM results WHERE run_id=?', (run_id,))}

    def save_batch_results(self, run_id, results):
        self.db.executemany('INSERT OR REPLACE INTO results VALUES(?,?,?)',
                            [(run_id, b, json.dumps(res)) for b, res in results])
        self.db.commit()

    def count_batch_results(self, run_id):
        return self.db.execute('SELECT COUNT(*) FROM results WHERE run_id=?', (run_id,)).fetchone()[0]

    def load_batch_results(self, run_id):
        return [(b, json.loads(p)) for b, p in
                self.db.execute('SELECT study_id, payload FROM results WHERE run_id=?', (run_id,))]

    def finalize(self, run_id, full, summary):
        self.db.execute('UPDATE runs SET status=?, result=? WHERE id=?',
                        ('completed', json.dumps({'full': full, 'summary': summary}), run_id))
        self.db.commit()

    # ---- 测试辅助 ----
    def status(self, run_id):
        return self.db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()[0]

    def result(self, run_id):
        row = self.db.execute('SELECT result FROM runs WHERE id=?', (run_id,)).fetchone()
        return json.loads(row[0]) if row[0] else None

    def corrupt_row(self, run_id):
        self.db.execute('UPDATE rows SET y=y+1 WHERE run_id=? AND ord=0', (run_id,))
        self.db.commit()


def make_dataset(seed=5, n_batches=7):
    rng = random.Random(seed)
    rows, keys = [], []
    for b in range(1, n_batches + 1):
        for n in range(rng.randint(3, 9)):
            rows.append((b, f'K{b}-{n}', rng.randint(0, 6) * 1.0, rng.randint(0, 6) * 1.0))
            keys.append(b)
    return rows, keys


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.keys = make_dataset()
        self.batches = sorted(set(self.keys))
        self.min_n = 3

    def make_repo(self):
        repo = SqliteRepo()
        repo.add_run(1, self.batches, self.min_n, self.rows)
        return repo

    def expected(self):
        xs = [r[2] for r in self.rows]
        ys = [r[3] for r in self.rows]
        return kendall.leave_one_batch_out(xs, ys, self.keys, self.min_n)

    def assert_matches_expected(self, repo):
        exp = self.expected()
        stored = dict(repo.load_batch_results(1))
        self.assertEqual(set(stored), set(self.batches))
        for b, res in exp['batches']:
            got = stored[b]
            self.assertEqual(got['n_removed'], res['n_removed'])
            self.assertEqual(got['n_remaining'], res['n_remaining'])
            self.assertEqual(got['concordant'], res['concordant'])
            self.assertEqual(got['discordant'], res['discordant'])
            self.assertEqual(got['flags'], res['flags'])
            if res['tau'] is None:
                self.assertIsNone(got['tau'])
            else:
                self.assertAlmostEqual(got['tau'], res['tau'], places=12)
        final = repo.result(1)
        self.assertAlmostEqual(final['full']['tau'], exp['full']['tau'], places=12)
        reversed_exp = sorted(b for b, r in exp['batches'] if r['reversed'])
        self.assertEqual(sorted(final['summary']['reversed_batches']), reversed_exp)

    def test_complete_run(self):
        repo = self.make_repo()
        self.assertTrue(joint_engine.execute(repo, 1, self.min_n))
        self.assertEqual(repo.status(1), 'completed')
        self.assert_matches_expected(repo)

    def test_resume_from_confirmed_progress(self):
        repo = self.make_repo()
        commits = []
        orig_save = repo.save_batch_results

        def spy(run_id, chunk):
            orig_save(run_id, chunk)
            commits.append(len(chunk))

        repo.save_batch_results = spy
        calls = {'n': 0}

        def stop(stage, done, total):
            if stage == 'batches':
                calls['n'] += 1
                return calls['n'] >= 2  # 第二个 chunk 提交后中断
            return False

        with self.assertRaises(joint_engine.Interrupted):
            joint_engine.execute(repo, 1, self.min_n, should_stop=stop, chunk_size=2)
        confirmed = repo.count_batch_results(1)
        self.assertEqual(confirmed, 4)  # 两个已提交 chunk
        self.assertNotEqual(repo.status(1), 'completed')  # 未齐全不开放
        # 续跑：从已确认进度继续，不重算已确认批次
        commits.clear()
        self.assertTrue(joint_engine.execute(repo, 1, self.min_n, chunk_size=2))
        self.assertEqual(sum(commits), len(self.batches) - confirmed)
        self.assertEqual(repo.count_batch_results(1), len(self.batches))
        self.assert_matches_expected(repo)

    def test_retry_does_not_double_count(self):
        repo = self.make_repo()
        self.assertTrue(joint_engine.execute(repo, 1, self.min_n, chunk_size=2))
        before = sorted(repo.load_batch_results(1))
        # 重试已完成的任务：幂等，结果不变
        self.assertTrue(joint_engine.execute(repo, 1, self.min_n, chunk_size=2))
        after = sorted(repo.load_batch_results(1))
        self.assertEqual(before, after)
        self.assertEqual(repo.count_batch_results(1), len(self.batches))

    def test_global_checkpoint_survives_crash(self):
        repo = self.make_repo()

        def stop(stage, done, total):
            return stage == 'global'

        with self.assertRaises(joint_engine.Interrupted):
            joint_engine.execute(repo, 1, self.min_n, should_stop=stop)
        self.assertIsNotNone(repo.load_global(1))  # 全体统计已确认
        self.assertEqual(repo.count_batch_results(1), 0)
        self.assertTrue(joint_engine.execute(repo, 1, self.min_n))
        self.assert_matches_expected(repo)

    def test_checksum_guard(self):
        repo = self.make_repo()
        repo.corrupt_row(1)
        with self.assertRaises(ValueError):
            joint_engine.execute(repo, 1, self.min_n)

    def test_empty_batch_still_counted(self):
        # 批次 99 无试件：冻结时仍登记，结果必须齐全才开放
        repo = SqliteRepo()
        batches = self.batches + [99]
        repo.add_run(1, batches, self.min_n, self.rows)  # rows 中无批次 99
        self.assertTrue(joint_engine.execute(repo, 1, self.min_n))
        stored = dict(repo.load_batch_results(1))
        self.assertIn(99, stored)
        self.assertEqual(stored[99]['n_removed'], 0)
        exp = self.expected()
        self.assertAlmostEqual(stored[99]['tau'], exp['full']['tau'], places=12)


if __name__ == '__main__':
    unittest.main()
