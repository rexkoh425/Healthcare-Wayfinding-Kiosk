from datetime import datetime
from pydantic import BaseModel, Field
from app.schemas.base import PyObjectId

class SearchLogEntry(BaseModel):
    id: PyObjectId = Field(alias="_id")
    landmark_id: PyObjectId
    searched_at: datetime

    model_config = {
        "validate_by_name": True,
        "json_encoders": {PyObjectId: str},
    }
