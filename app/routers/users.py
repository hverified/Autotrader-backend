# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from datetime import timedelta, datetime

from app.database import users_collection
from app.models.user_model import (
    UserCreate,
    UserResponse,
    UserLogin,
    Token,
    UserUpdate,
    PasswordChange,
    UserInDB,
)
from app.utils.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_active_user,
    get_current_admin_user,
)
from app.config import settings

router = APIRouter()


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register_user(user: UserCreate):
    """Register a new user"""
    # Check if user already exists
    existing_user = await users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    existing_username = await users_collection.find_one({"username": user.username})
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken"
        )

    # Create new user
    hashed_password = get_password_hash(user.password)
    user_in_db = UserInDB(
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        phone_number=user.phone_number,
        hashed_password=hashed_password,
    )

    # Insert into MongoDB
    user_dict = user_in_db.dict()
    result = await users_collection.insert_one(user_dict)

    # Get the created user
    created_user = await users_collection.find_one({"_id": result.inserted_id})

    # Remove sensitive data and _id
    created_user.pop("hashed_password", None)
    created_user.pop("_id", None)

    return UserResponse(**created_user)


@router.post("/login", response_model=Token)
async def login(user_credentials: UserLogin):
    """Login and get access token"""
    user = await users_collection.find_one({"email": user_credentials.email})

    if not user or not verify_password(
        user_credentials.password, user["hashed_password"]
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    # Update last login
    await users_collection.update_one(
        {"email": user_credentials.email}, {"$set": {"last_login": datetime.utcnow()}}
    )

    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_active_user)):
    """Get current user information"""
    # Remove sensitive data
    current_user.pop("hashed_password", None)
    current_user.pop("_id", None)

    return UserResponse(**current_user)


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate, current_user: dict = Depends(get_current_active_user)
):
    """Update current user information"""
    update_data = {}

    if user_update.full_name is not None:
        update_data["full_name"] = user_update.full_name

    if user_update.phone_number is not None:
        update_data["phone_number"] = user_update.phone_number

    if user_update.broker_name is not None:
        update_data["broker_name"] = user_update.broker_name

    if user_update.broker_api_key is not None:
        update_data["broker_api_key"] = user_update.broker_api_key

    if user_update.broker_api_secret is not None:
        update_data["broker_api_secret"] = user_update.broker_api_secret

    # Enable trading if broker credentials are provided
    if user_update.broker_api_key and user_update.broker_api_secret:
        update_data["trading_enabled"] = True

    update_data["updated_at"] = datetime.utcnow()

    # Update in MongoDB
    await users_collection.update_one(
        {"email": current_user["email"]}, {"$set": update_data}
    )

    # Get updated user
    updated_user = await users_collection.find_one({"email": current_user["email"]})
    updated_user.pop("hashed_password", None)
    updated_user.pop("_id", None)

    return UserResponse(**updated_user)


@router.post("/change-password")
async def change_password(
    password_change: PasswordChange,
    current_user: dict = Depends(get_current_active_user),
):
    """Change user password"""
    if not verify_password(
        password_change.old_password, current_user["hashed_password"]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect password"
        )

    new_hashed_password = get_password_hash(password_change.new_password)

    await users_collection.update_one(
        {"email": current_user["email"]},
        {
            "$set": {
                "hashed_password": new_hashed_password,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    return {"message": "Password changed successfully"}


@router.delete("/me")
async def delete_current_user(current_user: dict = Depends(get_current_active_user)):
    """Delete current user account"""
    await users_collection.delete_one({"email": current_user["email"]})

    return {"message": "User account deleted successfully"}


# Admin routes
@router.get("/all", response_model=List[UserResponse])
async def get_all_users(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_admin_user),
):
    """Get all users (Admin only)"""
    cursor = users_collection.find().skip(skip).limit(limit)
    users = await cursor.to_list(length=limit)

    # Remove sensitive data
    for user in users:
        user.pop("hashed_password", None)
        user.pop("_id", None)

    return [UserResponse(**user) for user in users]


@router.get("/{username}", response_model=UserResponse)
async def get_user_by_username(
    username: str, current_user: dict = Depends(get_current_admin_user)
):
    """Get user by username (Admin only)"""
    user = await users_collection.find_one({"username": username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    user.pop("hashed_password", None)
    user.pop("_id", None)

    return UserResponse(**user)


@router.put("/{username}/toggle-active")
async def toggle_user_active(
    username: str, current_user: dict = Depends(get_current_admin_user)
):
    """Toggle user active status (Admin only)"""
    user = await users_collection.find_one({"username": username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    new_status = not user.get("is_active", True)

    await users_collection.update_one(
        {"username": username},
        {"$set": {"is_active": new_status, "updated_at": datetime.utcnow()}},
    )

    return {
        "message": f"User {'activated' if new_status else 'deactivated'} successfully"
    }


@router.delete("/{username}")
async def delete_user(
    username: str, current_user: dict = Depends(get_current_admin_user)
):
    """Delete user (Admin only)"""
    user = await users_collection.find_one({"username": username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    await users_collection.delete_one({"username": username})

    return {"message": "User deleted successfully"}
