from sqlalchemy import create_engine, Date, Text, Column, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import os

engine = create_engine(os.environ.get('DATABASE_URL'), echo=True, pool_recycle=True)


Base = declarative_base()


class Deadline(Base):
    __tablename__ = 'deadlines_perform'
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    item = Column(Text, nullable=False)
    abstract_date = Column(Date, nullable=True)
    old_date = Column(Date, nullable=True)


class ResponseDeadline(Base):
    __tablename__ = 'response_deadlines_perform'
    id = Column(Integer, primary_key=True)
    item = Column(Text, nullable=False)
    early_response_date = Column(Date, nullable=True)
    notification_date = Column(Date, nullable=True)


Session = sessionmaker(bind=engine)


if __name__ == '__main__':
    # Create the table for the first time
    Deadline.__table__.create(engine)
    ResponseDeadline.__table__.create(engine)