from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy import Integer
from sqlalchemy.orm import Session
import models, schemas
from database import SessionLocal, engine
from auth import hash_password, verify_password, create_access_token, get_current_user

from fastapi import File, UploadFile
import os
import pandas as pd
from datetime import datetime

from typing import Optional
from datetime import date
from fastapi import Query


from fastapi.middleware.cors import CORSMiddleware


models.Base.metadata.create_all(bind=engine)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="User Auth API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ Register
@app.post("/register", response_model=schemas.UserResponse)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing_username = db.query(models.User).filter(models.User.username == user.username).first()
    existing_email = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already exists")
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already exists")

    new_user = models.User(
        name=user.name,
        username=user.username,
        email=user.email,
        hashed_password=hash_password(user.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# ✅ Login
@app.post("/login")
def login(user: schemas.UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    token = create_access_token({"sub": db_user.email})
    return {"access_token": token, "token_type": "bearer"}


# ✅ Upload CSV
@app.post("/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files allowed")

    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    new_file = models.UploadedFile(
        filename=file.filename,
        owner_id=current_user.id
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return {
        "message": "File uploaded successfully",
        "filename": file.filename,
        "uploaded_by": current_user.username
    }

@app.get("/read-csv/{id}")
def read_own_csv(
    id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file_record = db.query(models.UploadedFile).filter(
        models.UploadedFile.id == id,
        models.UploadedFile.owner_id == current_user.id
    ).first()

    if not file_record:
        raise HTTPException(status_code=403, detail="Access denied")

    filename = file_record.filename
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Read CSV
    df = pd.read_csv(file_path)
    
    # METHOD 1: Use fillna with explicit dtype conversion
    df = df.fillna(0)  # Fill numeric NaN with 0
    df = df.fillna("")  # Fill any remaining NaN with empty string
    
    # Convert all columns to Python native types
    for col in df.columns:
        if df[col].dtype == 'float64':
            df[col] = df[col].astype(float)
        elif df[col].dtype == 'int64':
            df[col] = df[col].astype(int)
    
    return {
        "file_id": id,
        "filename": filename,
        "rows": len(df),
        "columns": list(df.columns),
        "data": df.to_dict(orient="records")
    }

# ✅ Upload Transactions via CSV
@app.post("/upload-transactions-csv")
async def upload_transactions_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files allowed")

    try:
        df = pd.read_csv(file.file)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid CSV file")

    required_cols = {"amount", "type", "category", "description", "transaction_date"}
    if not required_cols.issubset(df.columns):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain columns: {required_cols}"
        )

    transactions = []
    for idx, row in df.iterrows():
        tx_type = str(row["type"]).lower()
        if tx_type not in ("credit", "debit"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid type at row {idx + 2}. Must be credit/debit"
            )

        try:
            tx_date = pd.to_datetime(row["transaction_date"]).date()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date at row {idx + 2}. Use YYYY-MM-DD"
            )

        tx = models.Transaction(
            user_id=current_user.id,
            amount=float(row["amount"]),
            type=tx_type,
            category=str(row["category"]),
            description=str(row.get("description", "")),
            transaction_date=tx_date
        )
        transactions.append(tx)

    db.add_all(transactions)
    db.commit()

    return {
        "message": "Transactions imported successfully",
        "count": len(transactions)
    }



#✅ Get Transactions with Filters
@app.get("/my-transactions")
def get_my_transactions(
    type: Optional[str] = Query(None, regex="^(credit|debit)$"),
    category: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    )

    if type:
        query = query.filter(models.Transaction.type == type)

    if category:
        query = query.filter(models.Transaction.category.ilike(f"%{category}%"))

    if start_date:
        query = query.filter(models.Transaction.transaction_date >= start_date)

    if end_date:
        query = query.filter(models.Transaction.transaction_date <= end_date)

    if min_amount is not None:
        query = query.filter(models.Transaction.amount >= min_amount)

    if max_amount is not None:
        query = query.filter(models.Transaction.amount <= max_amount)

    results = query.order_by(models.Transaction.transaction_date.desc()).all()
    return results

