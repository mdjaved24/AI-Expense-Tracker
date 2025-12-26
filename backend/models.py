from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from database import Base

from sqlalchemy import DateTime
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)

    transactions = relationship("Transaction", backref="user")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User")



class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    amount = Column(Float, nullable=False)

    type = Column(String, nullable=False)  # 'credit' or 'debit'

    category = Column(String, nullable=False)

    description = Column(String, nullable=True)

    transaction_date = Column(Date, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("type IN ('credit', 'debit')", name="check_transaction_type"),
    )

    
