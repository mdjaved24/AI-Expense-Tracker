from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy import Integer
from sqlalchemy.orm import Session
import models, schemas
from database import SessionLocal, engine
from auth import hash_password, verify_password, create_access_token, get_current_user

from fastapi import File, UploadFile
import os
import pandas as pd

models.Base.metadata.create_all(bind=engine)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="User Auth API")

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