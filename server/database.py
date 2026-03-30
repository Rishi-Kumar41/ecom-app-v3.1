from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

##SQLALCHEMY_DATABASE_URL = "sqlite:///./ecom.db"

SQLALCHEMY_DATABASE_URL = "postgresql://rikumar:Password%40123@localhost:5432/ecom_db"

#engine = create_engine(
  #  SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
#)
#SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
#Base = declarative_base()

engine = create_engine(
    SQLALCHEMY_DATABASE_URL
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
