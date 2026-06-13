from datetime import datetime

from pydantic import BaseModel


class SystemLogRead(BaseModel):
    id: int
    level: str
    module: str
    message: str
    payload_json: str
    created_at: datetime

    model_config = {"from_attributes": True}
