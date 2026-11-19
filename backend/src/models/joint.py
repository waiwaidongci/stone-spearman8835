from sqlalchemy import Column,Integer,BigInteger,String,JSON,Text,ForeignKey,Double
from src.config.database import Base

class JointRun(Base):
    """一次联合核算：多批冻结快照 + 逐批剔除敏感性。"""
    __tablename__='joint_runs'
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    status=Column(String(20),default='queued')  # queued/running/completed/failed
    parameters=Column(JSON,nullable=False)      # {'min_n': int}
    checksum=Column(String(64),nullable=False)  # 冻结内容 SHA256
    result=Column(JSON,nullable=True)  # {'full':..,'summary':..}，finalize 时写入
    error=Column(Text,default='')
    n_specimens=Column(Integer,nullable=False)
    n_batches=Column(Integer,nullable=False)
    completed_batches=Column(Integer,default=0)  # 由批次结果表 COUNT 派生更新
    frozen_at=Column(String(40),nullable=False)  # 同一时点冻结
    created_at=Column(String(40),nullable=False)

class JointRunRow(Base):
    """冻结的逐试件测值：创建时复制，之后的更正只影响下次研究。"""
    __tablename__='joint_run_rows'
    id=Column(Integer,primary_key=True)
    run_id=Column(Integer,ForeignKey('joint_runs.id'),nullable=False,index=True)
    study_id=Column(Integer,nullable=False)
    source_key=Column(String(100),nullable=False)
    x=Column(Double,nullable=False)  # 双精度，保证校验和逐位一致
    y=Column(Double,nullable=False)

class JointRunBatch(Base):
    """冻结时登记的批次清单（含空批次）：结果齐全性以此为准。"""
    __tablename__='joint_run_batches'
    run_id=Column(Integer,ForeignKey('joint_runs.id'),primary_key=True)
    study_id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    n_specimens=Column(Integer,nullable=False)

class JointBatchResult(Base):
    """逐批剔除结果：按 (run_id, study_id) 幂等覆盖，重试不重复计入。"""
    __tablename__='joint_batch_results'
    run_id=Column(Integer,ForeignKey('joint_runs.id'),primary_key=True)
    study_id=Column(Integer,primary_key=True)
    n_removed=Column(Integer,nullable=False)
    n_remaining=Column(Integer,nullable=False)
    concordant=Column(BigInteger,nullable=False)
    discordant=Column(BigInteger,nullable=False)
    tau=Column(Double,nullable=True)  # 余样不足/常量时为 NULL
    flags=Column(JSON,nullable=False)  # ['insufficient','constant_x','constant_y'] 子集
    computed_at=Column(String(40),nullable=False)

class JointCheckpoint(Base):
    """分阶段检查点：global 阶段保存全体统计，中断后免于重算。"""
    __tablename__='joint_checkpoints'
    run_id=Column(Integer,ForeignKey('joint_runs.id'),primary_key=True)
    stage=Column(String(20),primary_key=True)
    payload=Column(JSON,nullable=False)
    updated_at=Column(String(40),nullable=False)
