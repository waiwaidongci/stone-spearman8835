import os,time,json,logging
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from src.config.database import Session
from src.models.run import Run
from src.models.joint import JointRun
from src.models import user,study,observation,review,audit
from src.services.algorithm import calculate
from src.services import joint
from src.utils.serializers import checksum
redis=Redis.from_url(os.environ['REDIS_URL'])
Path('/app/artifacts').mkdir(exist_ok=True)
# Recover jobs interrupted after dequeue. A project runs exactly one worker.
# 联合核算中断后同样重投：引擎从检查点与已确认批次结果续跑，重试不重复计入。
with Session() as db:
    pending=list(db.scalars(select(Run).where(Run.status.in_(['queued','running']))))
    for run in pending: redis.rpush('analysis-queue',run.id)
    pending_joint=list(db.scalars(select(JointRun).where(JointRun.status.in_(['queued','running']))))
    for run in pending_joint: redis.rpush('analysis-queue',f'joint:{run.id}')
def process_run(id):
    with Session() as db:
        run=db.get(Run,id)
        if not run or run.status in ('completed','failed'): return
        run.status='running';db.commit()
        try:
            if checksum(run.snapshot)!=run.checksum: raise ValueError('输入快照校验失败')
            result=calculate(run.snapshot,run.parameters)
            result['input_sha256']=run.checksum
            run.result=result;run.status='completed'
            Path(f'/app/artifacts/run-{id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
        except Exception as e:
            logging.exception('analysis failed');run.status='failed';run.error=str(e)
        db.commit()
def process_joint(id):
    with Session() as db:
        run=db.get(JointRun,id)
        if not run or run.status in ('completed','failed'): return
        run.status='running';db.commit()
        try:
            payload=joint.process(db,id)
            Path(f'/app/artifacts/joint-{id}.json').write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False))
        except Exception as e:
            logging.exception('joint analysis failed');run.status='failed';run.error=str(e)[:2000]
        db.commit()
while True:
    Path('/tmp/worker-heartbeat').touch()
    job=redis.blpop('analysis-queue',timeout=2)
    if not job: continue
    raw=job[1].decode()
    if raw.startswith('joint:'):
        process_joint(int(raw.split(':',1)[1]))
    else:
        process_run(int(raw))
