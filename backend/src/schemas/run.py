from pydantic import BaseModel,Field
class CorrelationRunInput(BaseModel):
    study_id:int=Field(gt=0)
    name:str=Field(min_length=2,max_length=120)
    parameters:dict=Field(default_factory=dict)
RunInput=CorrelationRunInput
class JointRunInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    study_ids:list[int]=Field(min_length=2)
    parameters:dict=Field(default_factory=dict)
