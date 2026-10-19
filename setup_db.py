"""Creates collections, validation rules, indexes and default sources in MongoDB.

Usage:  python setup_db.py
(The app also does this automatically on startup.)
"""
from app.database import get_database, setup_database

if __name__ == "__main__":
    db = get_database()
    setup_database(db)
    print(f"MongoDB ready: database '{db.name}'")
    for name in db.list_collection_names():
        print(f"  - {name}: {db[name].count_documents({})} documents, indexes: {list(db[name].index_information())}")
