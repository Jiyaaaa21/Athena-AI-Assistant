from backend.database.db import engine
from backend.database.models import Base

Base.metadata.create_all(bind=engine)

print("Database created")