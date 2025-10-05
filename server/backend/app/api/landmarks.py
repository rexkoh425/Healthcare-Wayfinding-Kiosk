from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from app.schemas.landmark import Landmark
from app.db.mongo import landmarks_col

router = APIRouter(prefix="/landmarks", tags=["Landmarks"])

@router.get("/", response_model=List[Landmark])
def list_landmarks(
    name: Optional[str] = Query(
        None,
        title="Landmark name",
        description="If provided, only landmarks whose name matches (case-insensitive) will be returned"
    )
):
    # build the Mongo filter
    mongo_filter = {}
    if name:
        # exact match, case-insensitive; change to regex or partial match if you want
        mongo_filter["name"] = {"$regex": f"^{name}$", "$options": "i"}

    # no projection → return the full Landmark document
    docs = list(landmarks_col.find(mongo_filter))
    return docs
