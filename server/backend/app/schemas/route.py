from typing import List
from pydantic import BaseModel, Field
from app.schemas.base import PyObjectId

class LandmarkTimestamp(BaseModel):
    landmark: PyObjectId
    time: int                # seconds into the video
    description: str

    model_config = {
        "json_encoders": {PyObjectId: str},
    }

class Route(BaseModel):
    id: PyObjectId = Field(alias="_id")
    start_location: PyObjectId
    end_location: PyObjectId
    is_wheelchair_accessible: bool
    video_url: str
    duration_seconds: int
    walking_time_minutes: int
    landmark_timestamps: List[LandmarkTimestamp]

    model_config = {
        "validate_by_name": True,
        "json_encoders": {PyObjectId: str},
    }
