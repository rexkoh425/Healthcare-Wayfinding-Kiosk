from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from app.db.mongo import searchlog_col, landmarks_col
from app.schemas.search_log import SearchLogEntry

router = APIRouter(prefix="/stats", tags=["Stats"])

@router.post("/search/{landmark_id}", response_model=SearchLogEntry)
def log_search(landmark_id: str):
    if not ObjectId.is_valid(landmark_id):
        raise HTTPException(400, "Invalid ObjectId")

    # ensure the landmark exists
    oid = ObjectId(landmark_id)
    if not landmarks_col.count_documents({"_id": oid}):
        raise HTTPException(404, "Landmark not found")

    entry = {"landmark_id": oid, "searched_at": datetime.now()}

    try:
        res = searchlog_col.insert_one(entry)
    except DuplicateKeyError:
        # one-per-timestamp
        raise HTTPException(409, "Duplicate search")

    entry["_id"] = res.inserted_id
    return entry

@router.get("/weekly_top4")
def weekly_top4():
    """
    Exactly 7 days ago, top-4 most searched landmarks.
    """
    target_date = (datetime.now() - timedelta(days=7)).date()
    pipeline = [
        { "$addFields": { "search_date": { "$dateToString": { "format": "%Y-%m-%d", "date": "$searched_at" }}}},
        { "$match": { "search_date": target_date.isoformat() }},
        { "$group": { "_id": "$landmark_id", "search_count": { "$sum": 1 }}},
        { "$sort": { "search_count": -1 }},
        { "$limit": 4 },
        { "$lookup": {
            "from": "landmarks",
            "localField": "_id",
            "foreignField": "_id",
            "as": "landmark"
        }},
        { "$unwind": "$landmark" },
        { "$project": {
            "_id": 0,
            "landmark_id": {"$toString": "$_id"},
            "name": "$landmark.name",
            "search_count": 1
        }}
    ]
    return {
        "date": target_date.isoformat(),
        "top4": list(searchlog_col.aggregate(pipeline))
    }

@router.get("/hourly")
def hourly_stats():
    """
    Searches in the last full hour, grouped by landmark.
    """
    one_hour_ago = datetime.now() - timedelta(hours=1)
    pipeline = [
        { "$match": { "searched_at": { "$gte": one_hour_ago } } },
        { "$group": { "_id": "$landmark_id", "search_count": { "$sum": 1 } } },
        { "$sort": { "search_count": -1 } },
        { "$lookup": {
            "from": "landmarks",
            "localField": "_id",
            "foreignField": "_id",
            "as": "landmark"
        }},
        { "$unwind": "$landmark" },
        { "$project": {
            "_id": 0,
            "landmark_id": {"$toString": "$_id"},
            "name": "$landmark.name",
            "search_count": 1
        }}
    ]
    return {
        "from": one_hour_ago.isoformat(),
        "to": datetime.now().isoformat(),
        "stats": list(searchlog_col.aggregate(pipeline))
    }
