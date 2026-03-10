# server/create_tables.py
from database import Base, engine  # import from your database.py

# This will create all tables defined in your models
Base.metadata.create_all(bind=engine)

print("Tables created successfully in PostgreSQL")