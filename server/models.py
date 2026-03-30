"""
Stock Arena - Pydantic Models
"""

from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime


# ── Auth ──────────────────────────────────────
class RegisterRequest(BaseModel):
    employee_id: str
    nickname: str
    password: str

class LoginRequest(BaseModel):
    employee_id: str
    password: str

class TokenResponse(BaseModel):
    token: str
    user_id: int
    nickname: str
    is_admin: bool

# ── Trading ───────────────────────────────────
class OrderRequest(BaseModel):
    stock_code: str
    order_type: str  # BUY or SELL
    quantity: int

class PriceInputRequest(BaseModel):
    date: str
    prices: Dict[str, float]  # {"005930": 58700, ...}

# ── Board ─────────────────────────────────────
class PostCreateRequest(BaseModel):
    category: str = "자유"
    title: str
    content: str

class CommentCreateRequest(BaseModel):
    content: str

class VoteRequest(BaseModel):
    vote_type: str  # "like" or "dislike"

# ── Picks (방's pick) ─────────────────────────
class PickCreateRequest(BaseModel):
    title: str
    content: str
    importance: int = 1  # 1~3 (★~★★★)
    call_date: str       # "2026-03-20"
    call_time: Optional[str] = None  # "15:30"
    stock_codes: Optional[str] = None  # "005930,000660"
    direction: Optional[str] = None  # 매수/매도/관망/중립

# ── Betting ───────────────────────────────────
class BetCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    options: List[str]
    deadline: str  # "2026-03-25 18:00"

class BetEntryRequest(BaseModel):
    chosen_option: str
    points: int

class BetSettleRequest(BaseModel):
    result: str

# ── Nordle ────────────────────────────────────
class NordleGuessRequest(BaseModel):
    guess: str

class NordlePuzzleRequest(BaseModel):
    equation: str
    date: Optional[str] = None

# ── RPS (가위바위보) ─────────────────────────
class RPSPlayRequest(BaseModel):
    choice: str   # rock, paper, scissors
    wager: int

# ── Point Gift ───────────────────────────────
class PointGiftRequest(BaseModel):
    to_nickname: str
    amount: int
    message: Optional[str] = None

# ── Dice (주사위 게임) ──────────────────────────
class DiceRoomCreateRequest(BaseModel):
    mode: str = "HIGH"          # 레거시 호환
    dice_min: int = 1
    dice_max: int = 6
    entry_fee: int

# ── Chat (채팅) ──────────────────────────────
class ChatSendRequest(BaseModel):
    message: str

# ── Shop (상점) ──────────────────────────────
class ShopChickenRequest(BaseModel):
    target_nickname: str

# ── Admin ─────────────────────────────────────
class IPApproveRequest(BaseModel):
    ip: str
    memo: str = ""

class UserApproveRequest(BaseModel):
    user_id: int
    approved: bool

class AdminPointAdjustRequest(BaseModel):
    user_id: int
    amount: int  # 양수=지급, 음수=차감
    reason: str
