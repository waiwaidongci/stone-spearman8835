"""联合核算服务：多批冻结、逐批剔除结果、断点续跑、齐全才开放查看。"""
import os
from redis import Redis
from sqlalchemy import select,func,insert
from fastapi import HTTPException
from src.config.domain import DOMAIN
from src.models.joint import JointRun,JointRunRow,JointRunBatch,JointBatchResult,JointCheckpoint
from src.models.observation import Observation
from src.models.study import Study
from src.services import joint_engine,kendall
from src.services.domain_validation import validate_joint_parameters
from src.services.audits import log
from src.utils.serializers import record,now

FIELDS=[f[0] for f in DOMAIN['fields'] if f[2]=='number'][:2]  # 本域为 porosity/absorption

def _queue():
    return Redis.from_url(os.environ['REDIS_URL'])

class Repo:
    """joint_engine 的 SQLAlchemy 仓储：检查点与批次结果即"已确认进度"。"""
    def __init__(self,db): self.db=db
    def load_rows(self,run_id):
        return [(r.study_id,r.source_key,r.x,r.y) for r in self.db.scalars(
            select(JointRunRow).where(JointRunRow.run_id==run_id).order_by(JointRunRow.id))]
    def load_batches(self,run_id):
        return list(self.db.scalars(select(JointRunBatch.study_id).where(JointRunBatch.run_id==run_id).order_by(JointRunBatch.study_id)))
    def get_checksum(self,run_id):
        return self.db.get(JointRun,run_id).checksum
    def load_global(self,run_id):
        cp=self.db.get(JointCheckpoint,(run_id,'global'))
        return cp.payload if cp else None
    def save_global(self,run_id,ctx):
        self.db.merge(JointCheckpoint(run_id=run_id,stage='global',payload=ctx,updated_at=now()))
        self.db.commit()
    def completed_batch_keys(self,run_id):
        return set(self.db.scalars(select(JointBatchResult.study_id).where(JointBatchResult.run_id==run_id)))
    def save_batch_results(self,run_id,results):
        t=now()
        for study_id,res in results:
            self.db.merge(JointBatchResult(run_id=run_id,study_id=study_id,n_removed=res['n_removed'],
                n_remaining=res['n_remaining'],concordant=res['concordant'],discordant=res['discordant'],
                tau=res['tau'],flags=res['flags'],computed_at=t))
        run=self.db.get(JointRun,run_id)
        run.completed_batches=self.count_batch_results(run_id)  # 进度由 COUNT 派生，重试不重复计入
        self.db.commit()
    def count_batch_results(self,run_id):
        return self.db.scalar(select(func.count()).select_from(JointBatchResult).where(JointBatchResult.run_id==run_id))
    def load_batch_results(self,run_id):
        return [(r.study_id,{'n_removed':r.n_removed,'n_remaining':r.n_remaining,'concordant':r.concordant,
            'discordant':r.discordant,'tau':r.tau,'flags':r.flags}) for r in self.db.scalars(
            select(JointBatchResult).where(JointBatchResult.run_id==run_id))]
    def finalize(self,run_id,full,summary):
        run=self.db.get(JointRun,run_id)
        run.result={'full':full,'summary':summary}
        run.completed_batches=full['n_batches']
        run.status='completed'
        self.db.commit()

def _frozen_rows(study_ids,db):
    """同一事务内读取所选批次当前测值——并发更正只会进入下次研究。"""
    rows=db.scalars(select(Observation).where(Observation.study_id.in_(study_ids)).order_by(Observation.study_id,Observation.id)).all()
    return [[o.study_id,o.source_key,float(o.values[FIELDS[0]]),float(o.values[FIELDS[1]])] for o in rows]

def create(db,data,user):
    ids=sorted(set(data.study_ids))
    if len(ids)<2: raise HTTPException(422,'联合核算至少选择两个材料批次')
    found={s.id:s for s in db.scalars(select(Study).where(Study.id.in_(ids)))}
    missing=[i for i in ids if i not in found]
    if missing: raise HTTPException(404,'材料批次不存在: '+','.join(map(str,missing)))
    try: params=validate_joint_parameters(data.parameters)
    except (ValueError,TypeError) as e: raise HTTPException(422,str(e))
    frozen=_frozen_rows(ids,db)
    if len(frozen)<2: raise HTTPException(422,'所选批次观测总数不足，无法核算')
    run=JointRun(name=data.name,status='queued',parameters=params,
        checksum=joint_engine.payload_checksum(ids,params['min_n'],frozen),
        n_specimens=len(frozen),n_batches=len(ids),completed_batches=0,frozen_at=now(),created_at=now())
    db.add(run);db.flush()
    counts={}
    for f in frozen: counts[f[0]]=counts.get(f[0],0)+1
    db.add_all([JointRunBatch(run_id=run.id,study_id=s,name=found[s].name,n_specimens=counts.get(s,0)) for s in ids])
    payload=[{'run_id':run.id,'study_id':f[0],'source_key':f[1],'x':f[2],'y':f[3]} for f in frozen]
    for i in range(0,len(payload),5000):
        db.execute(insert(JointRunRow),payload[i:i+5000])
    log(db,user,'joint.queue',f'{run.id}: {len(ids)}批/{len(frozen)}件')
    db.commit()
    _queue().rpush('analysis-queue',f'joint:{run.id}')
    return record(run)

def list_runs(db):
    return [record(r) for r in db.scalars(select(JointRun).order_by(JointRun.id.desc()))]

def get(db,id):
    run=db.get(JointRun,id)
    if not run: raise HTTPException(404,'联合核算不存在')
    result=record(run)
    result['completed_batches']=Repo(db).count_batch_results(id)
    batches=db.scalars(select(JointRunBatch).where(JointRunBatch.run_id==id).order_by(JointRunBatch.study_id)).all()
    result['batches']=[record(b) for b in batches]
    # 冻结后源数据是否又被更正：更正不改写本次快照，只体现在下次研究。
    # 全量比对代价 O(n)，仅在终态时计算，避免计数期间被轮询拖垮。
    if run.status in ('completed','failed'):
        current=_frozen_rows([b.study_id for b in batches],db)
        result['source_changed']=joint_engine.payload_checksum([b.study_id for b in batches],run.parameters['min_n'],current)!=run.checksum
    else:
        result['source_changed']=None
    return result

def results(db,id):
    """所有批次结果齐全才开放查看。"""
    run=db.get(JointRun,id)
    if not run: raise HTTPException(404,'联合核算不存在')
    repo=Repo(db)
    done=repo.count_batch_results(id)
    if run.status!='completed' or done!=run.n_batches or not run.result:
        raise HTTPException(409,f'逐批结果尚未齐全（{done}/{run.n_batches}），所有批次完成后才开放查看')
    full=run.result['full'];summary=run.result['summary']
    names={b.study_id:b.name for b in db.scalars(select(JointRunBatch).where(JointRunBatch.run_id==id))}
    batches=[]
    for study_id,res in repo.load_batch_results(id):
        direction,reversed_,changed=kendall.verdict(full['tau'],res['tau'])
        batches.append({'study_id':study_id,'batch_name':names.get(study_id,str(study_id)),**res,
            'direction':direction,'reversed':reversed_,'direction_changed':changed})
    batches.sort(key=lambda b:(not b['reversed'],not b['direction_changed'],b['study_id']))
    tau_text='未定义' if full['tau'] is None else f"{full['tau']:.4f}"
    interpretation=(f"全样本 {full['n']} 件 / {full['n_batches']} 批，精确 Kendall τ-b={tau_text}（{_direction_label(full['direction'])}）。"
        f"逐批剔除后，{summary['reversed_count']} 批会使结论反向"
        + (f"：{', '.join(names.get(b,str(b)) for b in summary['reversed_batches'])}。" if summary['reversed_count'] else '。')
        + f"另有 {summary['changed_count']-summary['reversed_count']} 批使方向发生变化（含归零）。")
    return {'run':record(run),'full':full,'summary':summary,'batches':batches,
        'interpretation':interpretation,
        'caveat':'τ-b 保留并列修正；余样不足或余样为常量的批次已标明，其 τ 不定义。相关关系只支持后续假设，不解释为因果；不能据此挑选或删改试件。'}

def _direction_label(d):
    return {'positive':'正向','negative':'负向','zero':'零相关'}.get(d,'未定义')

def resume(db,id,user):
    """失败/中断后续跑：已确认进度保留，重试不重复计入。"""
    run=db.get(JointRun,id)
    if not run: raise HTTPException(404,'联合核算不存在')
    if run.status=='completed': raise HTTPException(409,'已完成，无需续跑')
    if run.status=='running': raise HTTPException(409,'正在计算中；若 worker 已停止，请稍后再试')
    run.status='queued';run.error=''
    log(db,user,'joint.resume',str(id))
    db.commit()
    _queue().rpush('analysis-queue',f'joint:{id}')
    return record(run)

def process(db,id):
    """worker 入口：执行/续跑，返回可归档的结果载荷。"""
    run=db.get(JointRun,id)
    if not run: raise ValueError('联合核算不存在')
    ok=joint_engine.execute(Repo(db),id,run.parameters['min_n'])
    if not ok: raise RuntimeError('批次结果未齐全')
    return results(db,id)
