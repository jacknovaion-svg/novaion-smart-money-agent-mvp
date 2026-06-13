from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.wallet import Wallet
from app.schemas.auth import CurrentUser
from app.schemas.wallet import WalletCreate, WalletRead, WalletUpdate
from app.services.system_log_service import write_log


router = APIRouter(prefix="/wallets", tags=["wallets"])


@router.get("", response_model=list[WalletRead])
def list_wallets(
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[Wallet]:
    query = db.query(Wallet)
    if not include_deleted:
        query = query.filter(Wallet.status != "deleted")
    return query.order_by(Wallet.created_at.desc()).all()


@router.post("", response_model=WalletRead, status_code=status.HTTP_201_CREATED)
def create_wallet(
    payload: WalletCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> Wallet:
    wallet = Wallet(**payload.model_dump())
    db.add(wallet)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Wallet address already exists")
    db.refresh(wallet)
    write_log(
        db,
        level="info",
        module="wallets",
        message="Wallet created",
        payload={"wallet_id": wallet.id, "address": wallet.address},
    )
    return wallet


@router.get("/{wallet_id}", response_model=WalletRead)
def get_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> Wallet:
    wallet = db.get(Wallet, wallet_id)
    if not wallet or wallet.status == "deleted":
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet


@router.put("/{wallet_id}", response_model=WalletRead)
def update_wallet(
    wallet_id: int,
    payload: WalletUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> Wallet:
    wallet = db.get(Wallet, wallet_id)
    if not wallet or wallet.status == "deleted":
        raise HTTPException(status_code=404, detail="Wallet not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(wallet, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Wallet address already exists")
    db.refresh(wallet)
    write_log(
        db,
        level="info",
        module="wallets",
        message="Wallet updated",
        payload={"wallet_id": wallet.id},
    )
    return wallet


@router.delete("/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> None:
    wallet = db.get(Wallet, wallet_id)
    if not wallet or wallet.status == "deleted":
        raise HTTPException(status_code=404, detail="Wallet not found")
    wallet.status = "deleted"
    db.commit()
    write_log(
        db,
        level="warning",
        module="wallets",
        message="Wallet deleted",
        payload={"wallet_id": wallet.id},
    )
