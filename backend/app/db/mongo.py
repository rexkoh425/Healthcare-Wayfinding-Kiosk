import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ——— MongoDB setup ———
MONGODB_URI = os.environ["MONGODB_URI"]
client = MongoClient(MONGODB_URI)
db = client["cde"]

landmarks_col = db["landmarks"]
routes_col = db["routes"]
searchlog_col = db["search_log"]

# ensure unique index on (landmark_id, searched_at)
def setup_indexes():
    searchlog_col.create_index(
        [("landmark_id", 1), ("searched_at", 1)],
        unique=True
    )
