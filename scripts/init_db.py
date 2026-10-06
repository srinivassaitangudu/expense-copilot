from app.db import Base, engine
import app.models
Base.metadata.create_all(engine)
print("database initialized")
