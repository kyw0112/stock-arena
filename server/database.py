"""
Stock Arena - Database Module
SQLite + aiosqlite for async operations
"""

import aiosqlite
import os
from datetime import datetime

DB_PATH = os.environ.get("SA_DB_PATH", "stock_arena.db")

SCHEMA = """
-- 유저
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT UNIQUE NOT NULL,
    nickname TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    is_approved INTEGER DEFAULT 0,
    ip_address TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 허용 IP 목록
CREATE TABLE IF NOT EXISTS allowed_ips (
    ip TEXT PRIMARY KEY,
    memo TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 종목 마스터
CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL
);

-- 종가 히스토리
CREATE TABLE IF NOT EXISTS prices (
    stock_code TEXT NOT NULL,
    date TEXT NOT NULL,
    close_price REAL NOT NULL,
    PRIMARY KEY (stock_code, date)
);

-- 포트폴리오 (월별)
CREATE TABLE IF NOT EXISTS portfolios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stock_code TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_price REAL NOT NULL DEFAULT 0,
    month TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, stock_code, month)
);

-- 현금 잔고 (월별)
CREATE TABLE IF NOT EXISTS balances (
    user_id INTEGER NOT NULL,
    month TEXT NOT NULL,
    cash REAL NOT NULL DEFAULT 100000000,
    PRIMARY KEY (user_id, month),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 주문
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stock_code TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK(order_type IN ('BUY','SELL')),
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','FILLED','CANCELLED')),
    ordered_at TEXT DEFAULT (datetime('now','localtime')),
    filled_price REAL,
    filled_at TEXT,
    fee REAL DEFAULT 0,
    tax REAL DEFAULT 0,
    month TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 일별 스냅샷
CREATE TABLE IF NOT EXISTS daily_snapshots (
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    total_value REAL NOT NULL,
    cash REAL NOT NULL,
    return_rate REAL NOT NULL,
    month TEXT NOT NULL,
    PRIMARY KEY (user_id, date, month),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 거래 로그
CREATE TABLE IF NOT EXISTS trade_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stock_code TEXT NOT NULL,
    trade_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL,
    traded_at TEXT DEFAULT (datetime('now','localtime')),
    month TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 게시판
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT '자유',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    likes INTEGER DEFAULT 0,
    dislikes INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 댓글
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (post_id) REFERENCES posts(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 방's pick (방장 게시판)
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 1 CHECK(importance BETWEEN 1 AND 3),
    call_date TEXT NOT NULL,
    call_time TEXT,
    stock_codes TEXT,
    direction TEXT CHECK(direction IN ('매수','매도','관망','중립')),
    likes INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- pick 댓글
CREATE TABLE IF NOT EXISTS pick_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (pick_id) REFERENCES picks(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 추천/비추 기록
CREATE TABLE IF NOT EXISTS post_votes (
    user_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    vote_type TEXT NOT NULL CHECK(vote_type IN ('like','dislike')),
    PRIMARY KEY (user_id, post_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

-- 베팅
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    options TEXT NOT NULL,
    deadline TEXT NOT NULL,
    result TEXT,
    status TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','SETTLED')),
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (creator_id) REFERENCES users(id)
);

-- 베팅 참여
CREATE TABLE IF NOT EXISTS bet_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    chosen_option TEXT NOT NULL,
    points INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (bet_id) REFERENCES bets(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(bet_id, user_id)
);

-- 포인트 잔고
CREATE TABLE IF NOT EXISTS point_balances (
    user_id INTEGER PRIMARY KEY,
    points INTEGER NOT NULL DEFAULT 1000,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 출석 체크
CREATE TABLE IF NOT EXISTS attendance (
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    points_awarded INTEGER NOT NULL DEFAULT 100,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 일일 활동 카운트 (게시글/댓글 포인트 제한)
CREATE TABLE IF NOT EXISTS daily_activity (
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date, activity_type),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 가위바위보 게임
CREATE TABLE IF NOT EXISTS rps_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    player_choice TEXT NOT NULL CHECK(player_choice IN ('rock','paper','scissors')),
    computer_choice TEXT NOT NULL CHECK(computer_choice IN ('rock','paper','scissors')),
    result TEXT NOT NULL CHECK(result IN ('win','lose','draw')),
    wager INTEGER NOT NULL,
    payout INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 포인트 선물
CREATE TABLE IF NOT EXISTS point_gifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    message TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (from_user_id) REFERENCES users(id),
    FOREIGN KEY (to_user_id) REFERENCES users(id)
);

-- 주사위 게임방
CREATE TABLE IF NOT EXISTS dice_rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('HIGH','LOW')),
    dice_min INTEGER NOT NULL DEFAULT 1,
    dice_max INTEGER NOT NULL DEFAULT 10,
    entry_fee INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'WAITING',
    current_round INTEGER NOT NULL DEFAULT 0,
    winner_id INTEGER,
    total_pot INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    finished_at TEXT,
    FOREIGN KEY (creator_id) REFERENCES users(id)
);

-- 주사위 참가자
CREATE TABLE IF NOT EXISTS dice_players (
    room_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    is_ready INTEGER DEFAULT 0,
    is_alive INTEGER DEFAULT 1,
    eliminated_round INTEGER,
    joined_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (room_id, user_id),
    FOREIGN KEY (room_id) REFERENCES dice_rooms(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 주사위 라운드별 기록
CREATE TABLE IF NOT EXISTS dice_rolls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    roll_value INTEGER NOT NULL,
    eliminated INTEGER DEFAULT 0,
    FOREIGN KEY (room_id) REFERENCES dice_rooms(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 주사위 통계 (칭호용)
CREATE TABLE IF NOT EXISTS dice_stats (
    user_id INTEGER PRIMARY KEY,
    total_games INTEGER NOT NULL DEFAULT 0,
    total_wins INTEGER NOT NULL DEFAULT 0,
    current_win_streak INTEGER NOT NULL DEFAULT 0,
    max_win_streak INTEGER NOT NULL DEFAULT 0,
    current_loss_streak INTEGER NOT NULL DEFAULT 0,
    max_loss_streak INTEGER NOT NULL DEFAULT 0,
    total_earned INTEGER NOT NULL DEFAULT 0,
    total_lost INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 가챠 뽑기 기록
CREATE TABLE IF NOT EXISTS gacha_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    spin_number INTEGER NOT NULL DEFAULT 1,
    grade TEXT NOT NULL CHECK(grade IN ('MISS','SMALL','MEDIUM','JACKPOT')),
    points_won INTEGER NOT NULL DEFAULT 0,
    cost INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 포인트 가감 내역 (트랜잭션 로그)
CREATE TABLE IF NOT EXISTS point_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    source TEXT NOT NULL,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Nordle 퍼즐 (하루 하나, 전원 공통)
CREATE TABLE IF NOT EXISTS nordle_puzzles (
    date TEXT PRIMARY KEY,
    equation TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- Nordle 게임 기록
CREATE TABLE IF NOT EXISTS nordle_games (
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    guesses TEXT NOT NULL DEFAULT '[]',
    solved INTEGER DEFAULT 0,
    finished_at TEXT,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 잭팟 풀
CREATE TABLE IF NOT EXISTS jackpot_pool (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    amount INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO jackpot_pool (id, amount) VALUES (1, 0);

-- 해피아워
CREATE TABLE IF NOT EXISTS happy_hour (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    start_time TEXT,
    end_time TEXT
);
INSERT OR IGNORE INTO happy_hour (id) VALUES (1);

-- 배지 (닭대가리 등)
CREATE TABLE IF NOT EXISTS user_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_user_id INTEGER NOT NULL,
    sender_user_id INTEGER NOT NULL,
    badge_type TEXT NOT NULL DEFAULT 'chicken',
    expires_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (target_user_id) REFERENCES users(id),
    FOREIGN KEY (sender_user_id) REFERENCES users(id)
);

-- 전광판 (시스템 알림 티커)
CREATE TABLE IF NOT EXISTS ticker_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 채팅 메시지
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'user' CHECK(msg_type IN ('user','system')),
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        # 기본 관리자 계정 (사번: admin, 비번: admin)
        from auth import hash_password
        admin_hash = hash_password("admin")
        await db.execute(
            """INSERT OR IGNORE INTO users (employee_id, nickname, password_hash, is_admin, is_approved)
               VALUES (?, ?, ?, 1, 1)""",
            ("admin", "관리자", admin_hash)
        )
        await db.commit()
    finally:
        await db.close()


def current_month():
    return datetime.now().strftime("%Y-%m")


INITIAL_SEED = 100_000_000  # 1억
FEE_RATE = 0.00015  # 0.015%
TAX_RATE = 0.002    # 0.2% (매도시)
