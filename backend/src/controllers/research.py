from src.services import studies,runs,joint
# Controllers keep endpoint contracts separate from persistence and calculation.
def overview(db): return {'studies':studies.list_studies(db),'runs':runs.list_runs(db)}
def create_study(db,data,user): return studies.create(db,data,user)
def list_rows(db,id): return studies.observations(db,id)
def save_row(db,id,data,user,row_id=None): return studies.save_observation(db,id,data,user,row_id)
def create_run(db,data,user): return runs.create(db,data,user)
def review_run(db,id,data,user): return runs.approve(db,id,data,user)
def create_joint_run(db,data,user): return joint.create(db,data,user)
def resume_joint_run(db,id,user): return joint.resume(db,id,user)
