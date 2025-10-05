from fastapi import APIRouter, Query, HTTPException
from typing import List
from bson import ObjectId
from app.schemas.route import Route
from app.db.mongo import routes_col, landmarks_col

router = APIRouter(prefix="/routes", tags=["Routes"])

@router.get("/", response_model=List[Route])
def get_routes_by_landmark_names(
    start_name: str = Query(..., title="Start landmark name"),
    end_name:   str = Query(..., title="End landmark name"),
):
    """
    Fetch all routes whose start_location has name `start_name`
    and end_location has name `end_name` (both case-insensitive).
    """
    # 1) look up the two landmark ObjectIds
    start_doc = landmarks_col.find_one(
        {"name": {"$regex": f"^{start_name}$", "$options": "i"}},
        {"_id": 1}
    )
    if not start_doc:
        raise HTTPException(404, detail=f"Start landmark '{start_name}' not found")

    end_doc = landmarks_col.find_one(
        {"name": {"$regex": f"^{end_name}$", "$options": "i"}},
        {"_id": 1}
    )
    if not end_doc:
        raise HTTPException(404, detail=f"End landmark '{end_name}' not found")

    start_id = start_doc["_id"]
    end_id   = end_doc["_id"]

    # 2) query routes using those ObjectIds
    route_docs = list(routes_col.find({
        "start_location": start_id,
        "end_location":   end_id
    }))

    if not route_docs:
        # no matching routes → 404 or just return empty list; here I choose empty
        return []

    return route_docs
