from datetime import datetime,timezone
import hashlib,json
def now(): return datetime.now(timezone.utc).isoformat()
def record(obj):
    from sqlalchemy import inspect  # 延迟载入，保证无ORM环境可复用checksum
    return {c.key:getattr(obj,c.key) for c in inspect(obj).mapper.column_attrs}
def checksum(value): return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
