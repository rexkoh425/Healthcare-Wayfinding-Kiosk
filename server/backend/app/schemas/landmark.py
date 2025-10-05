from pydantic import BaseModel, Field
from app.schemas.base import PyObjectId

class Landmark(BaseModel):
    id: PyObjectId = Field(alias="_id")
    name: str
    floor: int
    building: str
    image_url: str
    is_destination: bool

    model_config = {
        "validate_by_name": True,
        "json_encoders": {PyObjectId: str},
    }
