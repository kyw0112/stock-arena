"""
Stock Arena - Main Application
FastAPI server with all API endpoints

실행: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import asyncio
import json
import os
import pathlib
import re
import random
import shutil
from datetime import datetime as dt, timedelta

from database import get_db, init_db, current_month, INITIAL_SEED, FEE_RATE, TAX_RATE
from auth import hash_password, verify_password, create_token, decode_token
from models import *


# ── App Setup ─────────────────────────────────

PRICE_DATA_DIR = pathlib.Path(__file__).parent / "price_data"
PRICE_DONE_DIR = PRICE_DATA_DIR / "done"


async def process_price_file(filepath: pathlib.Path):
    """price_data/ 폴더의 JSON 파일을 읽어 종가 입력 + 체결 처리"""
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        date = data["date"]
        prices = data["prices"]
        month = date[:7]

        db = await get_db()
        try:
            settled_count = 0

            # 1. 종가 저장
            for code, price in prices.items():
                await db.execute(
                    "INSERT OR REPLACE INTO prices (stock_code, date, close_price) VALUES (?, ?, ?)",
                    (code, date, price)
                )

            # 2. PENDING 주문 체결
            pending = await db.execute_fetchall(
                "SELECT * FROM orders WHERE status = 'PENDING' AND month = ?", (month,)
            )

            for order in pending:
                stock_code = order["stock_code"]
                if stock_code not in prices:
                    continue

                price = prices[stock_code]
                uid = order["user_id"]
                qty = order["quantity"]
                otype = order["order_type"]

                bal = await db.execute_fetchall(
                    "SELECT cash FROM balances WHERE user_id = ? AND month = ?", (uid, month)
                )
                if not bal:
                    await db.execute(
                        "INSERT INTO balances (user_id, month, cash) VALUES (?, ?, ?)",
                        (uid, month, INITIAL_SEED)
                    )
                    cash = INITIAL_SEED
                else:
                    cash = bal[0]["cash"]

                if otype == "BUY":
                    cost = price * qty
                    fee = cost * FEE_RATE
                    total_cost = cost + fee

                    if cash < total_cost:
                        await db.execute(
                            "UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (order["id"],)
                        )
                        continue

                    cash -= total_cost
                    await db.execute(
                        "UPDATE balances SET cash = ? WHERE user_id = ? AND month = ?",
                        (cash, uid, month)
                    )

                    existing = await db.execute_fetchall(
                        "SELECT quantity, avg_price FROM portfolios WHERE user_id = ? AND stock_code = ? AND month = ?",
                        (uid, stock_code, month)
                    )
                    if existing:
                        old_qty = existing[0]["quantity"]
                        old_avg = existing[0]["avg_price"]
                        new_qty = old_qty + qty
                        new_avg = ((old_avg * old_qty) + (price * qty)) / new_qty if new_qty > 0 else 0
                        await db.execute(
                            "UPDATE portfolios SET quantity = ?, avg_price = ? WHERE user_id = ? AND stock_code = ? AND month = ?",
                            (new_qty, new_avg, uid, stock_code, month)
                        )
                    else:
                        await db.execute(
                            "INSERT INTO portfolios (user_id, stock_code, quantity, avg_price, month) VALUES (?, ?, ?, ?, ?)",
                            (uid, stock_code, qty, price, month)
                        )

                    await db.execute(
                        "INSERT INTO trade_logs (user_id, stock_code, trade_type, quantity, price, fee, tax, total_amount, month) VALUES (?, ?, 'BUY', ?, ?, ?, 0, ?, ?)",
                        (uid, stock_code, qty, price, fee, total_cost, month)
                    )

                elif otype == "SELL":
                    revenue = price * qty
                    fee = revenue * FEE_RATE
                    tax = revenue * TAX_RATE
                    net = revenue - fee - tax

                    existing = await db.execute_fetchall(
                        "SELECT quantity, avg_price FROM portfolios WHERE user_id = ? AND stock_code = ? AND month = ?",
                        (uid, stock_code, month)
                    )
                    if not existing or existing[0]["quantity"] < qty:
                        await db.execute(
                            "UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (order["id"],)
                        )
                        continue

                    new_qty = existing[0]["quantity"] - qty
                    await db.execute(
                        "UPDATE portfolios SET quantity = ? WHERE user_id = ? AND stock_code = ? AND month = ?",
                        (new_qty, uid, stock_code, month)
                    )

                    cash += net
                    await db.execute(
                        "UPDATE balances SET cash = ? WHERE user_id = ? AND month = ?",
                        (cash, uid, month)
                    )

                    await db.execute(
                        "INSERT INTO trade_logs (user_id, stock_code, trade_type, quantity, price, fee, tax, total_amount, month) VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?)",
                        (uid, stock_code, qty, price, fee, tax, net, month)
                    )

                await db.execute(
                    "UPDATE orders SET status = 'FILLED', filled_price = ?, filled_at = ?, fee = ?, tax = ? WHERE id = ?",
                    (price, date, fee if otype == "BUY" else fee, tax if otype == "SELL" else 0, order["id"])
                )
                settled_count += 1

            # 3. 일별 스냅샷
            users = await db.execute_fetchall(
                "SELECT id FROM users WHERE is_approved = 1 AND is_admin = 0"
            )
            for u in users:
                uid = u["id"]
                bal = await db.execute_fetchall(
                    "SELECT cash FROM balances WHERE user_id = ? AND month = ?", (uid, month)
                )
                cash_val = bal[0]["cash"] if bal else INITIAL_SEED

                ports = await db.execute_fetchall(
                    "SELECT stock_code, quantity FROM portfolios WHERE user_id = ? AND month = ? AND quantity > 0",
                    (uid, month)
                )
                total_eval = 0
                for p in ports:
                    pr = await db.execute_fetchall(
                        "SELECT close_price FROM prices WHERE stock_code = ? ORDER BY date DESC LIMIT 1",
                        (p["stock_code"],)
                    )
                    if pr:
                        total_eval += pr[0]["close_price"] * p["quantity"]

                total = cash_val + total_eval
                rate = ((total / INITIAL_SEED) - 1) * 100

                await db.execute(
                    "INSERT OR REPLACE INTO daily_snapshots (user_id, date, total_value, cash, return_rate, month) VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, date, total, cash_val, round(rate, 2), month)
                )

            if settled_count > 0:
                await insert_ticker(db, f"📊 {date} 매매가 체결되었습니다 ({settled_count}건)", "trade")
            await check_eval_leader_change(db, month)
            await check_point_leader_change(db)

            await db.commit()
            print(f"[price_scan] {filepath.name} 처리 완료: 종가 {len(prices)}건, 체결 {settled_count}건")
        finally:
            await db.close()

        # 처리 완료 → done/ 으로 이동
        PRICE_DONE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(filepath), str(PRICE_DONE_DIR / filepath.name))

    except Exception as e:
        print(f"[price_scan] {filepath.name} 처리 실패: {e}")


async def price_folder_scanner():
    """30초마다 price_data/ 폴더를 스캔하여 JSON 파일 처리"""
    while True:
        await asyncio.sleep(60)
        if not PRICE_DATA_DIR.exists():
            continue
        for f in sorted(PRICE_DATA_DIR.glob("*.json")):
            if f.is_file():
                await process_price_file(f)


@asynccontextmanager
async def lifespan(app):
    await init_db()
    PRICE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(price_folder_scanner())
    yield
    task.cancel()

app = FastAPI(title="Stock Arena", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth Dependency ───────────────────────────

async def get_current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "인증이 필요합니다")
    payload = decode_token(auth[7:])
    if not payload:
        raise HTTPException(401, "토큰이 만료되었거나 유효하지 않습니다")
    return payload

async def get_admin_user(request: Request):
    user = await get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "관리자 권한이 필요합니다")
    return user

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Point Transaction Helper ─────────────────

async def log_point_change(db, user_id: int, amount: int, source: str, description: str = None):
    """포인트 변경 + 트랜잭션 로그 기록. amount는 양수(증가) 또는 음수(감소)."""
    await db.execute(
        "UPDATE point_balances SET points = points + ? WHERE user_id = ?",
        (amount, user_id)
    )
    rows = await db.execute_fetchall(
        "SELECT points FROM point_balances WHERE user_id = ?", (user_id,)
    )
    balance_after = rows[0]["points"] if rows else 0
    await db.execute(
        "INSERT INTO point_transactions (user_id, amount, balance_after, source, description) VALUES (?,?,?,?,?)",
        (user_id, amount, balance_after, source, description)
    )
    return balance_after


async def get_user_badge_str(db, user_id: int) -> str:
    """유저의 현재 배지 문자열 생성 (왕관 + 닭)"""
    # 포인트 1위 체크
    leader = await db.execute_fetchall(
        """SELECT pb.user_id FROM point_balances pb
           JOIN users u ON pb.user_id = u.id
           WHERE u.is_approved = 1 AND u.is_admin = 0
           ORDER BY pb.points DESC LIMIT 1"""
    )
    is_leader = leader and leader[0]["user_id"] == user_id

    # 유효한 닭 수
    chickens = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM user_badges WHERE target_user_id = ? AND badge_type = 'chicken' AND expires_at > datetime('now','localtime')",
        (user_id,),
    )
    chicken_count = chickens[0]["cnt"] if chickens else 0

    badge = ""
    if is_leader:
        badge += "👑"
    if chicken_count > 0:
        badge += "🐔" * chicken_count
    return badge


# ═══════════════════════════════════════════════
# AUTH API
# ═══════════════════════════════════════════════

@app.post("/api/auth/register")
async def register(req: RegisterRequest, request: Request):
    db = await get_db()
    try:
        # 중복 체크
        row = await db.execute_fetchall(
            "SELECT id FROM users WHERE employee_id = ?", (req.employee_id,)
        )
        if row:
            raise HTTPException(400, "이미 등록된 사번입니다")

        pw_hash = hash_password(req.password)
        client_ip = get_client_ip(request)

        cursor = await db.execute(
            """INSERT INTO users (employee_id, nickname, password_hash, ip_address, is_approved)
               VALUES (?, ?, ?, ?, 0)""",
            (req.employee_id, req.nickname, pw_hash, client_ip)
        )
        user_id = cursor.lastrowid

        # 초기 포인트
        await db.execute(
            "INSERT INTO point_balances (user_id, points) VALUES (?, 1000)",
            (user_id,)
        )
        await db.execute(
            "INSERT INTO point_transactions (user_id, amount, balance_after, source, description) VALUES (?,?,?,?,?)",
            (user_id, 1000, 1000, "회원가입", "초기 지급")
        )
        await db.commit()
        return {"message": "가입 완료. 관리자 승인을 기다려주세요.", "user_id": user_id}
    finally:
        await db.close()


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM users WHERE employee_id = ?", (req.employee_id,)
        )
        if not rows:
            raise HTTPException(401, "사번 또는 비밀번호가 틀렸습니다")

        user = dict(rows[0])
        if not verify_password(req.password, user["password_hash"]):
            raise HTTPException(401, "사번 또는 비밀번호가 틀렸습니다")

        client_ip = get_client_ip(request)

        # IP 체크 (관리자는 면제)
        if not user["is_admin"]:
            # 허용 IP 목록 확인
            ips = await db.execute_fetchall("SELECT ip FROM allowed_ips")
            allowed = {row["ip"] for row in ips}
            if allowed and client_ip not in allowed:
                # IP 저장해두기 (관리자가 승인할 수 있도록)
                await db.execute(
                    "UPDATE users SET ip_address = ? WHERE id = ?",
                    (client_ip, user["id"])
                )
                await db.commit()
                raise HTTPException(403, f"허용되지 않은 IP입니다 ({client_ip}). 관리자에게 문의하세요.")

            if not user["is_approved"]:
                raise HTTPException(403, "관리자 승인 대기 중입니다")

        # IP 업데이트
        await db.execute(
            "UPDATE users SET ip_address = ? WHERE id = ?",
            (client_ip, user["id"])
        )
        await db.commit()

        token = create_token({
            "user_id": user["id"],
            "employee_id": user["employee_id"],
            "nickname": user["nickname"],
            "is_admin": bool(user["is_admin"]),
        })

        return TokenResponse(
            token=token,
            user_id=user["id"],
            nickname=user["nickname"],
            is_admin=bool(user["is_admin"])
        )
    finally:
        await db.close()


@app.get("/api/auth/me")
async def get_me(user=Depends(get_current_user)):
    return user


# ═══════════════════════════════════════════════
# STOCKS API
# ═══════════════════════════════════════════════

@app.get("/api/stocks/search")
async def search_stocks(q: str = "", user=Depends(get_current_user)):
    if len(q) < 1:
        return []
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT code, name, market FROM stocks WHERE name LIKE ? OR code LIKE ? LIMIT 20",
            (f"%{q}%", f"%{q}%")
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/stocks/{code}")
async def get_stock(code: str, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT code, name, market FROM stocks WHERE code = ?", (code,)
        )
        if not rows:
            raise HTTPException(404, "종목을 찾을 수 없습니다")
        stock = dict(rows[0])

        # 최신 종가
        price_rows = await db.execute_fetchall(
            "SELECT close_price, date FROM prices WHERE stock_code = ? ORDER BY date DESC LIMIT 1",
            (code,)
        )
        if price_rows:
            stock["last_price"] = price_rows[0]["close_price"]
            stock["last_date"] = price_rows[0]["date"]
        return stock
    finally:
        await db.close()


@app.get("/api/stocks/{code}/prices")
async def get_stock_prices(code: str, limit: int = 30, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT date, close_price FROM prices WHERE stock_code = ? ORDER BY date DESC LIMIT ?",
            (code, limit)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# TRADING API
# ═══════════════════════════════════════════════

@app.post("/api/orders")
async def create_order(req: OrderRequest, user=Depends(get_current_user)):
    if req.order_type not in ("BUY", "SELL"):
        raise HTTPException(400, "BUY 또는 SELL만 가능합니다")
    if req.quantity <= 0:
        raise HTTPException(400, "수량은 1 이상이어야 합니다")

    user_id = user["user_id"]
    month = current_month()
    db = await get_db()

    try:
        # 종목 존재 확인
        stock = await db.execute_fetchall(
            "SELECT code FROM stocks WHERE code = ?", (req.stock_code,)
        )
        if not stock:
            raise HTTPException(404, "존재하지 않는 종목입니다")

        # 매도인 경우 보유 수량 확인
        if req.order_type == "SELL":
            port = await db.execute_fetchall(
                "SELECT quantity FROM portfolios WHERE user_id = ? AND stock_code = ? AND month = ?",
                (user_id, req.stock_code, month)
            )
            held = port[0]["quantity"] if port else 0

            # PENDING 매도 주문 합산
            pending = await db.execute_fetchall(
                """SELECT COALESCE(SUM(quantity), 0) as total FROM orders
                   WHERE user_id = ? AND stock_code = ? AND order_type = 'SELL'
                   AND status = 'PENDING' AND month = ?""",
                (user_id, req.stock_code, month)
            )
            pending_qty = pending[0]["total"] if pending else 0

            if held - pending_qty < req.quantity:
                raise HTTPException(400, f"매도 가능 수량 부족 (보유: {held}, 매도대기: {pending_qty})")

        # 주문 등록
        await db.execute(
            """INSERT INTO orders (user_id, stock_code, order_type, quantity, status, month)
               VALUES (?, ?, ?, ?, 'PENDING', ?)""",
            (user_id, req.stock_code, req.order_type, req.quantity, month)
        )
        await db.commit()
        return {"message": f"{req.order_type} 주문 등록 완료 (종가 체결 대기)"}
    finally:
        await db.close()


@app.get("/api/orders")
async def get_orders(status: str = "PENDING", user=Depends(get_current_user)):
    db = await get_db()
    try:
        month = current_month()
        rows = await db.execute_fetchall(
            """SELECT o.*, s.name as stock_name FROM orders o
               LEFT JOIN stocks s ON o.stock_code = s.code
               WHERE o.user_id = ? AND o.status = ? AND o.month = ?
               ORDER BY o.ordered_at DESC""",
            (user["user_id"], status, month)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.delete("/api/orders/{order_id}")
async def cancel_order(order_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM orders WHERE id = ? AND user_id = ? AND status = 'PENDING'",
            (order_id, user["user_id"])
        )
        if not rows:
            raise HTTPException(404, "취소할 수 있는 주문이 없습니다")
        await db.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (order_id,))
        await db.commit()
        return {"message": "주문 취소 완료"}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# PORTFOLIO API
# ═══════════════════════════════════════════════

@app.get("/api/portfolio")
async def get_portfolio(user=Depends(get_current_user)):
    db = await get_db()
    try:
        user_id = user["user_id"]
        month = current_month()

        # 잔고 확인 (없으면 초기화)
        bal = await db.execute_fetchall(
            "SELECT cash FROM balances WHERE user_id = ? AND month = ?",
            (user_id, month)
        )
        if not bal:
            await db.execute(
                "INSERT INTO balances (user_id, month, cash) VALUES (?, ?, ?)",
                (user_id, month, INITIAL_SEED)
            )
            await db.commit()
            cash = INITIAL_SEED
        else:
            cash = bal[0]["cash"]

        # 보유 종목
        rows = await db.execute_fetchall(
            """SELECT p.stock_code, p.quantity, p.avg_price, s.name as stock_name
               FROM portfolios p
               LEFT JOIN stocks s ON p.stock_code = s.code
               WHERE p.user_id = ? AND p.month = ? AND p.quantity > 0
               ORDER BY s.name""",
            (user_id, month)
        )
        holdings = []
        total_eval = 0
        for r in rows:
            item = dict(r)
            # 최신 종가
            price_rows = await db.execute_fetchall(
                "SELECT close_price FROM prices WHERE stock_code = ? ORDER BY date DESC LIMIT 1",
                (r["stock_code"],)
            )
            cur_price = price_rows[0]["close_price"] if price_rows else item["avg_price"]
            item["current_price"] = cur_price
            item["eval_amount"] = cur_price * item["quantity"]
            item["profit_amount"] = (cur_price - item["avg_price"]) * item["quantity"]
            item["profit_rate"] = ((cur_price / item["avg_price"]) - 1) * 100 if item["avg_price"] > 0 else 0
            total_eval += item["eval_amount"]
            holdings.append(item)

        total_value = cash + total_eval
        return_rate = ((total_value / INITIAL_SEED) - 1) * 100

        return {
            "cash": cash,
            "total_eval": total_eval,
            "total_value": total_value,
            "return_rate": round(return_rate, 2),
            "initial_seed": INITIAL_SEED,
            "month": month,
            "holdings": holdings,
        }
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# RANKINGS API
# ═══════════════════════════════════════════════

async def _calculate_monthly_rankings(db, month: str) -> list:
    """월간 랭킹 계산 헬퍼 (db 커넥션 재사용)"""
    users = await db.execute_fetchall(
        "SELECT id, nickname, employee_id FROM users WHERE is_approved = 1 AND is_admin = 0"
    )
    rankings = []
    for u in users:
        uid = u["id"]
        bal = await db.execute_fetchall(
            "SELECT cash FROM balances WHERE user_id = ? AND month = ?", (uid, month)
        )
        cash = bal[0]["cash"] if bal else INITIAL_SEED

        ports = await db.execute_fetchall(
            "SELECT stock_code, quantity, avg_price FROM portfolios WHERE user_id = ? AND month = ? AND quantity > 0",
            (uid, month)
        )
        total_eval = 0
        for p in ports:
            pr = await db.execute_fetchall(
                "SELECT close_price FROM prices WHERE stock_code = ? ORDER BY date DESC LIMIT 1",
                (p["stock_code"],)
            )
            price = pr[0]["close_price"] if pr else p["avg_price"]
            total_eval += price * p["quantity"]

        total = cash + total_eval
        rate = ((total / INITIAL_SEED) - 1) * 100

        badge = await get_user_badge_str(db, uid)
        rankings.append({
            "user_id": uid,
            "nickname": u["nickname"],
            "badge": badge,
            "total_value": round(total),
            "return_rate": round(rate, 2),
            "cash": round(cash),
            "holdings_count": len(ports),
        })

    rankings.sort(key=lambda x: x["return_rate"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1
    return rankings


@app.get("/api/rankings/monthly")
async def get_monthly_rankings(month: str = "", user=Depends(get_current_user)):
    if not month:
        month = current_month()
    db = await get_db()
    try:
        rankings = await _calculate_monthly_rankings(db, month)
        return {"month": month, "rankings": rankings}
    finally:
        await db.close()


@app.get("/api/rankings/cumulative")
async def get_cumulative_rankings(user=Depends(get_current_user)):
    db = await get_db()
    try:
        users = await db.execute_fetchall(
            "SELECT id, nickname FROM users WHERE is_approved = 1 AND is_admin = 0"
        )
        rankings = []
        for u in users:
            # 모든 월 스냅샷의 마지막 날 수익률
            snapshots = await db.execute_fetchall(
                """SELECT month, return_rate FROM daily_snapshots
                   WHERE user_id = ? GROUP BY month
                   HAVING date = MAX(date) ORDER BY month""",
                (u["id"],)
            )
            months_played = len(snapshots)
            avg_return = sum(s["return_rate"] for s in snapshots) / months_played if months_played > 0 else 0
            best = max((s["return_rate"] for s in snapshots), default=0)
            worst = min((s["return_rate"] for s in snapshots), default=0)
            wins = sum(1 for s in snapshots if s["return_rate"] > 0)

            badge = await get_user_badge_str(db, u["id"])
            rankings.append({
                "user_id": u["id"],
                "nickname": u["nickname"],
                "badge": badge,
                "months_played": months_played,
                "avg_return": round(avg_return, 2),
                "best_return": round(best, 2),
                "worst_return": round(worst, 2),
                "win_rate": round((wins / months_played) * 100, 1) if months_played > 0 else 0,
            })

        rankings.sort(key=lambda x: x["avg_return"], reverse=True)
        for i, r in enumerate(rankings):
            r["rank"] = i + 1

        return {"rankings": rankings}
    finally:
        await db.close()


@app.get("/api/rankings/daily")
async def get_daily_rankings(date: str = "", user=Depends(get_current_user)):
    db = await get_db()
    try:
        if date:
            rows = await db.execute_fetchall(
                """SELECT ds.*, u.nickname FROM daily_snapshots ds
                   JOIN users u ON ds.user_id = u.id
                   WHERE ds.date = ? ORDER BY ds.return_rate DESC""",
                (date,)
            )
        else:
            # 가장 최근 날짜
            latest = await db.execute_fetchall(
                "SELECT MAX(date) as d FROM daily_snapshots"
            )
            if not latest or not latest[0]["d"]:
                return {"date": "", "snapshots": []}
            date = latest[0]["d"]
            rows = await db.execute_fetchall(
                """SELECT ds.*, u.nickname FROM daily_snapshots ds
                   JOIN users u ON ds.user_id = u.id
                   WHERE ds.date = ? ORDER BY ds.return_rate DESC""",
                (date,)
            )
        return {"date": date, "snapshots": [dict(r) for r in rows]}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# ADMIN API
# ═══════════════════════════════════════════════

@app.get("/api/admin/users")
async def admin_list_users(user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT id, employee_id, nickname, is_approved, is_admin, ip_address, created_at
               FROM users ORDER BY created_at DESC"""
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.post("/api/admin/users/approve")
async def admin_approve_user(req: UserApproveRequest, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET is_approved = ? WHERE id = ?",
            (1 if req.approved else 0, req.user_id)
        )
        await db.commit()
        return {"message": f"유저 {'승인' if req.approved else '차단'} 완료"}
    finally:
        await db.close()


@app.get("/api/admin/ips")
async def admin_list_ips(user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM allowed_ips ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.post("/api/admin/ips")
async def admin_add_ip(req: IPApproveRequest, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO allowed_ips (ip, memo) VALUES (?, ?)",
            (req.ip, req.memo)
        )
        await db.commit()
        return {"message": f"IP {req.ip} 허용 등록"}
    finally:
        await db.close()


@app.delete("/api/admin/ips/{ip}")
async def admin_remove_ip(ip: str, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        await db.execute("DELETE FROM allowed_ips WHERE ip = ?", (ip,))
        await db.commit()
        return {"message": f"IP {ip} 삭제"}
    finally:
        await db.close()


@app.get("/api/admin/pending-stocks")
async def admin_pending_stocks(user=Depends(get_admin_user)):
    """현재 보유중인 종목 + 대기 주문 종목 → 종가 입력 필요 목록"""
    db = await get_db()
    try:
        month = current_month()
        rows = await db.execute_fetchall(
            """SELECT DISTINCT s.code, s.name FROM (
                 SELECT stock_code FROM portfolios WHERE month = ? AND quantity > 0
                 UNION
                 SELECT stock_code FROM orders WHERE month = ? AND status = 'PENDING'
               ) AS needed
               JOIN stocks s ON needed.stock_code = s.code
               ORDER BY s.name""",
            (month, month)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.post("/api/admin/prices")
async def admin_input_prices(req: PriceInputRequest, user=Depends(get_admin_user)):
    """종가 JSON 입력 + 체결 처리"""
    db = await get_db()
    try:
        date = req.date
        month = date[:7]  # "2026-03-20" → "2026-03"
        settled_count = 0

        # 1. 종가 저장
        for code, price in req.prices.items():
            await db.execute(
                "INSERT OR REPLACE INTO prices (stock_code, date, close_price) VALUES (?, ?, ?)",
                (code, date, price)
            )

        # 2. PENDING 주문 체결
        pending = await db.execute_fetchall(
            "SELECT * FROM orders WHERE status = 'PENDING' AND month = ?", (month,)
        )

        for order in pending:
            stock_code = order["stock_code"]
            if stock_code not in req.prices:
                continue  # 이 종목 종가 없으면 스킵

            price = req.prices[stock_code]
            uid = order["user_id"]
            qty = order["quantity"]
            otype = order["order_type"]

            # 잔고 확인/생성
            bal = await db.execute_fetchall(
                "SELECT cash FROM balances WHERE user_id = ? AND month = ?", (uid, month)
            )
            if not bal:
                await db.execute(
                    "INSERT INTO balances (user_id, month, cash) VALUES (?, ?, ?)",
                    (uid, month, INITIAL_SEED)
                )
                cash = INITIAL_SEED
            else:
                cash = bal[0]["cash"]

            if otype == "BUY":
                cost = price * qty
                fee = cost * FEE_RATE
                total_cost = cost + fee

                if cash < total_cost:
                    await db.execute(
                        "UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (order["id"],)
                    )
                    continue

                # 현금 차감
                cash -= total_cost
                await db.execute(
                    "UPDATE balances SET cash = ? WHERE user_id = ? AND month = ?",
                    (cash, uid, month)
                )

                # 포트폴리오 업데이트
                existing = await db.execute_fetchall(
                    "SELECT quantity, avg_price FROM portfolios WHERE user_id = ? AND stock_code = ? AND month = ?",
                    (uid, stock_code, month)
                )
                if existing:
                    old_qty = existing[0]["quantity"]
                    old_avg = existing[0]["avg_price"]
                    new_qty = old_qty + qty
                    new_avg = ((old_avg * old_qty) + (price * qty)) / new_qty if new_qty > 0 else 0
                    await db.execute(
                        "UPDATE portfolios SET quantity = ?, avg_price = ? WHERE user_id = ? AND stock_code = ? AND month = ?",
                        (new_qty, new_avg, uid, stock_code, month)
                    )
                else:
                    await db.execute(
                        "INSERT INTO portfolios (user_id, stock_code, quantity, avg_price, month) VALUES (?, ?, ?, ?, ?)",
                        (uid, stock_code, qty, price, month)
                    )

                # 거래 로그
                await db.execute(
                    "INSERT INTO trade_logs (user_id, stock_code, trade_type, quantity, price, fee, tax, total_amount, month) VALUES (?, ?, 'BUY', ?, ?, ?, 0, ?, ?)",
                    (uid, stock_code, qty, price, fee, total_cost, month)
                )

            elif otype == "SELL":
                revenue = price * qty
                fee = revenue * FEE_RATE
                tax = revenue * TAX_RATE
                net = revenue - fee - tax

                # 포트폴리오에서 차감
                existing = await db.execute_fetchall(
                    "SELECT quantity, avg_price FROM portfolios WHERE user_id = ? AND stock_code = ? AND month = ?",
                    (uid, stock_code, month)
                )
                if not existing or existing[0]["quantity"] < qty:
                    await db.execute(
                        "UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (order["id"],)
                    )
                    continue

                new_qty = existing[0]["quantity"] - qty
                await db.execute(
                    "UPDATE portfolios SET quantity = ? WHERE user_id = ? AND stock_code = ? AND month = ?",
                    (new_qty, uid, stock_code, month)
                )

                # 현금 추가
                cash += net
                await db.execute(
                    "UPDATE balances SET cash = ? WHERE user_id = ? AND month = ?",
                    (cash, uid, month)
                )

                # 거래 로그
                await db.execute(
                    "INSERT INTO trade_logs (user_id, stock_code, trade_type, quantity, price, fee, tax, total_amount, month) VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?)",
                    (uid, stock_code, qty, price, fee, tax, net, month)
                )

            # 주문 상태 업데이트
            await db.execute(
                "UPDATE orders SET status = 'FILLED', filled_price = ?, filled_at = ?, fee = ?, tax = ? WHERE id = ?",
                (price, date, fee if otype == "BUY" else fee, tax if otype == "SELL" else 0, order["id"])
            )
            settled_count += 1

        # 3. 일별 스냅샷 생성
        users = await db.execute_fetchall(
            "SELECT id FROM users WHERE is_approved = 1 AND is_admin = 0"
        )
        for u in users:
            uid = u["id"]
            bal = await db.execute_fetchall(
                "SELECT cash FROM balances WHERE user_id = ? AND month = ?", (uid, month)
            )
            cash = bal[0]["cash"] if bal else INITIAL_SEED

            ports = await db.execute_fetchall(
                "SELECT stock_code, quantity FROM portfolios WHERE user_id = ? AND month = ? AND quantity > 0",
                (uid, month)
            )
            total_eval = 0
            for p in ports:
                pr = await db.execute_fetchall(
                    "SELECT close_price FROM prices WHERE stock_code = ? ORDER BY date DESC LIMIT 1",
                    (p["stock_code"],)
                )
                if pr:
                    total_eval += pr[0]["close_price"] * p["quantity"]

            total = cash + total_eval
            rate = ((total / INITIAL_SEED) - 1) * 100

            await db.execute(
                "INSERT OR REPLACE INTO daily_snapshots (user_id, date, total_value, cash, return_rate, month) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, date, total, cash, round(rate, 2), month)
            )

        # 전광판: 매매 체결 알림
        if settled_count > 0:
            await insert_ticker(db, f"📊 {date} 매매가 체결되었습니다 ({settled_count}건)", "trade")
        # 전광판: 평가금 1위 변동 체크
        await check_eval_leader_change(db, month)
        # 전광판: 포인트 1위 변동 체크
        await check_point_leader_change(db)

        await db.commit()
        return {
            "message": f"종가 입력 완료 ({date})",
            "prices_count": len(req.prices),
            "settled_count": settled_count,
        }
    finally:
        await db.close()


@app.get("/api/admin/settlement-status")
async def admin_settlement_status(user=Depends(get_admin_user)):
    """이번 달 체결 입력 현황: 입력 완료 날짜 + 미입력 영업일"""
    db = await get_db()
    try:
        month = current_month()

        # 입력 완료된 날짜들 (prices 테이블에서 이번 달 distinct dates)
        rows = await db.execute_fetchall(
            "SELECT DISTINCT date FROM prices WHERE date LIKE ? ORDER BY date",
            (f"{month}%",)
        )
        entered_dates = [r["date"] for r in rows]

        # 이번 달의 영업일 계산 (월~금, 공휴일 제외하지 않음)
        today = dt.now().date()
        year, mon = int(month[:4]), int(month[5:7])
        import calendar
        _, last_day = calendar.monthrange(year, mon)
        business_days = []
        for d in range(1, last_day + 1):
            date_obj = dt(year, mon, d).date()
            if date_obj > today:
                break
            if date_obj.weekday() < 5:  # 월~금
                business_days.append(date_obj.isoformat())

        missing_dates = [d for d in business_days if d not in entered_dates]

        return {
            "month": month,
            "entered_dates": entered_dates,
            "missing_dates": missing_dates,
            "total_business_days": len(business_days),
            "entered_count": len(entered_dates),
            "missing_count": len(missing_dates),
        }
    finally:
        await db.close()


@app.post("/api/admin/stocks/load-csv")
async def admin_load_stock_csv(request: Request, user=Depends(get_admin_user)):
    """종목 CSV 데이터 로드 (JSON body: {"stocks": [{"code":"005930","name":"삼성전자","market":"KOSPI"}, ...]})"""
    data = await request.json()
    stocks = data.get("stocks", [])
    if not stocks:
        raise HTTPException(400, "종목 데이터가 없습니다")

    db = await get_db()
    try:
        for s in stocks:
            await db.execute(
                "INSERT OR REPLACE INTO stocks (code, name, market) VALUES (?, ?, ?)",
                (s["code"], s["name"], s.get("market", "KOSPI"))
            )
        await db.commit()
        return {"message": f"{len(stocks)}개 종목 로드 완료"}
    finally:
        await db.close()


@app.post("/api/admin/month-reset")
async def admin_month_reset(with_rewards: bool = False, user=Depends(get_admin_user)):
    """월간 리셋 (새 달 시작). with_rewards=true이면 랭킹 보상 포함"""
    month = current_month()
    db = await get_db()
    try:
        reward_msg = ""
        if with_rewards:
            rankings = await _calculate_monthly_rankings(db, month)
            rewards = []
            RANK_REWARDS = {1: 5000, 2: 3000, 3: 1000}
            for r in rankings:
                if r["rank"] in RANK_REWARDS:
                    amount = RANK_REWARDS[r["rank"]]
                    await log_point_change(db, r["user_id"], amount, "월간 리셋 보상", f"월간 {r['rank']}등 보상 (+{amount}P)")
                    rewards.append(f"{r['nickname']} {r['rank']}등 +{amount}P")
            if len(rankings) >= 2:
                last = rankings[-1]
                await log_point_change(db, last["user_id"], -500, "월간 리셋 벌칙", f"월간 꼴등 벌칙 (-500P)")
                rewards.append(f"{last['nickname']} 꼴등 -500P")
            reward_msg = " — " + " | ".join(rewards) if rewards else ""

        # 잔고 초기화
        users = await db.execute_fetchall(
            "SELECT id FROM users WHERE is_approved = 1 AND is_admin = 0"
        )
        for u in users:
            await db.execute(
                "INSERT OR REPLACE INTO balances (user_id, month, cash) VALUES (?, ?, ?)",
                (u["id"], month, INITIAL_SEED)
            )
            await db.execute(
                "UPDATE orders SET status = 'CANCELLED' WHERE user_id = ? AND status = 'PENDING' AND month != ?",
                (u["id"], month)
            )
        await db.commit()
        return {"message": f"{month} 월간 리셋 완료 ({len(users)}명){reward_msg}"}
    finally:
        await db.close()


@app.post("/api/admin/points/reset-all")
async def admin_reset_all_points(user=Depends(get_admin_user)):
    """전체 유저 포인트를 10,000P로 초기화"""
    db = await get_db()
    try:
        users = await db.execute_fetchall(
            "SELECT id, nickname FROM users WHERE is_approved = 1 AND is_admin = 0"
        )
        count = 0
        for u in users:
            bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (u["id"],))
            old_points = bal[0]["points"] if bal else 0
            diff = 10000 - old_points
            if diff != 0:
                await log_point_change(db, u["id"], diff, "전체 초기화", f"포인트 전체 초기화 ({old_points}P → 10,000P)")
            else:
                # 이미 10000이면 로그만
                pass
            count += 1
        await db.commit()
        return {"message": f"전체 {count}명 포인트를 10,000P로 초기화 완료"}
    finally:
        await db.close()


@app.post("/api/admin/points/adjust")
async def admin_adjust_points(req: AdminPointAdjustRequest, user=Depends(get_admin_user)):
    """관리자 포인트 수동 조정"""
    if req.amount == 0:
        raise HTTPException(400, "변경할 포인트를 입력하세요")
    db = await get_db()
    try:
        target = await db.execute_fetchall("SELECT id, nickname FROM users WHERE id = ?", (req.user_id,))
        if not target:
            raise HTTPException(404, "유저를 찾을 수 없습니다")
        bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (req.user_id,))
        if not bal:
            raise HTTPException(404, "포인트 잔고가 없습니다")
        if bal[0]["points"] + req.amount < 0:
            raise HTTPException(400, f"차감 후 잔고가 음수가 됩니다 (현재: {bal[0]['points']}P)")

        new_balance = await log_point_change(db, req.user_id, req.amount, "관리자 조정", req.reason)
        await db.commit()
        action = "지급" if req.amount > 0 else "차감"
        return {
            "message": f"{target[0]['nickname']}에게 {abs(req.amount)}P {action} 완료",
            "new_balance": new_balance,
        }
    finally:
        await db.close()


@app.get("/api/admin/points/transactions")
async def admin_point_transactions(
    user_id: int = 0,
    source: str = "",
    page: int = 1,
    user=Depends(get_admin_user),
):
    """포인트 가감 내역 조회 (관리자)"""
    db = await get_db()
    try:
        limit = 50
        offset = (page - 1) * limit
        conditions = []
        params = []
        if user_id:
            conditions.append("pt.user_id = ?")
            params.append(user_id)
        if source:
            conditions.append("pt.source LIKE ?")
            params.append(f"%{source}%")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await db.execute_fetchall(
            f"""SELECT pt.*, u.nickname FROM point_transactions pt
                JOIN users u ON pt.user_id = u.id
                {where}
                ORDER BY pt.id DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset)
        )
        count_rows = await db.execute_fetchall(
            f"SELECT COUNT(*) as cnt FROM point_transactions pt {where}", params
        )
        return {
            "transactions": [dict(r) for r in rows],
            "total": count_rows[0]["cnt"],
            "page": page,
            "pages": (count_rows[0]["cnt"] + limit - 1) // limit,
        }
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# BOARD API
# ═══════════════════════════════════════════════

@app.get("/api/posts")
async def list_posts(category: str = "", page: int = 1, user=Depends(get_current_user)):
    db = await get_db()
    try:
        limit = 20
        offset = (page - 1) * limit
        if category:
            rows = await db.execute_fetchall(
                """SELECT p.*, u.nickname FROM posts p
                   JOIN users u ON p.user_id = u.id
                   WHERE p.category = ?
                   ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
                (category, limit, offset)
            )
        else:
            rows = await db.execute_fetchall(
                """SELECT p.*, u.nickname FROM posts p
                   JOIN users u ON p.user_id = u.id
                   ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset)
            )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.post("/api/posts")
async def create_post(req: PostCreateRequest, user=Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO posts (user_id, category, title, content) VALUES (?, ?, ?, ?)",
            (user["user_id"], req.category, req.title, req.content)
        )

        # 게시글 포인트 (일 3회, 30P)
        today = dt.now().strftime("%Y-%m-%d")
        rows = await db.execute_fetchall(
            "SELECT count FROM daily_activity WHERE user_id=? AND date=? AND activity_type='post'",
            (user["user_id"], today)
        )
        current_count = rows[0]["count"] if rows else 0
        points_awarded = 0
        if current_count < 3:
            await db.execute(
                "INSERT INTO daily_activity (user_id, date, activity_type, count) VALUES (?,?,'post',1) "
                "ON CONFLICT(user_id, date, activity_type) DO UPDATE SET count = count + 1",
                (user["user_id"], today)
            )
            points_awarded = 30
            await log_point_change(db, user["user_id"], points_awarded, "게시글 작성", f"게시글 #{cursor.lastrowid}")

        await db.commit()
        return {"message": "글 작성 완료", "post_id": cursor.lastrowid, "points_awarded": points_awarded}
    finally:
        await db.close()


@app.get("/api/posts/{post_id}")
async def get_post(post_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT p.*, u.nickname FROM posts p
               JOIN users u ON p.user_id = u.id WHERE p.id = ?""",
            (post_id,)
        )
        if not rows:
            raise HTTPException(404, "게시글을 찾을 수 없습니다")
        post = dict(rows[0])

        # 댓글
        comments = await db.execute_fetchall(
            """SELECT c.*, u.nickname FROM comments c
               JOIN users u ON c.user_id = u.id
               WHERE c.post_id = ? ORDER BY c.created_at""",
            (post_id,)
        )
        post["comments"] = [dict(c) for c in comments]

        # 현재 사용자의 투표 여부
        my_vote = await db.execute_fetchall(
            "SELECT vote_type FROM post_votes WHERE user_id = ? AND post_id = ?",
            (user["user_id"], post_id)
        )
        post["my_vote"] = my_vote[0]["vote_type"] if my_vote else None

        return post
    finally:
        await db.close()


@app.post("/api/posts/{post_id}/comments")
async def create_comment(post_id: int, req: CommentCreateRequest, user=Depends(get_current_user)):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO comments (post_id, user_id, content) VALUES (?, ?, ?)",
            (post_id, user["user_id"], req.content)
        )

        # 댓글 포인트 (일 10회, 10P)
        today = dt.now().strftime("%Y-%m-%d")
        rows = await db.execute_fetchall(
            "SELECT count FROM daily_activity WHERE user_id=? AND date=? AND activity_type='comment'",
            (user["user_id"], today)
        )
        current_count = rows[0]["count"] if rows else 0
        points_awarded = 0
        if current_count < 10:
            await db.execute(
                "INSERT INTO daily_activity (user_id, date, activity_type, count) VALUES (?,?,'comment',1) "
                "ON CONFLICT(user_id, date, activity_type) DO UPDATE SET count = count + 1",
                (user["user_id"], today)
            )
            points_awarded = 10
            await log_point_change(db, user["user_id"], points_awarded, "댓글 작성", f"게시글 #{post_id} 댓글")

        await db.commit()
        return {"message": "댓글 작성 완료", "points_awarded": points_awarded}
    finally:
        await db.close()


@app.post("/api/posts/{post_id}/vote")
async def vote_post(post_id: int, req: VoteRequest, user=Depends(get_current_user)):
    if req.vote_type not in ("like", "dislike"):
        raise HTTPException(400, "like 또는 dislike만 가능합니다")
    db = await get_db()
    try:
        # 게시글 작성자 조회
        post_rows = await db.execute_fetchall(
            "SELECT user_id FROM posts WHERE id = ?", (post_id,)
        )
        if not post_rows:
            raise HTTPException(404, "게시글을 찾을 수 없습니다")
        author_id = post_rows[0]["user_id"]

        # 기존 투표 확인
        existing = await db.execute_fetchall(
            "SELECT vote_type FROM post_votes WHERE user_id = ? AND post_id = ?",
            (user["user_id"], post_id)
        )

        like_awarded = False
        if existing:
            raise HTTPException(400, "이미 투표했습니다. 투표는 수정할 수 없습니다.")
        else:
            await db.execute(
                "INSERT INTO post_votes (user_id, post_id, vote_type) VALUES (?, ?, ?)",
                (user["user_id"], post_id, req.vote_type)
            )
            await db.execute(f"UPDATE posts SET {req.vote_type}s = {req.vote_type}s + 1 WHERE id = ?", (post_id,))
            # 새 좋아요 시 작성자에게 10P
            if req.vote_type == "like" and user["user_id"] != author_id:
                like_awarded = True

        if like_awarded:
            await log_point_change(db, author_id, 10, "추천 받음", f"게시글 #{post_id} 추천")

        await db.commit()
        return {"message": "투표 완료"}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# PICKS API (방's pick)
# ═══════════════════════════════════════════════

@app.get("/api/picks")
async def list_picks(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT p.*, u.nickname FROM picks p
               JOIN users u ON p.user_id = u.id
               ORDER BY p.call_date DESC, p.created_at DESC"""
        )
        result = []
        for r in rows:
            pick = dict(r)
            # 관련 종목명 붙이기
            if pick.get("stock_codes"):
                codes = [c.strip() for c in pick["stock_codes"].split(",") if c.strip()]
                stock_names = []
                for code in codes:
                    s = await db.execute_fetchall("SELECT name FROM stocks WHERE code = ?", (code,))
                    stock_names.append({"code": code, "name": s[0]["name"] if s else code})
                pick["stocks"] = stock_names
            else:
                pick["stocks"] = []
            # 댓글 수
            cnt = await db.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM pick_comments WHERE pick_id = ?", (pick["id"],)
            )
            pick["comment_count"] = cnt[0]["cnt"]
            result.append(pick)
        return result
    finally:
        await db.close()


@app.post("/api/picks")
async def create_pick(req: PickCreateRequest, user=Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO picks (user_id, title, content, importance, call_date, call_time, stock_codes, direction)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user["user_id"], req.title, req.content, req.importance,
             req.call_date, req.call_time, req.stock_codes, req.direction)
        )
        await db.commit()
        return {"message": "Pick 등록 완료", "pick_id": cursor.lastrowid}
    finally:
        await db.close()


@app.get("/api/picks/{pick_id}")
async def get_pick(pick_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT p.*, u.nickname FROM picks p
               JOIN users u ON p.user_id = u.id WHERE p.id = ?""",
            (pick_id,)
        )
        if not rows:
            raise HTTPException(404, "Pick을 찾을 수 없습니다")
        pick = dict(rows[0])

        # 종목
        if pick.get("stock_codes"):
            codes = [c.strip() for c in pick["stock_codes"].split(",") if c.strip()]
            stock_names = []
            for code in codes:
                s = await db.execute_fetchall("SELECT name FROM stocks WHERE code = ?", (code,))
                stock_names.append({"code": code, "name": s[0]["name"] if s else code})
            pick["stocks"] = stock_names
        else:
            pick["stocks"] = []

        # 댓글
        comments = await db.execute_fetchall(
            """SELECT c.*, u.nickname FROM pick_comments c
               JOIN users u ON c.user_id = u.id
               WHERE c.pick_id = ? ORDER BY c.created_at""",
            (pick_id,)
        )
        pick["comments"] = [dict(c) for c in comments]
        return pick
    finally:
        await db.close()


@app.post("/api/picks/{pick_id}/comments")
async def create_pick_comment(pick_id: int, req: CommentCreateRequest, user=Depends(get_current_user)):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO pick_comments (pick_id, user_id, content) VALUES (?, ?, ?)",
            (pick_id, user["user_id"], req.content)
        )
        await db.commit()
        return {"message": "댓글 작성 완료"}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# BETTING API
# ═══════════════════════════════════════════════

@app.get("/api/bets")
async def list_bets(status: str = "", user=Depends(get_current_user)):
    db = await get_db()
    try:
        if status:
            rows = await db.execute_fetchall(
                """SELECT b.*, u.nickname as creator_name FROM bets b
                   JOIN users u ON b.creator_id = u.id
                   WHERE b.status = ? ORDER BY b.created_at DESC""",
                (status,)
            )
        else:
            rows = await db.execute_fetchall(
                """SELECT b.*, u.nickname as creator_name FROM bets b
                   JOIN users u ON b.creator_id = u.id
                   ORDER BY b.created_at DESC"""
            )
        result = []
        for r in rows:
            bet = dict(r)
            bet["options"] = json.loads(bet["options"])
            # 참여자 수
            entries = await db.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM bet_entries WHERE bet_id = ?", (bet["id"],)
            )
            bet["entry_count"] = entries[0]["cnt"]
            result.append(bet)
        return result
    finally:
        await db.close()


@app.post("/api/bets")
async def create_bet(req: BetCreateRequest, user=Depends(get_current_user)):
    if len(req.options) < 2:
        raise HTTPException(400, "선택지는 2개 이상이어야 합니다")
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO bets (creator_id, title, description, options, deadline) VALUES (?, ?, ?, ?, ?)",
            (user["user_id"], req.title, req.description, json.dumps(req.options, ensure_ascii=False), req.deadline)
        )
        await db.commit()
        return {"message": "베팅 생성 완료", "bet_id": cursor.lastrowid}
    finally:
        await db.close()


@app.post("/api/bets/{bet_id}/enter")
async def enter_bet(bet_id: int, req: BetEntryRequest, user=Depends(get_current_user)):
    if req.points <= 0:
        raise HTTPException(400, "포인트는 1 이상이어야 합니다")
    db = await get_db()
    try:
        # 베팅 확인
        bets = await db.execute_fetchall("SELECT * FROM bets WHERE id = ? AND status = 'OPEN'", (bet_id,))
        if not bets:
            raise HTTPException(404, "참여할 수 있는 베팅이 없습니다")

        options = json.loads(bets[0]["options"])
        if req.chosen_option not in options:
            raise HTTPException(400, "유효하지 않은 선택지입니다")

        # 포인트 확인
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        if not bal or bal[0]["points"] < req.points:
            raise HTTPException(400, "포인트가 부족합니다")

        # 참여
        await db.execute(
            "INSERT INTO bet_entries (bet_id, user_id, chosen_option, points) VALUES (?, ?, ?, ?)",
            (bet_id, user["user_id"], req.chosen_option, req.points)
        )
        await log_point_change(db, user["user_id"], -req.points, "베팅 참여", f"베팅 #{bet_id} '{req.chosen_option}'")
        await db.commit()
        return {"message": "베팅 참여 완료"}
    finally:
        await db.close()


@app.post("/api/bets/{bet_id}/settle")
async def settle_bet(bet_id: int, req: BetSettleRequest, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        bets = await db.execute_fetchall("SELECT * FROM bets WHERE id = ?", (bet_id,))
        if not bets:
            raise HTTPException(404, "베팅을 찾을 수 없습니다")

        # 총 포인트 풀
        entries = await db.execute_fetchall(
            "SELECT * FROM bet_entries WHERE bet_id = ?", (bet_id,)
        )
        total_pool = sum(e["points"] for e in entries)
        winners = [e for e in entries if e["chosen_option"] == req.result]
        winner_pool = sum(w["points"] for w in winners)

        # 배분
        if winners and winner_pool > 0:
            for w in winners:
                payout = int(total_pool * (w["points"] / winner_pool))
                await log_point_change(db, w["user_id"], payout, "베팅 당첨", f"베팅 #{bet_id} 정산")

        await db.execute(
            "UPDATE bets SET status = 'SETTLED', result = ? WHERE id = ?",
            (req.result, bet_id)
        )
        await db.commit()
        return {
            "message": "베팅 정산 완료",
            "total_pool": total_pool,
            "winners_count": len(winners),
        }
    finally:
        await db.close()


@app.get("/api/points")
async def get_points(user=Depends(get_current_user)):
    db = await get_db()
    try:
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        return {"points": bal[0]["points"] if bal else 0}
    finally:
        await db.close()


ROULETTE_TABLE = [
    (3000, 0.02),   # 3000P: 2%
    (1000, 0.08),   # 1000P: 8%
    (200, 0.30),    # 200P: 30%
    (100, 0.40),    # 100P: 40%
    (50, 0.20),     # 50P: 20%
]

@app.post("/api/points/daily-free")
async def daily_free_charge(user=Depends(get_current_user)):
    """일일 출석 룰렛"""
    db = await get_db()
    try:
        today = dt.now().strftime("%Y-%m-%d")
        rows = await db.execute_fetchall(
            "SELECT count FROM daily_activity WHERE user_id = ? AND date = ? AND activity_type = 'free_charge'",
            (user["user_id"], today)
        )
        if rows and rows[0]["count"] > 0:
            raise HTTPException(400, "오늘 이미 룰렛을 돌렸습니다")

        # 룰렛 추첨
        roll = random.random()
        cumulative = 0
        reward = 50  # 기본값
        for amount, prob in ROULETTE_TABLE:
            cumulative += prob
            if roll < cumulative:
                reward = amount
                break

        await db.execute(
            "INSERT INTO daily_activity (user_id, date, activity_type, count) VALUES (?, ?, 'free_charge', 1) "
            "ON CONFLICT(user_id, date, activity_type) DO UPDATE SET count = count + 1",
            (user["user_id"], today)
        )
        new_balance = await log_point_change(db, user["user_id"], reward, "출석 룰렛", f"출석 룰렛 {reward}P")
        await db.commit()
        return {"reward": reward, "points": new_balance}
    finally:
        await db.close()


@app.post("/api/points/relief")
async def relief_points(user=Depends(get_current_user)):
    """구제 포인트: 100P 이하일 때 하루 1회 200P 자동 지급"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        current_points = rows[0]["points"] if rows else 0
        if current_points > 100:
            return {"relief": False, "reason": "포인트가 충분합니다"}

        today = dt.now().strftime("%Y-%m-%d")
        existing = await db.execute_fetchall(
            "SELECT count FROM daily_activity WHERE user_id = ? AND date = ? AND activity_type = 'relief'",
            (user["user_id"], today)
        )
        if existing and existing[0]["count"] > 0:
            return {"relief": False, "reason": "오늘 이미 구제 포인트를 받았습니다"}

        await db.execute(
            "INSERT INTO daily_activity (user_id, date, activity_type, count) VALUES (?, ?, 'relief', 1) "
            "ON CONFLICT(user_id, date, activity_type) DO UPDATE SET count = count + 1",
            (user["user_id"], today)
        )
        new_balance = await log_point_change(db, user["user_id"], 200, "구제 포인트", "잔액 부족 자동 구제 200P")
        await db.commit()
        return {"relief": True, "points_awarded": 200, "points": new_balance}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# ATTENDANCE (출석 체크)
# ═══════════════════════════════════════════════

@app.post("/api/attendance/check-in")
async def check_in(user=Depends(get_current_user)):
    db = await get_db()
    try:
        today = dt.now().strftime("%Y-%m-%d")
        existing = await db.execute_fetchall(
            "SELECT * FROM attendance WHERE user_id = ? AND date = ?",
            (user["user_id"], today)
        )
        if existing:
            return {"checked_in": False, "points_awarded": 0}

        points_award = 100
        await db.execute(
            "INSERT INTO attendance (user_id, date, points_awarded) VALUES (?, ?, ?)",
            (user["user_id"], today, points_award)
        )
        await log_point_change(db, user["user_id"], points_award, "출석 체크", f"{today} 출석")

        # 연속 출석 스트릭 계산
        streak = 1
        check_date = dt.now()
        for _ in range(60):  # 최대 60일 전까지 확인
            check_date -= timedelta(days=1)
            prev = await db.execute_fetchall(
                "SELECT 1 FROM attendance WHERE user_id = ? AND date = ?",
                (user["user_id"], check_date.strftime("%Y-%m-%d"))
            )
            if prev:
                streak += 1
            else:
                break

        streak_bonus = 0
        streak_milestone = None
        if streak == 3:
            streak_bonus, streak_milestone = 50, "3일 연속"
        elif streak == 7:
            streak_bonus, streak_milestone = 200, "7일 연속"
        elif streak == 14:
            streak_bonus, streak_milestone = 500, "14일 연속"
        elif streak == 30:
            streak_bonus, streak_milestone = 1000, "30일 연속"

        if streak_bonus > 0:
            await log_point_change(db, user["user_id"], streak_bonus, "출석 스트릭", f"{streak_milestone} 보너스")
            points_award += streak_bonus

        await db.commit()
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        return {
            "checked_in": True,
            "points_awarded": points_award,
            "total_points": bal[0]["points"] if bal else 0,
            "streak": streak,
            "streak_bonus": streak_bonus,
            "streak_milestone": streak_milestone,
        }
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# GACHA (일일 가챠 뽑기)
# ═══════════════════════════════════════════════

GACHA_FREE_PER_DAY = 1
GACHA_PAID_COST = 100

def _spin_gacha():
    roll = random.randint(1, 100)
    if roll <= 50:
        return "MISS", 0
    elif roll <= 80:
        return "SMALL", random.randint(10, 50)
    elif roll <= 95:
        return "MEDIUM", random.randint(100, 300)
    else:
        return "JACKPOT", random.randint(500, 2000)

@app.get("/api/gacha/today")
async def gacha_today(user=Depends(get_current_user)):
    db = await get_db()
    try:
        today = dt.now().strftime("%Y-%m-%d")
        spins = await db.execute_fetchall(
            "SELECT grade, points_won, cost, created_at FROM gacha_logs WHERE user_id = ? AND date = ? ORDER BY id",
            (user["user_id"], today)
        )
        spin_count = len(spins)
        free_used = spin_count > 0
        return {
            "spin_count": spin_count,
            "free_used": free_used,
            "paid_cost": GACHA_PAID_COST,
            "today_spins": [dict(s) for s in spins],
        }
    finally:
        await db.close()

@app.post("/api/gacha/spin")
async def gacha_spin(user=Depends(get_current_user)):
    db = await get_db()
    try:
        today = dt.now().strftime("%Y-%m-%d")
        spins = await db.execute_fetchall(
            "SELECT COUNT(*) as cnt FROM gacha_logs WHERE user_id = ? AND date = ?",
            (user["user_id"], today)
        )
        spin_count = spins[0]["cnt"] if spins else 0

        cost = 0
        if spin_count >= GACHA_FREE_PER_DAY:
            cost = GACHA_PAID_COST
            bal = await db.execute_fetchall(
                "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
            )
            pts = bal[0]["points"] if bal else 0
            if pts < cost:
                raise HTTPException(400, f"포인트가 부족합니다 (추가 뽑기 비용: {cost}P)")
            await log_point_change(db, user["user_id"], -cost, "가챠 비용", f"추가 뽑기 #{spin_count + 1}")

        grade, points_won = _spin_gacha()
        spin_number = spin_count + 1

        await db.execute(
            "INSERT INTO gacha_logs (user_id, date, spin_number, grade, points_won, cost) VALUES (?,?,?,?,?,?)",
            (user["user_id"], today, spin_number, grade, points_won, cost)
        )

        if points_won > 0:
            await log_point_change(db, user["user_id"], points_won, "가챠 당첨", f"{grade} +{points_won}P")

        await db.commit()
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        nickname_rows = await db.execute_fetchall(
            "SELECT nickname FROM users WHERE id = ?", (user["user_id"],)
        )
        nickname = nickname_rows[0]["nickname"] if nickname_rows else ""
        return {
            "grade": grade,
            "points_won": points_won,
            "cost": cost,
            "total_points": bal[0]["points"] if bal else 0,
            "nickname": nickname,
        }
    finally:
        await db.close()

@app.get("/api/gacha/recent-jackpots")
async def gacha_recent_jackpots(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT gl.points_won, gl.created_at, u.nickname
               FROM gacha_logs gl
               JOIN users u ON gl.user_id = u.id
               WHERE gl.grade = 'JACKPOT'
               ORDER BY gl.id DESC LIMIT 10"""
        )
        return {"jackpots": [dict(r) for r in rows]}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# POINT LEADERBOARD
# ═══════════════════════════════════════════════

@app.get("/api/points/leaderboard")
async def point_leaderboard(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT pb.user_id, u.nickname, pb.points
               FROM point_balances pb
               JOIN users u ON pb.user_id = u.id
               WHERE u.is_approved = 1
               ORDER BY pb.points DESC LIMIT 50"""
        )
        rankings = []
        for i, r in enumerate(rows):
            badge = await get_user_badge_str(db, r["user_id"])
            rankings.append({
                "rank": i + 1,
                "user_id": r["user_id"],
                "nickname": r["nickname"],
                "badge": badge,
                "points": r["points"],
            })
        return {"rankings": rankings}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# RPS (가위바위보)
# ═══════════════════════════════════════════════

RPS_BASE_RATE = 0.97  # 1.97배 배당 (승리 시 배팅금 × 0.97 수익)
RPS_JACKPOT_RAKE = 0.04  # 배팅금의 4%가 잭팟 풀로
RPS_LOTTO_RAKE = 0.01  # 배팅금의 1%가 로또 풀로
RPS_JACKPOT_CHANCE = 0.001  # 잭팟 확률 0.1% (100P 이상 배팅)
WEALTH_TAX_RATE = 0.10  # 보유세 10%
LOTTO_DRAW_HOUR = 15
LOTTO_DRAW_MINUTE = 55


@app.get("/api/rps/status")
async def rps_status(user=Depends(get_current_user)):
    """잭팟 풀 상태"""
    db = await get_db()
    try:
        jp = await db.execute_fetchall("SELECT amount FROM jackpot_pool WHERE id = 1")
        return {
            "jackpot_pool": jp[0]["amount"] if jp else 0,
        }
    finally:
        await db.close()


@app.post("/api/rps/play")
async def play_rps(req: RPSPlayRequest, user=Depends(get_current_user)):
    if req.choice not in ("rock", "paper", "scissors"):
        raise HTTPException(400, "rock, paper, scissors 중 선택하세요")
    if req.wager <= 0:
        raise HTTPException(400, "배팅 포인트는 1 이상이어야 합니다")

    db = await get_db()
    try:
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        if not bal or bal[0]["points"] < req.wager:
            raise HTTPException(400, "포인트가 부족합니다")

        max_wager = max(1, int(bal[0]["points"] * 0.9))
        if req.wager > max_wager:
            raise HTTPException(400, f"보유 포인트의 90%까지만 배팅할 수 있습니다 (최대 {max_wager}P)")

        # 잭팟 풀 적립 (4%)
        rake = max(1, int(req.wager * RPS_JACKPOT_RAKE))
        await db.execute("UPDATE jackpot_pool SET amount = amount + ? WHERE id = 1", (rake,))

        # 로또 풀 적립 (1%)
        lotto_rake = int(req.wager * RPS_LOTTO_RAKE)
        if lotto_rake > 0:
            await db.execute("UPDATE lotto_pool SET amount = amount + ? WHERE id = 1", (lotto_rake,))

        computer = random.choice(["rock", "paper", "scissors"])
        jackpot_win = 0
        if req.choice == computer:
            result = "draw"
            payout = 0
        elif (req.choice == "rock" and computer == "scissors") or \
             (req.choice == "paper" and computer == "rock") or \
             (req.choice == "scissors" and computer == "paper"):
            result = "win"
            payout = int(req.wager * RPS_BASE_RATE)
        else:
            result = "lose"
            payout = -req.wager

        if payout != 0:
            if result == "win":
                desc = f"가위바위보 win (배팅 {req.wager}P → +{payout}P)"
            else:
                desc = f"가위바위보 lose (배팅 {req.wager}P)"
            await log_point_change(db, user["user_id"], payout, "가위바위보", desc)

        # 잭팟 추첨 (승패 무관, 100P 이상 배팅만, 0.5%)
        if req.wager >= 100 and random.random() < RPS_JACKPOT_CHANCE:
            jp_row = await db.execute_fetchall("SELECT amount FROM jackpot_pool WHERE id = 1")
            jp_amount = jp_row[0]["amount"] if jp_row else 0
            if jp_amount >= 100:
                jackpot_win = jp_amount
                await db.execute("UPDATE jackpot_pool SET amount = 0 WHERE id = 1")
                await log_point_change(db, user["user_id"], jackpot_win, "잭팟", f"가위바위보 잭팟 당첨! {jackpot_win}P")
                nick_row = await db.execute_fetchall("SELECT nickname FROM users WHERE id = ?", (user["user_id"],))
                nickname = nick_row[0]["nickname"] if nick_row else "???"
                await insert_system_message(db, f"🎰 {nickname}님이 잭팟 {jackpot_win:,}P 당첨!!")
                await insert_ticker(db, f"🎰 {nickname}님 가위바위보 잭팟 {jackpot_win:,}P 대박!", "jackpot")

        await db.execute(
            """INSERT INTO rps_games (user_id, player_choice, computer_choice, result, wager, payout)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user["user_id"], req.choice, computer, result, req.wager, payout)
        )

        # 채팅 시스템 메시지 (주목할 만한 이벤트)
        if not jackpot_win:  # 잭팟 메시지가 이미 있으면 중복 방지
            nick_row = await db.execute_fetchall(
                "SELECT nickname FROM users WHERE id = ?", (user["user_id"],)
            )
            nickname = nick_row[0]["nickname"] if nick_row else "???"
            await check_rps_notable_event(db, user["user_id"], nickname, result, req.wager, payout)
        if abs(payout) >= 300 or jackpot_win:
            await check_point_leader_change(db)

        await db.commit()

        new_bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        jp_after = await db.execute_fetchall("SELECT amount FROM jackpot_pool WHERE id = 1")

        return {
            "player_choice": req.choice,
            "computer_choice": computer,
            "result": result,
            "payout": payout,
            "jackpot_win": jackpot_win,
            "jackpot_pool": jp_after[0]["amount"] if jp_after else 0,
            "new_balance": new_bal[0]["points"] if new_bal else 0,
        }
    finally:
        await db.close()


@app.get("/api/rps/history")
async def rps_history(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT * FROM rps_games WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 20""",
            (user["user_id"],)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# CHAT (채팅)
# ═══════════════════════════════════════════════

async def insert_system_message(db, message: str):
    await db.execute(
        "INSERT INTO chat_messages (user_id, message, msg_type) VALUES (NULL, ?, 'system')",
        (message,),
    )
    await db.execute(
        "DELETE FROM chat_messages WHERE id NOT IN "
        "(SELECT id FROM chat_messages ORDER BY id DESC LIMIT 500)"
    )


async def check_rps_notable_event(db, user_id: int, nickname: str, result: str, wager: int, payout: int):
    messages = []

    # 연승/연패 감지
    recent = await db.execute_fetchall(
        "SELECT result FROM rps_games WHERE user_id = ? ORDER BY id DESC LIMIT 20",
        (user_id,),
    )
    results = [r["result"] for r in recent]

    if len(results) >= 5:
        current = results[0]
        streak = 0
        for r in results:
            if r == current:
                streak += 1
            else:
                break

        if current == "win" and streak >= 10:
            messages.append(f"{nickname}님 가위바위보 {streak}연승 중!")
        elif current == "lose" and streak >= 10:
            messages.append(f"{nickname}님 가위바위보 {streak}연패 중...")

    if messages:
        await insert_system_message(db, messages[0])


@app.get("/api/chat/messages")
async def get_chat_messages(after_id: int = 0, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT c.id, c.user_id, u.nickname, c.message, c.msg_type, c.created_at
               FROM chat_messages c
               LEFT JOIN users u ON c.user_id = u.id
               WHERE c.id > ?
               ORDER BY c.id ASC
               LIMIT 100""",
            (after_id,),
        )
        result = []
        for r in rows:
            d = dict(r)
            if d["user_id"]:
                d["badge"] = await get_user_badge_str(db, d["user_id"])
            else:
                d["badge"] = ""
            result.append(d)
        return result
    finally:
        await db.close()


@app.post("/api/chat/send")
async def send_chat_message(req: ChatSendRequest, user=Depends(get_current_user)):
    msg = req.message.strip()
    if not msg or len(msg) > 200:
        raise HTTPException(400, "메시지는 1~200자여야 합니다")
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO chat_messages (user_id, message, msg_type) VALUES (?, ?, 'user')",
            (user["user_id"], msg),
        )
        msg_id = cursor.lastrowid
        await db.execute(
            "DELETE FROM chat_messages WHERE id NOT IN "
            "(SELECT id FROM chat_messages ORDER BY id DESC LIMIT 500)"
        )
        await db.commit()
        return {"id": msg_id, "message": msg}
    finally:
        await db.close()


@app.delete("/api/admin/chat/clear")
async def admin_clear_chat(user=Depends(get_admin_user)):
    db = await get_db()
    try:
        await db.execute("DELETE FROM chat_messages")
        await db.commit()
        return {"message": "채팅 내역이 초기화되었습니다"}
    finally:
        await db.close()


@app.delete("/api/admin/chat/{msg_id}")
async def admin_delete_chat_message(msg_id: int, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        await db.execute("DELETE FROM chat_messages WHERE id = ?", (msg_id,))
        await db.commit()
        return {"message": "삭제되었습니다"}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# LOTTO (로또) + WEALTH TAX (보유세)
# ═══════════════════════════════════════════════


async def get_user_point_rank(db, user_id: int) -> int:
    """포인트 기준 순위 반환 (1-based)"""
    rows = await db.execute_fetchall(
        """SELECT pb.user_id FROM point_balances pb
           JOIN users u ON pb.user_id = u.id
           WHERE u.is_approved = 1 AND u.is_admin = 0
           ORDER BY pb.points DESC"""
    )
    for i, r in enumerate(rows):
        if r["user_id"] == user_id:
            return i + 1
    return len(rows) + 1


def max_tickets_for_rank(rank: int) -> int:
    if rank <= 4:
        return 1
    elif rank <= 8:
        return 3
    else:
        return 5


async def ensure_open_round(db):
    """OPEN 상태 라운드가 없으면 생성"""
    row = await db.execute_fetchall(
        "SELECT id, round_number FROM lotto_rounds WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1"
    )
    if row:
        return row[0]
    # 최대 round_number 조회
    last = await db.execute_fetchall("SELECT MAX(round_number) as mx FROM lotto_rounds")
    next_num = (last[0]["mx"] or 0) + 1
    today = dt.now().strftime("%Y-%m-%d")
    cursor = await db.execute(
        "INSERT INTO lotto_rounds (round_number, draw_date, status) VALUES (?, ?, 'OPEN')",
        (next_num, today)
    )
    return {"id": cursor.lastrowid, "round_number": next_num}


async def maybe_run_daily_lotto_cycle(db):
    """15:55 이후 호출 시 보유세 징수 + 로또 추첨 (하루 1회)"""
    today = dt.now().strftime("%Y-%m-%d")
    now = dt.now()

    # 이미 오늘 실행했으면 skip
    done = await db.execute_fetchall(
        "SELECT date FROM wealth_tax_log WHERE date = ?", (today,)
    )
    if done:
        return None

    # 15:55 이전이면 skip
    if now.hour < LOTTO_DRAW_HOUR or (now.hour == LOTTO_DRAW_HOUR and now.minute < LOTTO_DRAW_MINUTE):
        return None

    # ── Step 1: 보유세 징수 ──
    users = await db.execute_fetchall(
        """SELECT pb.user_id, pb.points FROM point_balances pb
           JOIN users u ON pb.user_id = u.id
           WHERE u.is_approved = 1 AND u.is_admin = 0 AND pb.points > 0"""
    )
    total_collected = 0
    tax_count = 0
    for u in users:
        tax = int(u["points"] * WEALTH_TAX_RATE)
        if tax < 1:
            continue
        await log_point_change(db, u["user_id"], -tax, "보유세", f"일일 보유세 {int(WEALTH_TAX_RATE*100)}%")
        total_collected += tax
        tax_count += 1

    burned = total_collected // 2
    to_lotto = total_collected - burned

    await db.execute(
        "UPDATE lotto_pool SET amount = amount + ? WHERE id = 1", (to_lotto,)
    )
    await db.execute(
        "INSERT INTO wealth_tax_log (date, total_collected, burned, to_lotto, user_count) VALUES (?,?,?,?,?)",
        (today, total_collected, burned, to_lotto, tax_count)
    )

    # ── Step 2: 로또 추첨 ──
    round_row = await db.execute_fetchall(
        "SELECT id, round_number FROM lotto_rounds WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1"
    )
    if not round_row:
        round_info = await ensure_open_round(db)
        round_id = round_info["id"] if isinstance(round_info, dict) else round_info[0]
        round_num = round_info["round_number"] if isinstance(round_info, dict) else round_info[1]
    else:
        round_id = round_row[0]["id"]
        round_num = round_row[0]["round_number"]

    pool_row = await db.execute_fetchall("SELECT amount FROM lotto_pool WHERE id = 1")
    pool_amount = pool_row[0]["amount"] if pool_row else 0

    winning_number = random.randint(1, 46)

    # 당첨자 조회
    winners = await db.execute_fetchall(
        """SELECT lt.user_id, u.nickname FROM lotto_tickets lt
           JOIN users u ON lt.user_id = u.id
           WHERE lt.round_id = ? AND lt.chosen_number = ?""",
        (round_id, winning_number)
    )

    drawn_at = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    winner_count = len(winners)
    payout_per = 0

    if winner_count > 0 and pool_amount > 0:
        payout_per = pool_amount // winner_count
        for w in winners:
            await log_point_change(db, w["user_id"], payout_per, "로또",
                                   f"로또 {round_num}회 당첨! +{payout_per:,}P")
        remainder = pool_amount - payout_per * winner_count
        await db.execute("UPDATE lotto_pool SET amount = ? WHERE id = 1", (remainder,))
        status = "DRAWN"
        winner_names = ", ".join(w["nickname"] for w in winners)
        await insert_system_message(db, f"🎱 로또 {round_num}회 당첨번호: {winning_number}! 당첨자: {winner_names} (+{payout_per:,}P)")
        await insert_ticker(db, f"🎱 로또 {round_num}회 당첨! 번호 {winning_number}, {winner_names} +{payout_per:,}P", "lotto")
    else:
        status = "NO_WINNER"
        carry = pool_amount
        await insert_system_message(db, f"🎱 로또 {round_num}회 당첨번호: {winning_number} - 당첨자 없음! {carry:,}P 이월")
        await insert_ticker(db, f"🎱 로또 {round_num}회 당첨자 없음! {carry:,}P 이월", "lotto")

    await db.execute(
        """UPDATE lotto_rounds SET status=?, winning_number=?, pool_amount=?,
           winner_count=?, payout_per_winner=?, drawn_at=? WHERE id=?""",
        (status, winning_number, pool_amount, winner_count, payout_per, drawn_at, round_id)
    )

    # 보유세 안내
    if total_collected > 0:
        await insert_system_message(db,
            f"💰 보유세 징수: 총 {total_collected:,}P (소각 {burned:,}P / 로또풀 {to_lotto:,}P)")

    # 다음 라운드 생성
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    await db.execute(
        "INSERT INTO lotto_rounds (round_number, draw_date, status) VALUES (?, ?, 'OPEN')",
        (round_num + 1, tomorrow)
    )

    await db.commit()
    return {"round": round_num, "winning_number": winning_number, "winners": winner_count}


@app.get("/api/lotto/status")
async def lotto_status(user=Depends(get_current_user)):
    db = await get_db()
    try:
        await maybe_run_daily_lotto_cycle(db)

        pool = await db.execute_fetchall("SELECT amount FROM lotto_pool WHERE id = 1")
        pool_amount = pool[0]["amount"] if pool else 0

        # 현재 OPEN 라운드
        round_info = await ensure_open_round(db)
        if isinstance(round_info, dict):
            round_id = round_info["id"]
            round_num = round_info["round_number"]
        else:
            round_id = round_info["id"]
            round_num = round_info["round_number"]
        await db.commit()

        # 내 순위 & 티켓
        rank = await get_user_point_rank(db, user["user_id"])
        max_tickets = max_tickets_for_rank(rank)

        my_tickets = await db.execute_fetchall(
            "SELECT chosen_number FROM lotto_tickets WHERE round_id = ? AND user_id = ?",
            (round_id, user["user_id"])
        )
        my_numbers = [t["chosen_number"] for t in my_tickets]

        # 오늘 보유세 정보
        today = dt.now().strftime("%Y-%m-%d")
        tax_info = await db.execute_fetchall(
            "SELECT * FROM wealth_tax_log WHERE date = ?", (today,)
        )

        # 가장 최근 추첨 결과
        last_drawn = await db.execute_fetchall(
            """SELECT lr.*, GROUP_CONCAT(u.nickname) as winner_names
               FROM lotto_rounds lr
               LEFT JOIN lotto_tickets lt ON lt.round_id = lr.id AND lt.chosen_number = lr.winning_number
               LEFT JOIN users u ON lt.user_id = u.id
               WHERE lr.status IN ('DRAWN', 'NO_WINNER')
               GROUP BY lr.id
               ORDER BY lr.id DESC LIMIT 1"""
        )

        return {
            "pool_amount": pool_amount,
            "round_id": round_id,
            "round_number": round_num,
            "my_rank": rank,
            "max_tickets": max_tickets,
            "my_numbers": my_numbers,
            "draw_hour": LOTTO_DRAW_HOUR,
            "draw_minute": LOTTO_DRAW_MINUTE,
            "tax_done": bool(tax_info),
            "tax_info": dict(tax_info[0]) if tax_info else None,
            "last_result": dict(last_drawn[0]) if last_drawn else None,
        }
    finally:
        await db.close()


@app.post("/api/lotto/pick")
async def lotto_pick(req: LottoTicketRequest, user=Depends(get_current_user)):
    now = dt.now()
    if now.hour > LOTTO_DRAW_HOUR or (now.hour == LOTTO_DRAW_HOUR and now.minute >= LOTTO_DRAW_MINUTE):
        raise HTTPException(400, "추첨 시각(15:55) 이후에는 번호를 선택할 수 없습니다")

    for n in req.numbers:
        if n < 1 or n > 46:
            raise HTTPException(400, "번호는 1~46 사이여야 합니다")
    if len(set(req.numbers)) != len(req.numbers):
        raise HTTPException(400, "중복된 번호는 선택할 수 없습니다")

    db = await get_db()
    try:
        round_info = await ensure_open_round(db)
        round_id = round_info["id"] if isinstance(round_info, dict) else round_info[0]
        await db.commit()

        rank = await get_user_point_rank(db, user["user_id"])
        max_tickets = max_tickets_for_rank(rank)

        # 이미 제출한 티켓
        existing = await db.execute_fetchall(
            "SELECT chosen_number FROM lotto_tickets WHERE round_id = ? AND user_id = ?",
            (round_id, user["user_id"])
        )
        existing_numbers = {t["chosen_number"] for t in existing}

        new_numbers = [n for n in req.numbers if n not in existing_numbers]
        total_after = len(existing_numbers) + len(new_numbers)
        if total_after > max_tickets:
            raise HTTPException(400,
                f"티켓 한도 초과 (현재 순위 {rank}위, 최대 {max_tickets}장, 이미 {len(existing_numbers)}장 사용)")

        for n in new_numbers:
            await db.execute(
                "INSERT INTO lotto_tickets (round_id, user_id, chosen_number) VALUES (?, ?, ?)",
                (round_id, user["user_id"], n)
            )
        await db.commit()

        all_tickets = await db.execute_fetchall(
            "SELECT chosen_number FROM lotto_tickets WHERE round_id = ? AND user_id = ?",
            (round_id, user["user_id"])
        )
        return {
            "my_numbers": [t["chosen_number"] for t in all_tickets],
            "remaining": max_tickets - len(all_tickets),
        }
    finally:
        await db.close()


@app.delete("/api/lotto/pick/{number}")
async def lotto_delete_pick(number: int, user=Depends(get_current_user)):
    now = dt.now()
    if now.hour > LOTTO_DRAW_HOUR or (now.hour == LOTTO_DRAW_HOUR and now.minute >= LOTTO_DRAW_MINUTE):
        raise HTTPException(400, "추첨 시각 이후에는 변경할 수 없습니다")

    db = await get_db()
    try:
        round_row = await db.execute_fetchall(
            "SELECT id FROM lotto_rounds WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1"
        )
        if not round_row:
            raise HTTPException(400, "진행 중인 라운드가 없습니다")

        await db.execute(
            "DELETE FROM lotto_tickets WHERE round_id = ? AND user_id = ? AND chosen_number = ?",
            (round_row[0]["id"], user["user_id"], number)
        )
        await db.commit()
        return {"message": f"{number}번 취소됨"}
    finally:
        await db.close()


@app.get("/api/lotto/history")
async def lotto_history(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT lr.*,
                      GROUP_CONCAT(DISTINCT u.nickname) as winner_names
               FROM lotto_rounds lr
               LEFT JOIN lotto_tickets lt ON lt.round_id = lr.id AND lt.chosen_number = lr.winning_number
               LEFT JOIN users u ON lt.user_id = u.id
               WHERE lr.status != 'OPEN'
               GROUP BY lr.id
               ORDER BY lr.round_number DESC LIMIT 20"""
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# TICKER (전광판)
# ═══════════════════════════════════════════════

async def insert_ticker(db, message: str, category: str = "general"):
    await db.execute(
        "INSERT INTO ticker_messages (message, category) VALUES (?, ?)",
        (message, category),
    )
    await db.execute(
        "DELETE FROM ticker_messages WHERE id NOT IN "
        "(SELECT id FROM ticker_messages ORDER BY id DESC LIMIT 200)"
    )


async def check_point_leader_change(db):
    """포인트 1위 변동 감지 → 전광판"""
    rows = await db.execute_fetchall(
        """SELECT pb.user_id, u.nickname, pb.points
           FROM point_balances pb JOIN users u ON pb.user_id = u.id
           WHERE u.is_approved = 1 AND u.is_admin = 0
           ORDER BY pb.points DESC LIMIT 1"""
    )
    if not rows:
        return
    leader = rows[0]
    # 최근 전광판에서 포인트 1위 메시지 확인
    recent = await db.execute_fetchall(
        "SELECT message FROM ticker_messages WHERE category = 'point_leader' ORDER BY id DESC LIMIT 1"
    )
    leader_tag = f"[PL:{leader['user_id']}]"
    if recent and leader_tag in recent[0]["message"]:
        return  # 이미 같은 사람
    msg = f"👑 {leader['nickname']}님이 포인트 1위를 탈환! ({leader['points']:,}P)"
    await insert_ticker(db, f"{msg} {leader_tag}", "point_leader")
    await insert_system_message(db, msg)


async def check_eval_leader_change(db, month: str):
    """평가금 1위 변동 감지 → 전광판"""
    rows = await db.execute_fetchall(
        """SELECT ds.user_id, u.nickname, ds.total_value, ds.return_rate
           FROM daily_snapshots ds JOIN users u ON ds.user_id = u.id
           WHERE ds.month = ? AND u.is_admin = 0
           ORDER BY ds.return_rate DESC LIMIT 1""",
        (month,),
    )
    if not rows:
        return
    leader = rows[0]
    recent = await db.execute_fetchall(
        "SELECT message FROM ticker_messages WHERE category = 'eval_leader' ORDER BY id DESC LIMIT 1"
    )
    leader_tag = f"[EL:{leader['user_id']}]"
    if recent and leader_tag in recent[0]["message"]:
        return
    sign = "+" if leader["return_rate"] >= 0 else ""
    await insert_ticker(db, f"👑 {leader['nickname']}님이 평가금 1위를 탈환! ({sign}{leader['return_rate']:.2f}%) {leader_tag}", "eval_leader")


async def check_dice_notable_event(db, winner_id: int, winner_nick: str, total_pot: int, player_count: int):
    """주사위 주목 이벤트 → 전광판"""
    messages = []

    # 큰 판 (참가비 기준: pot >= 1000P)
    if total_pot >= 1000:
        messages.append(f"🎲 {winner_nick}님이 주사위에서 {total_pot:,}P 획득! ({player_count}인전)")

    # 연승/연패 (dice_stats에서 조회)
    stats = await db.execute_fetchall(
        "SELECT current_win_streak, current_loss_streak FROM dice_stats WHERE user_id = ?",
        (winner_id,),
    )
    if stats:
        ws = stats[0]["current_win_streak"]
        if ws >= 10:
            messages.append(f"🔥 {winner_nick}님 주사위 {ws}연승!")

    # 패배자 연패 체크
    losers = await db.execute_fetchall(
        """SELECT dp.user_id, u.nickname, ds.current_loss_streak
           FROM dice_players dp
           JOIN users u ON dp.user_id = u.id
           LEFT JOIN dice_stats ds ON dp.user_id = ds.user_id
           WHERE dp.room_id = (SELECT id FROM dice_rooms WHERE winner_id = ? ORDER BY id DESC LIMIT 1)
             AND dp.user_id != ?""",
        (winner_id, winner_id),
    )
    for loser in losers:
        ls = loser["current_loss_streak"] or 0
        if ls >= 10:
            messages.append(f"😭 {loser['nickname']}님 주사위 {ls}연패...")

    # 가장 주목할 만한 메시지 1개만
    if messages:
        await insert_ticker(db, messages[0], "dice")


@app.get("/api/ticker/messages")
async def get_ticker_messages(user=Depends(get_current_user)):
    """최근 전광판 메시지 (24시간 이내, 최신 20개)"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT id, message, category, created_at FROM ticker_messages
               WHERE created_at >= datetime('now','localtime','-24 hours')
               ORDER BY id DESC LIMIT 20"""
        )
        # 메시지에서 내부 태그 제거 후 반환
        result = []
        for r in rows:
            msg = r["message"]
            # [PL:xxx], [EL:xxx] 같은 내부 태그 제거
            msg = re.sub(r'\s*\[(?:PL|EL):\d+\]', '', msg)
            result.append({"id": r["id"], "message": msg, "category": r["category"], "created_at": r["created_at"]})
        return result
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# SHOP (상점) / BADGE (배지)
# ═══════════════════════════════════════════════

CHICKEN_COST = 500
CHICKEN_REMOVE_COST = 1000
CHICKEN_MAX = 5
CHICKEN_DURATION_HOURS = 24


@app.get("/api/shop/items")
async def shop_items(user=Depends(get_current_user)):
    return {
        "items": [
            {
                "id": "chicken",
                "name": "닭대가리 씌우기",
                "emoji": "🐔",
                "description": f"타인 닉네임 앞에 닭대가리를 붙입니다 (24시간 유지, 최대 {CHICKEN_MAX}마리)",
                "cost": CHICKEN_COST,
            },
        ],
        "remove_chicken_cost": CHICKEN_REMOVE_COST,
    }


@app.post("/api/shop/chicken")
async def shop_buy_chicken(req: ShopChickenRequest, user=Depends(get_current_user)):
    db = await get_db()
    try:
        # 대상 유저 찾기
        target = await db.execute_fetchall(
            "SELECT id, nickname FROM users WHERE nickname = ? AND is_approved = 1",
            (req.target_nickname,),
        )
        if not target:
            raise HTTPException(404, "존재하지 않는 닉네임입니다")
        target_id = target[0]["id"]
        target_nick = target[0]["nickname"]

        if target_id == user["user_id"]:
            raise HTTPException(400, "자기 자신에게는 사용할 수 없습니다")

        # 포인트 확인
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        if not bal or bal[0]["points"] < CHICKEN_COST:
            raise HTTPException(400, f"포인트가 부족합니다 ({CHICKEN_COST}P 필요)")

        # 만료된 닭 정리 후 현재 닭 수 확인
        await db.execute(
            "DELETE FROM user_badges WHERE badge_type = 'chicken' AND expires_at <= datetime('now','localtime')"
        )
        current = await db.execute_fetchall(
            "SELECT COUNT(*) as cnt FROM user_badges WHERE target_user_id = ? AND badge_type = 'chicken'",
            (target_id,),
        )
        if current[0]["cnt"] >= CHICKEN_MAX:
            raise HTTPException(400, f"이미 닭대가리 {CHICKEN_MAX}마리가 최대입니다")

        # 포인트 차감
        await log_point_change(db, user["user_id"], -CHICKEN_COST, "상점", f"닭대가리 → {target_nick}")

        # 배지 추가
        await db.execute(
            "INSERT INTO user_badges (target_user_id, sender_user_id, badge_type, expires_at) VALUES (?, ?, 'chicken', datetime('now','localtime','+' || ? || ' hours'))",
            (target_id, user["user_id"], CHICKEN_DURATION_HOURS),
        )

        new_count = current[0]["cnt"] + 1

        # 채팅 시스템 메시지
        sender_nick_row = await db.execute_fetchall("SELECT nickname FROM users WHERE id = ?", (user["user_id"],))
        sender_nick = sender_nick_row[0]["nickname"] if sender_nick_row else "???"
        await insert_system_message(db, f"🐔 {sender_nick}님이 {target_nick}님에게 닭대가리를 씌웠습니다! ({'🐔' * new_count})")

        # 전광판 (3마리 이상)
        if new_count >= 3:
            await insert_ticker(db, f"🐔 {target_nick}님 닭대가리 {new_count}마리 돌파!", "badge")

        await db.commit()

        new_bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],))
        return {
            "message": f"{target_nick}님에게 닭대가리를 씌웠습니다!",
            "target_chicken_count": new_count,
            "new_balance": new_bal[0]["points"] if new_bal else 0,
        }
    finally:
        await db.close()


@app.post("/api/shop/remove-chicken")
async def shop_remove_chicken(user=Depends(get_current_user)):
    db = await get_db()
    try:
        # 만료된 것 정리
        await db.execute(
            "DELETE FROM user_badges WHERE badge_type = 'chicken' AND expires_at <= datetime('now','localtime')"
        )

        # 내 닭 수 확인
        current = await db.execute_fetchall(
            "SELECT COUNT(*) as cnt FROM user_badges WHERE target_user_id = ? AND badge_type = 'chicken'",
            (user["user_id"],),
        )
        if current[0]["cnt"] == 0:
            raise HTTPException(400, "제거할 닭대가리가 없습니다")

        # 포인트 확인
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        if not bal or bal[0]["points"] < CHICKEN_REMOVE_COST:
            raise HTTPException(400, f"포인트가 부족합니다 ({CHICKEN_REMOVE_COST}P 필요)")

        # 포인트 차감
        await log_point_change(db, user["user_id"], -CHICKEN_REMOVE_COST, "상점", "닭대가리 소각")

        # 전체 삭제
        await db.execute(
            "DELETE FROM user_badges WHERE target_user_id = ? AND badge_type = 'chicken'",
            (user["user_id"],),
        )

        nick_row = await db.execute_fetchall("SELECT nickname FROM users WHERE id = ?", (user["user_id"],))
        nick = nick_row[0]["nickname"] if nick_row else "???"
        await insert_system_message(db, f"🔥 {nick}님이 닭대가리를 소각했습니다!")

        await db.commit()
        new_bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],))
        return {
            "message": "닭대가리를 소각했습니다!",
            "new_balance": new_bal[0]["points"] if new_bal else 0,
        }
    finally:
        await db.close()


@app.get("/api/badge/me")
async def get_my_badge(user=Depends(get_current_user)):
    db = await get_db()
    try:
        badge = await get_user_badge_str(db, user["user_id"])
        # 내 닭 상세 정보
        chickens = await db.execute_fetchall(
            """SELECT ub.id, u.nickname as sender, ub.expires_at
               FROM user_badges ub JOIN users u ON ub.sender_user_id = u.id
               WHERE ub.target_user_id = ? AND ub.badge_type = 'chicken'
                 AND ub.expires_at > datetime('now','localtime')
               ORDER BY ub.created_at ASC""",
            (user["user_id"],),
        )
        return {
            "badge": badge,
            "chickens": [{"sender": c["sender"], "expires_at": c["expires_at"]} for c in chickens],
        }
    finally:
        await db.close()


@app.get("/api/users/list")
async def users_list(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, nickname FROM users WHERE is_approved = 1 AND is_admin = 0 AND id != ?",
            (user["user_id"],),
        )
        return [{"id": r["id"], "nickname": r["nickname"]} for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# POINT GIFT (포인트 선물)
# ═══════════════════════════════════════════════

@app.post("/api/points/gift")
async def send_gift(req: PointGiftRequest, user=Depends(get_current_user)):
    if req.amount < 10:
        raise HTTPException(400, "최소 10 포인트부터 선물할 수 있습니다")

    db = await get_db()
    try:
        # 받는 사람 확인
        recipients = await db.execute_fetchall(
            "SELECT id, nickname FROM users WHERE nickname = ? AND is_approved = 1",
            (req.to_nickname,)
        )
        if not recipients:
            raise HTTPException(404, "해당 닉네임의 유저를 찾을 수 없습니다")
        to_user = recipients[0]
        if to_user["id"] == user["user_id"]:
            raise HTTPException(400, "자기 자신에게는 선물할 수 없습니다")

        # 잔고 확인
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        if not bal or bal[0]["points"] < req.amount:
            raise HTTPException(400, "포인트가 부족합니다")

        # 차감 & 지급
        await log_point_change(db, user["user_id"], -req.amount, "포인트 선물", f"{to_user['nickname']}에게 선물")
        await log_point_change(db, to_user["id"], req.amount, "포인트 선물", f"선물 받음 ({req.message or ''})")
        await db.execute(
            "INSERT INTO point_gifts (from_user_id, to_user_id, amount, message) VALUES (?, ?, ?, ?)",
            (user["user_id"], to_user["id"], req.amount, req.message)
        )
        await db.commit()

        new_bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        return {
            "message": f"{to_user['nickname']}님에게 {req.amount}P를 선물했습니다!",
            "new_balance": new_bal[0]["points"] if new_bal else 0,
        }
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# DICE GAME (주사위 게임)
# ═══════════════════════════════════════════════

@app.post("/api/dice/rooms")
async def create_dice_room(req: DiceRoomCreateRequest, user=Depends(get_current_user)):
    if req.dice_min < 1 or req.dice_max < req.dice_min + 1:
        raise HTTPException(400, "주사위 범위가 올바르지 않습니다")
    if req.entry_fee < 10:
        raise HTTPException(400, "최소 참가비는 10P입니다")

    db = await get_db()
    try:
        # 이미 진행 중인 게임 참여 중인지 체크
        active = await db.execute_fetchall(
            """SELECT dp.room_id FROM dice_players dp
               JOIN dice_rooms dr ON dp.room_id = dr.id
               WHERE dp.user_id = ? AND dr.status IN ('WAITING','ROLLING')""",
            (user["user_id"],)
        )
        if active:
            raise HTTPException(400, "이미 다른 게임에 참여 중입니다")

        # 포인트 체크
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        pts = bal[0]["points"] if bal else 0
        if pts < req.entry_fee:
            raise HTTPException(400, "포인트가 부족합니다")

        # 방 생성 (참가비는 라운드 시작 시 차감)
        cursor = await db.execute(
            """INSERT INTO dice_rooms (creator_id, mode, dice_min, dice_max, entry_fee, total_pot)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (user["user_id"], req.mode, req.dice_min, req.dice_max, req.entry_fee)
        )
        room_id = cursor.lastrowid

        # 방장 자동 입장 (참가비 차감 없음)
        await db.execute(
            "INSERT INTO dice_players (room_id, user_id, is_ready) VALUES (?, ?, 1)",
            (room_id, user["user_id"])
        )
        await db.commit()
        return {"room_id": room_id, "message": "방 생성 완료"}
    finally:
        await db.close()


@app.get("/api/dice/rooms")
async def list_dice_rooms(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            """SELECT dr.*, u.nickname as creator_name,
                      (SELECT COUNT(*) FROM dice_players WHERE room_id = dr.id) as player_count
               FROM dice_rooms dr
               JOIN users u ON dr.creator_id = u.id
               WHERE dr.status IN ('WAITING','ROLLING')
               ORDER BY dr.created_at DESC"""
        )
        return [dict(r) for r in rooms]
    finally:
        await db.close()


@app.get("/api/dice/rooms/{room_id}")
async def get_dice_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            """SELECT dr.*, u.nickname as creator_name
               FROM dice_rooms dr JOIN users u ON dr.creator_id = u.id
               WHERE dr.id = ?""",
            (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = dict(rooms[0])

        # 참가자 목록
        players = await db.execute_fetchall(
            """SELECT dp.*, u.nickname FROM dice_players dp
               JOIN users u ON dp.user_id = u.id
               WHERE dp.room_id = ?
               ORDER BY dp.joined_at""",
            (room_id,)
        )
        room["players"] = [dict(p) for p in players]

        # 현재 라운드 주사위 기록
        if room["current_round"] > 0:
            rolls = await db.execute_fetchall(
                """SELECT dr2.*, u.nickname FROM dice_rolls dr2
                   JOIN users u ON dr2.user_id = u.id
                   WHERE dr2.room_id = ? AND dr2.round_number = ?""",
                (room_id, room["current_round"])
            )
            # FINISHED/CANCELLED이면 결과 확정이므로 전부 공개
            if room["status"] in ("FINISHED", "CANCELLED"):
                all_rolled = True
            else:
                alive_count = sum(1 for p in players if p["is_alive"])
                rolled_count = len(rolls)
                all_rolled = rolled_count >= alive_count

            roll_list = []
            for r in rolls:
                rd = dict(r)
                # 전원 굴리기 전에는 본인 것만 값 공개
                if not all_rolled and rd["user_id"] != user["user_id"]:
                    rd["roll_value"] = None
                roll_list.append(rd)
            room["current_rolls"] = roll_list
            room["all_rolled"] = all_rolled
        else:
            room["current_rolls"] = []
            room["all_rolled"] = False

        # 라운드 결과 판정 (프론트에서 사용)
        # winner_id가 있으면 승자 확정, pot이 0이면 무승부 환불됨, 그 외 아직 미결
        if room["current_round"] > 0 and room["status"] == "WAITING":
            if room["winner_id"] is not None:
                room["round_result"] = "WIN"
            elif room["total_pot"] == 0:
                room["round_result"] = "DRAW"
            else:
                room["round_result"] = None
        else:
            room["round_result"] = None

        # 이전 라운드 기록 (결과 공개용)
        if room["current_round"] > 1:
            prev_rolls = await db.execute_fetchall(
                """SELECT dr2.*, u.nickname FROM dice_rolls dr2
                   JOIN users u ON dr2.user_id = u.id
                   WHERE dr2.room_id = ? AND dr2.round_number < ?
                   ORDER BY dr2.round_number, dr2.roll_value DESC""",
                (room_id, room["current_round"])
            )
            room["previous_rounds"] = [dict(r) for r in prev_rolls]
        else:
            room["previous_rounds"] = []

        return room
    finally:
        await db.close()


@app.post("/api/dice/rooms/{room_id}/join")
async def join_dice_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]
        if room["status"] != "WAITING":
            raise HTTPException(400, "이미 게임이 시작되었거나 종료된 방입니다")

        # 이미 참가 중인지
        existing = await db.execute_fetchall(
            "SELECT 1 FROM dice_players WHERE room_id = ? AND user_id = ?",
            (room_id, user["user_id"])
        )
        if existing:
            raise HTTPException(400, "이미 참가 중입니다")

        # 다른 게임 참여 중인지
        active = await db.execute_fetchall(
            """SELECT dp.room_id FROM dice_players dp
               JOIN dice_rooms dr ON dp.room_id = dr.id
               WHERE dp.user_id = ? AND dr.status IN ('WAITING','ROLLING')""",
            (user["user_id"],)
        )
        if active:
            raise HTTPException(400, "이미 다른 게임에 참여 중입니다")

        # 포인트 체크
        bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        pts = bal[0]["points"] if bal else 0
        if pts < room["entry_fee"]:
            raise HTTPException(400, "포인트가 부족합니다")

        # 입장 (참가비는 라운드 시작 시 차감)
        await db.execute(
            "INSERT INTO dice_players (room_id, user_id) VALUES (?, ?)",
            (room_id, user["user_id"])
        )
        await db.commit()
        return {"message": "입장 완료"}
    finally:
        await db.close()


@app.post("/api/dice/rooms/{room_id}/ready")
async def toggle_dice_ready(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        player = await db.execute_fetchall(
            "SELECT * FROM dice_players WHERE room_id = ? AND user_id = ?",
            (room_id, user["user_id"])
        )
        if not player:
            raise HTTPException(400, "이 방에 참가하지 않았습니다")

        room = await db.execute_fetchall(
            "SELECT status FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not room or room[0]["status"] != "WAITING":
            raise HTTPException(400, "대기 중인 방에서만 준비할 수 있습니다")

        new_ready = 0 if player[0]["is_ready"] else 1
        await db.execute(
            "UPDATE dice_players SET is_ready = ? WHERE room_id = ? AND user_id = ?",
            (new_ready, room_id, user["user_id"])
        )
        await db.commit()
        return {"is_ready": bool(new_ready)}
    finally:
        await db.close()


@app.post("/api/dice/rooms/{room_id}/leave")
async def leave_dice_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["status"] != "WAITING":
            raise HTTPException(400, "대기 중인 방에서만 나갈 수 있습니다")

        player = await db.execute_fetchall(
            "SELECT * FROM dice_players WHERE room_id = ? AND user_id = ?",
            (room_id, user["user_id"])
        )
        if not player:
            raise HTTPException(400, "이 방에 참가하지 않았습니다")

        if room["creator_id"] == user["user_id"]:
            raise HTTPException(400, "방장은 나갈 수 없습니다. 방 끝내기를 이용하세요.")

        # 퇴장 (참가비 미차감 상태이므로 환불 없음)
        await db.execute(
            "DELETE FROM dice_players WHERE room_id = ? AND user_id = ?",
            (room_id, user["user_id"])
        )
        await db.commit()
        return {"message": "방에서 나갔습니다."}
    finally:
        await db.close()


@app.post("/api/dice/rooms/{room_id}/start-round")
async def start_dice_round(room_id: int, user=Depends(get_current_user)):
    """첫 게임 시작 또는 생존자 재투표"""
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["creator_id"] != user["user_id"]:
            raise HTTPException(403, "방장만 라운드를 시작할 수 있습니다")
        if room["status"] != "WAITING":
            raise HTTPException(400, "게임을 시작할 수 없는 상태입니다")
        if room["current_round"] > 0:
            raise HTTPException(400, "이미 결판났습니다. '한 판 더'를 이용하세요.")

        alive_players = await db.execute_fetchall(
            "SELECT * FROM dice_players WHERE room_id = ? AND is_alive = 1",
            (room_id,)
        )
        if len(alive_players) < 2:
            raise HTTPException(400, "최소 2명 이상 필요합니다")

        # 전원 준비 체크
        not_ready = [p for p in alive_players if not p["is_ready"]]
        if not_ready:
            raise HTTPException(400, "모든 참가자가 준비해야 합니다")

        # 참가비 차감 + pot 생성
        for p in alive_players:
            bal = await db.execute_fetchall(
                "SELECT points FROM point_balances WHERE user_id = ?", (p["user_id"],)
            )
            pts = bal[0]["points"] if bal else 0
            if pts < room["entry_fee"]:
                raise HTTPException(400, f"포인트가 부족한 참가자가 있습니다")

        pot = room["entry_fee"] * len(alive_players)
        for p in alive_players:
            await log_point_change(db, p["user_id"], -room["entry_fee"], "주사위 참가", f"방 #{room_id} 라운드 시작")

        new_round = room["current_round"] + 1
        await db.execute(
            "UPDATE dice_rooms SET status = 'ROLLING', current_round = ?, total_pot = ? WHERE id = ?",
            (new_round, pot, room_id)
        )
        await db.commit()
        return {"round": new_round, "message": f"라운드 {new_round} 시작!"}
    finally:
        await db.close()


@app.post("/api/dice/rooms/{room_id}/next-game")
async def next_dice_game(room_id: int, user=Depends(get_current_user)):
    """한 판 더 — 참가비 재차감 후 새 라운드"""
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["creator_id"] != user["user_id"]:
            raise HTTPException(403, "방장만 시작할 수 있습니다")
        if room["status"] != "WAITING" or room["current_round"] == 0:
            raise HTTPException(400, "한 판 더를 시작할 수 없는 상태입니다")

        all_players = await db.execute_fetchall(
            """SELECT dp.user_id, dp.is_ready, COALESCE(pb.points, 0) as points
               FROM dice_players dp
               LEFT JOIN point_balances pb ON dp.user_id = pb.user_id
               WHERE dp.room_id = ?""",
            (room_id,)
        )

        # 전원 준비 체크
        not_ready = [p for p in all_players if not p["is_ready"]]
        if not_ready:
            raise HTTPException(400, "모든 참가자가 준비해야 합니다")

        participating = []
        excluded = []
        for p in all_players:
            if p["points"] >= room["entry_fee"]:
                participating.append(p["user_id"])
            else:
                excluded.append(p["user_id"])

        if len(participating) < 2:
            raise HTTPException(400, f"포인트가 충분한 참가자가 {len(participating)}명뿐입니다 (최소 2명)")

        # 플레이어 리셋 + 참가비 차감
        for uid in participating:
            await db.execute(
                "UPDATE dice_players SET is_alive = 1, is_ready = 0, eliminated_round = NULL WHERE room_id = ? AND user_id = ?",
                (room_id, uid)
            )
            await log_point_change(db, uid, -room["entry_fee"], "주사위 참가", f"방 #{room_id} 한판더")
        for uid in excluded:
            await db.execute(
                "UPDATE dice_players SET is_alive = 0, is_ready = 0 WHERE room_id = ? AND user_id = ?",
                (room_id, uid)
            )

        pot = room["entry_fee"] * len(participating)
        new_round = room["current_round"] + 1
        await db.execute(
            "UPDATE dice_rooms SET status = 'ROLLING', current_round = ?, total_pot = ?, winner_id = NULL, finished_at = NULL WHERE id = ?",
            (new_round, pot, room_id)
        )
        await db.commit()
        return {
            "round": new_round,
            "participants": len(participating),
            "excluded": len(excluded),
            "pot": pot,
            "message": f"한 판 더! 라운드 {new_round} ({len(participating)}명 참가, 판돈 {pot}P)"
        }
    finally:
        await db.close()


@app.post("/api/dice/rooms/{room_id}/roll")
async def roll_dice(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["status"] != "ROLLING":
            raise HTTPException(400, "주사위를 굴릴 수 없는 상태입니다")

        # 참가자이며 생존 중인지
        player = await db.execute_fetchall(
            "SELECT * FROM dice_players WHERE room_id = ? AND user_id = ? AND is_alive = 1",
            (room_id, user["user_id"])
        )
        if not player:
            raise HTTPException(400, "이 라운드에 참가할 수 없습니다")

        # 이미 이번 라운드에 굴렸는지
        already = await db.execute_fetchall(
            "SELECT 1 FROM dice_rolls WHERE room_id = ? AND round_number = ? AND user_id = ?",
            (room_id, room["current_round"], user["user_id"])
        )
        if already:
            raise HTTPException(400, "이미 주사위를 굴렸습니다")

        # 주사위 굴리기
        roll_value = random.randint(room["dice_min"], room["dice_max"])
        await db.execute(
            "INSERT INTO dice_rolls (room_id, round_number, user_id, roll_value) VALUES (?, ?, ?, ?)",
            (room_id, room["current_round"], user["user_id"], roll_value)
        )

        # 전원 굴림 완료 체크
        alive_players = await db.execute_fetchall(
            "SELECT user_id FROM dice_players WHERE room_id = ? AND is_alive = 1",
            (room_id,)
        )
        rolled = await db.execute_fetchall(
            "SELECT user_id, roll_value FROM dice_rolls WHERE room_id = ? AND round_number = ?",
            (room_id, room["current_round"])
        )

        result = {"roll_value": roll_value, "waiting": True}

        if len(rolled) >= len(alive_players):
            # 전원 완료 → 동수 탈락 판정
            from collections import Counter
            values = [(r["user_id"], r["roll_value"]) for r in rolled]
            value_counts = Counter(v for _, v in values)

            # 2번 이상 나온 값 = 동수
            duplicate_values = {v for v, c in value_counts.items() if c > 1}

            eliminated_users = []
            surviving_users = []
            for uid, val in values:
                if val in duplicate_values:
                    eliminated_users.append(uid)
                    await db.execute(
                        "UPDATE dice_rolls SET eliminated = 1 WHERE room_id = ? AND round_number = ? AND user_id = ?",
                        (room_id, room["current_round"], uid)
                    )
                    await db.execute(
                        "UPDATE dice_players SET is_alive = 0, eliminated_round = ? WHERE room_id = ? AND user_id = ?",
                        (room["current_round"], room_id, uid)
                    )
                else:
                    surviving_users.append((uid, val))

            if len(surviving_users) == 0:
                # 전원 동수 탈락 → 무승부, 참가비 환불
                for uid in eliminated_users:
                    await log_point_change(db, uid, room["entry_fee"], "주사위 환불", f"방 #{room_id} 무승부")
                    await db.execute(
                        "UPDATE dice_players SET is_alive = 1, is_ready = 0, eliminated_round = NULL WHERE room_id = ? AND user_id = ?",
                        (room_id, uid)
                    )
                await db.execute(
                    "UPDATE dice_rooms SET status = 'WAITING', total_pot = 0 WHERE id = ?",
                    (room_id,)
                )
                result["draw"] = True
                result["message"] = "전원 동수! 무승부 — 참가비가 환불됩니다"

            else:
                # 생존자 1명+ → HIGH/LOW 모드에 따라 승자 결정
                if room["mode"] == "HIGH":
                    winner_id = max(surviving_users, key=lambda x: x[1])[0]
                else:
                    winner_id = min(surviving_users, key=lambda x: x[1])[0]

                await db.execute(
                    """UPDATE dice_rooms SET status = 'WAITING', winner_id = ?, total_pot = 0,
                       finished_at = datetime('now','localtime') WHERE id = ?""",
                    (winner_id, room_id)
                )
                await log_point_change(db, winner_id, room["total_pot"], "주사위 우승", f"방 #{room_id} 우승 ({room['total_pot']}P)")
                # 한판더 대비 준비상태 초기화
                await db.execute(
                    "UPDATE dice_players SET is_ready = 0 WHERE room_id = ?",
                    (room_id,)
                )
                await _update_dice_stats(db, room_id, winner_id, room["total_pot"])
                # 전광판: 주사위 주목 이벤트
                winner_row = await db.execute_fetchall("SELECT nickname FROM users WHERE id = ?", (winner_id,))
                winner_nick = winner_row[0]["nickname"] if winner_row else "???"
                player_cnt = len(await db.execute_fetchall("SELECT user_id FROM dice_players WHERE room_id = ?", (room_id,)))
                await check_dice_notable_event(db, winner_id, winner_nick, room["total_pot"], player_cnt)
                await check_point_leader_change(db)
                result["finished"] = True
                result["winner_id"] = winner_id

            result["waiting"] = False

        await db.commit()
        return result
    finally:
        await db.close()


async def _update_dice_stats(db, room_id, winner_id, total_pot):
    """게임 종료 시 모든 참가자 통계 갱신"""
    players = await db.execute_fetchall(
        "SELECT user_id FROM dice_players WHERE room_id = ?", (room_id,)
    )
    for p in players:
        uid = p["user_id"]
        is_winner = uid == winner_id

        # upsert stats
        await db.execute(
            """INSERT INTO dice_stats (user_id, total_games, total_wins,
                   current_win_streak, max_win_streak,
                   current_loss_streak, max_loss_streak,
                   total_earned, total_lost)
               VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   total_games = total_games + 1,
                   total_wins = total_wins + ?,
                   current_win_streak = CASE WHEN ? THEN current_win_streak + 1 ELSE 0 END,
                   max_win_streak = CASE WHEN ? THEN MAX(max_win_streak, current_win_streak + 1) ELSE max_win_streak END,
                   current_loss_streak = CASE WHEN ? THEN 0 ELSE current_loss_streak + 1 END,
                   max_loss_streak = CASE WHEN ? THEN max_loss_streak ELSE MAX(max_loss_streak, current_loss_streak + 1) END,
                   total_earned = total_earned + ?,
                   total_lost = total_lost + ?""",
            (uid,
             1 if is_winner else 0,  # total_wins initial
             1 if is_winner else 0,  # current_win_streak initial
             1 if is_winner else 0,  # max_win_streak initial
             0 if is_winner else 1,  # current_loss_streak initial
             0 if is_winner else 1,  # max_loss_streak initial
             total_pot if is_winner else 0,  # total_earned initial
             0 if is_winner else 0,  # total_lost initial (entry fee already deducted)
             # ON CONFLICT params:
             1 if is_winner else 0,  # total_wins increment
             is_winner,  # win streak check
             is_winner,  # max win streak check
             is_winner,  # loss streak reset check
             is_winner,  # max loss streak check
             total_pot if is_winner else 0,  # earned
             0,  # lost (already deducted on join)
             )
        )


@app.post("/api/dice/rooms/{room_id}/cancel")
async def cancel_dice_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["creator_id"] != user["user_id"]:
            raise HTTPException(403, "방장만 취소할 수 있습니다")
        if room["status"] not in ("WAITING", "ROLLING"):
            raise HTTPException(400, "이미 종료된 방입니다")

        # 진행 중(ROLLING)이고 pot이 있을 때만 환불 (참가비가 차감된 상태)
        if room["status"] == "ROLLING" and room["total_pot"] > 0:
            alive_players = await db.execute_fetchall(
                "SELECT user_id FROM dice_players WHERE room_id = ? AND is_alive = 1",
                (room_id,)
            )
            for p in alive_players:
                await log_point_change(db, p["user_id"], room["entry_fee"], "주사위 환불", f"방 #{room_id} 취소")

        await db.execute(
            "UPDATE dice_rooms SET status = 'CANCELLED' WHERE id = ?", (room_id,)
        )
        await db.commit()
        return {"message": "방이 종료되었습니다."}
    finally:
        await db.close()


@app.get("/api/admin/omok/rooms")
async def admin_list_omok_rooms(user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            """SELECT r.id, r.bet_amount, r.status, r.move_count, r.created_at,
                      c.nickname as creator_name, o.nickname as opponent_name
               FROM omok_rooms r
               JOIN users c ON r.creator_id = c.id
               LEFT JOIN users o ON r.opponent_id = o.id
               WHERE r.status IN ('WAITING', 'PLAYING')
               ORDER BY r.created_at DESC"""
        )
        return [dict(r) for r in rooms]
    finally:
        await db.close()


@app.post("/api/admin/omok/rooms/{room_id}/destroy")
async def admin_destroy_omok_room(room_id: int, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM omok_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["status"] not in ("WAITING", "PLAYING"):
            raise HTTPException(400, "이미 종료된 방입니다")

        # 참가자 베팅금 환불
        if room["bet_amount"] > 0:
            await log_point_change(db, room["creator_id"], room["bet_amount"], "오목 환불", f"관리자 방 #{room_id} 강제 종료")
            if room["opponent_id"]:
                await log_point_change(db, room["opponent_id"], room["bet_amount"], "오목 환불", f"관리자 방 #{room_id} 강제 종료")

        # 관전 배팅 환불
        await _settle_spectator_bets(db, "omok", room_id, 0, is_draw=True)

        await db.execute(
            "UPDATE omok_rooms SET status = 'CANCELLED' WHERE id = ?", (room_id,)
        )
        await db.commit()
        return {"message": f"오목 방 #{room_id}이 강제 종료되었습니다. 베팅금이 환불되었습니다."}
    finally:
        await db.close()


@app.get("/api/admin/chess/rooms")
async def admin_list_chess_rooms(user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            """SELECT r.id, r.bet_amount, r.status, r.move_count, r.created_at,
                      c.nickname as creator_name, o.nickname as opponent_name
               FROM chess_rooms r
               JOIN users c ON r.creator_id = c.id
               LEFT JOIN users o ON r.opponent_id = o.id
               WHERE r.status IN ('WAITING', 'PLAYING')
               ORDER BY r.created_at DESC"""
        )
        return [dict(r) for r in rooms]
    finally:
        await db.close()


@app.post("/api/admin/chess/rooms/{room_id}/destroy")
async def admin_destroy_chess_room(room_id: int, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM chess_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["status"] not in ("WAITING", "PLAYING"):
            raise HTTPException(400, "이미 종료된 방입니다")

        # 참가자 베팅금 환불
        if room["bet_amount"] > 0:
            await log_point_change(db, room["creator_id"], room["bet_amount"], "체스 환불", f"관리자 방 #{room_id} 강제 종료")
            if room["opponent_id"]:
                await log_point_change(db, room["opponent_id"], room["bet_amount"], "체스 환불", f"관리자 방 #{room_id} 강제 종료")

        # 관전 배팅 환불
        await _settle_spectator_bets(db, "chess", room_id, 0, is_draw=True)

        await db.execute(
            "UPDATE chess_rooms SET status = 'CANCELLED' WHERE id = ?", (room_id,)
        )
        await db.commit()
        return {"message": f"체스 방 #{room_id}이 강제 종료되었습니다. 베팅금이 환불되었습니다."}
    finally:
        await db.close()


@app.get("/api/admin/dice/rooms")
async def admin_list_dice_rooms(user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            """SELECT dr.*, u.nickname as creator_name,
                      (SELECT COUNT(*) FROM dice_players WHERE room_id = dr.id) as player_count
               FROM dice_rooms dr
               JOIN users u ON dr.creator_id = u.id
               WHERE dr.status IN ('WAITING', 'ROLLING')
               ORDER BY dr.created_at DESC"""
        )
        return [dict(r) for r in rooms]
    finally:
        await db.close()


@app.post("/api/admin/dice/rooms/{room_id}/destroy")
async def admin_destroy_dice_room(room_id: int, user=Depends(get_admin_user)):
    db = await get_db()
    try:
        rooms = await db.execute_fetchall(
            "SELECT * FROM dice_rooms WHERE id = ?", (room_id,)
        )
        if not rooms:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rooms[0]

        if room["status"] not in ("WAITING", "ROLLING"):
            raise HTTPException(400, "이미 종료된 방입니다")

        # 살아있는 플레이어 전원 환불
        if room["total_pot"] > 0:
            alive_players = await db.execute_fetchall(
                "SELECT user_id FROM dice_players WHERE room_id = ? AND is_alive = 1",
                (room_id,)
            )
            for p in alive_players:
                await log_point_change(db, p["user_id"], room["entry_fee"], "주사위 환불", f"관리자 방 #{room_id} 폭파")

        await db.execute(
            "UPDATE dice_rooms SET status = 'CANCELLED' WHERE id = ?", (room_id,)
        )
        await db.commit()
        return {"message": f"방 #{room_id}이 폭파되었습니다. 참가자들이 다른 방에 참여할 수 있습니다."}
    finally:
        await db.close()


@app.get("/api/dice/history")
async def dice_history(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT dr.id, dr.mode, dr.dice_min, dr.dice_max, dr.entry_fee,
                      dr.total_pot, dr.status, dr.current_round, dr.created_at, dr.finished_at,
                      u.nickname as winner_name,
                      (SELECT COUNT(*) FROM dice_players WHERE room_id = dr.id) as player_count
               FROM dice_rooms dr
               LEFT JOIN users u ON dr.winner_id = u.id
               JOIN dice_players dp ON dp.room_id = dr.id AND dp.user_id = ?
               WHERE dr.status = 'CANCELLED' OR dr.finished_at IS NOT NULL
               ORDER BY COALESCE(dr.finished_at, dr.created_at) DESC LIMIT 20""",
            (user["user_id"],)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# TRADE LOGS
# ═══════════════════════════════════════════════

@app.get("/api/trades")
async def get_trade_logs(user=Depends(get_current_user)):
    db = await get_db()
    try:
        month = current_month()
        rows = await db.execute_fetchall(
            """SELECT t.*, s.name as stock_name FROM trade_logs t
               LEFT JOIN stocks s ON t.stock_code = s.code
               WHERE t.user_id = ? AND t.month = ?
               ORDER BY t.traded_at DESC LIMIT 50""",
            (user["user_id"], month)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# NORDLE (수식 맞추기 게임)
# ═══════════════════════════════════════════════

NORDLE_MAX = 6
NORDLE_LEN = 8  # 기본 수식 길이


def _is_valid_equation(eq: str) -> bool:
    """수식이 올바른 산술식인지 검증 (예: 12+34=46)."""
    if not re.fullmatch(r'[\d+\-*/=]+', eq):
        return False
    if eq.count('=') != 1:
        return False
    left, right = eq.split('=')
    if not left or not right:
        return False
    # 우변: 양의 정수 (선행 0 없음)
    if not re.fullmatch(r'0|[1-9]\d*', right):
        return False
    # 좌변: 숫자와 연산자가 번갈아 오는 형태
    if not re.fullmatch(r'\d+([+\-*/]\d+)+', left):
        return False
    # 좌변 피연산자에 선행 0 없음
    for operand in re.split(r'[+\-*/]', left):
        if len(operand) > 1 and operand.startswith('0'):
            return False
    try:
        result = eval(left)  # nosec — 문자셋 검증 완료
        if not isinstance(result, (int, float)):
            return False
        if isinstance(result, float) and result % 1 != 0:
            return False
        return int(result) == int(right) and result >= 0
    except ZeroDivisionError:
        return False
    except Exception:
        return False


def _compute_colors(guess: str, answer: str) -> list:
    """Wordle 방식으로 각 문자의 색상(green/yellow/gray) 반환."""
    n = len(guess)
    colors = ['gray'] * n
    ans_pool = list(answer)
    guess_pool = list(guess)

    # 1차: 정확한 위치(green)
    for i in range(n):
        if i < len(answer) and guess[i] == answer[i]:
            colors[i] = 'green'
            ans_pool[i] = None
            guess_pool[i] = None

    # 2차: 포함되지만 위치 다름(yellow)
    for i in range(n):
        if guess_pool[i] is not None and guess_pool[i] in ans_pool:
            colors[i] = 'yellow'
            ans_pool[ans_pool.index(guess_pool[i])] = None

    return colors


def _generate_equation(target_len: int = NORDLE_LEN) -> str:
    """target_len 길이의 올바른 수식 랜덤 생성."""
    for _ in range(200_000):
        op = random.choice(['+', '-', '*'])
        if op == '+':
            a = random.randint(1, 999)
            b = random.randint(1, 999)
            c = a + b
        elif op == '-':
            a = random.randint(2, 999)
            b = random.randint(1, a - 1)
            c = a - b
        else:
            a = random.randint(2, 99)
            b = random.randint(2, 99)
            c = a * b
        eq = f"{a}{op}{b}={c}"
        if len(eq) == target_len:
            return eq
    # 길이 고정 폴백 목록
    fallbacks = {
        6: "3+5=8", 7: "12+5=17", 8: "23+45=68", 9: "123+45=168"
    }
    return fallbacks.get(target_len, "23+45=68")


@app.get("/api/nordle/today")
async def nordle_today(user=Depends(get_current_user)):
    db = await get_db()
    today = dt.now().strftime("%Y-%m-%d")
    try:
        puzzle = await db.execute_fetchall(
            "SELECT equation FROM nordle_puzzles WHERE date = ?", (today,)
        )
        if not puzzle:
            eq = _generate_equation()
            await db.execute(
                "INSERT OR IGNORE INTO nordle_puzzles (date, equation) VALUES (?, ?)",
                (today, eq)
            )
            await db.commit()
        else:
            eq = puzzle[0]["equation"]

        game = await db.execute_fetchall(
            "SELECT * FROM nordle_games WHERE user_id = ? AND date = ?",
            (user["user_id"], today)
        )

        if not game:
            return {
                "length": len(eq), "max_attempts": NORDLE_MAX,
                "guesses": [], "solved": False, "game_over": False, "answer": None,
            }

        g = game[0]
        raw_guesses = json.loads(g["guesses"])
        solved = bool(g["solved"])
        game_over = solved or len(raw_guesses) >= NORDLE_MAX

        guesses_with_colors = [
            {"guess": gu, "colors": _compute_colors(gu, eq)}
            for gu in raw_guesses
        ]

        return {
            "length": len(eq), "max_attempts": NORDLE_MAX,
            "guesses": guesses_with_colors,
            "solved": solved,
            "game_over": game_over,
            "answer": eq if game_over else None,
        }
    finally:
        await db.close()


@app.post("/api/nordle/guess")
async def nordle_guess(req: NordleGuessRequest, user=Depends(get_current_user)):
    db = await get_db()
    today = dt.now().strftime("%Y-%m-%d")
    try:
        puzzle = await db.execute_fetchall(
            "SELECT equation FROM nordle_puzzles WHERE date = ?", (today,)
        )
        if not puzzle:
            raise HTTPException(404, "오늘의 퍼즐이 없습니다")
        eq = puzzle[0]["equation"]

        guess = req.guess.strip()
        if len(guess) != len(eq):
            raise HTTPException(400, f"수식 길이는 {len(eq)}자여야 합니다")
        if not _is_valid_equation(guess):
            raise HTTPException(400, "올바른 수식이 아닙니다 (예: 12+34=46)")

        game = await db.execute_fetchall(
            "SELECT * FROM nordle_games WHERE user_id = ? AND date = ?",
            (user["user_id"], today)
        )
        if game:
            if game[0]["solved"]:
                raise HTTPException(400, "이미 정답을 맞혔습니다")
            raw = json.loads(game[0]["guesses"])
            if len(raw) >= NORDLE_MAX:
                raise HTTPException(400, "시도 횟수를 모두 사용했습니다")
        else:
            raw = []

        raw.append(guess)
        solved = (guess == eq)
        game_over = solved or len(raw) >= NORDLE_MAX
        finished_at = dt.now().strftime("%Y-%m-%d %H:%M:%S") if game_over else None

        if game:
            await db.execute(
                "UPDATE nordle_games SET guesses=?, solved=?, finished_at=? WHERE user_id=? AND date=?",
                (json.dumps(raw), int(solved), finished_at, user["user_id"], today)
            )
        else:
            await db.execute(
                "INSERT INTO nordle_games (user_id, date, guesses, solved, finished_at) VALUES (?,?,?,?,?)",
                (user["user_id"], today, json.dumps(raw), int(solved), finished_at)
            )
        await db.commit()

        return {
            "colors": _compute_colors(guess, eq),
            "solved": solved,
            "game_over": game_over,
            "attempts": len(raw),
            "answer": eq if game_over else None,
        }
    finally:
        await db.close()


@app.get("/api/nordle/leaderboard")
async def nordle_leaderboard(user=Depends(get_current_user)):
    db = await get_db()
    today = dt.now().strftime("%Y-%m-%d")
    try:
        rows = await db.execute_fetchall(
            """SELECT g.*, u.nickname
               FROM nordle_games g
               JOIN users u ON g.user_id = u.id
               WHERE g.date = ?
               ORDER BY g.solved DESC,
                        CASE WHEN g.solved=1 THEN json_array_length(g.guesses) ELSE 999 END ASC,
                        g.finished_at ASC""",
            (today,)
        )
        leaderboard = []
        for i, r in enumerate(rows):
            guesses = json.loads(r["guesses"])
            leaderboard.append({
                "rank": i + 1,
                "user_id": r["user_id"],
                "nickname": r["nickname"],
                "solved": bool(r["solved"]),
                "attempts": len(guesses),
                "max_attempts": NORDLE_MAX,
                "finished_at": r["finished_at"],
            })
        return {"date": today, "leaderboard": leaderboard}
    finally:
        await db.close()


@app.post("/api/nordle/puzzle")
async def set_nordle_puzzle(req: NordlePuzzleRequest, user=Depends(get_admin_user)):
    if not _is_valid_equation(req.equation):
        raise HTTPException(400, "올바른 수식이 아닙니다")
    db = await get_db()
    target_date = req.date or dt.now().strftime("%Y-%m-%d")
    try:
        await db.execute(
            "INSERT OR REPLACE INTO nordle_puzzles (date, equation) VALUES (?, ?)",
            (target_date, req.equation)
        )
        await db.commit()
        return {"message": f"퍼즐 설정 완료: {req.equation} ({target_date})"}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# OMOK (오목 - 렌주룰)
# ═══════════════════════════════════════════════

OMOK_SIZE = 19

def _empty_board():
    return [[0]*OMOK_SIZE for _ in range(OMOK_SIZE)]

def _count_direction(board, x, y, dx, dy, color):
    """한 방향으로 연속된 같은 색 돌 수 세기"""
    cnt = 0
    nx, ny = x + dx, y + dy
    while 0 <= nx < OMOK_SIZE and 0 <= ny < OMOK_SIZE and board[ny][nx] == color:
        cnt += 1
        nx += dx
        ny += dy
    return cnt

def _check_five(board, x, y, color):
    """5목 이상 완성 여부 확인. (연속 개수, 정확히5목여부) 반환"""
    dirs = [(1,0),(0,1),(1,1),(1,-1)]
    for dx, dy in dirs:
        cnt = 1 + _count_direction(board, x, y, dx, dy, color) + _count_direction(board, x, y, -dx, -dy, color)
        if cnt >= 5:
            return cnt
    return 0

def _is_overline(board, x, y, color):
    """장목(6목 이상) 체크"""
    dirs = [(1,0),(0,1),(1,1),(1,-1)]
    for dx, dy in dirs:
        cnt = 1 + _count_direction(board, x, y, dx, dy, color) + _count_direction(board, x, y, -dx, -dy, color)
        if cnt >= 6:
            return True
    return False

def _count_open_pattern(board, x, y, color, target_len):
    """특정 방향에서 열린 패턴(활삼/사) 수를 세기. target_len=3이면 활삼, 4이면 사."""
    dirs = [(1,0),(0,1),(1,1),(1,-1)]
    count = 0
    for dx, dy in dirs:
        # 해당 방향으로 연속된 돌 수
        pos_cnt = _count_direction(board, x, y, dx, dy, color)
        neg_cnt = _count_direction(board, x, y, -dx, -dy, color)
        total = 1 + pos_cnt + neg_cnt

        if target_len == 4:
            # 사(四): 연속 4개 + 한쪽이라도 빈칸 (= 5목 가능)
            if total == 4:
                # 양 끝 확인
                end1_x, end1_y = x + dx*(pos_cnt+1), y + dy*(pos_cnt+1)
                end2_x, end2_y = x - dx*(neg_cnt+1), y - dy*(neg_cnt+1)
                open1 = 0 <= end1_x < OMOK_SIZE and 0 <= end1_y < OMOK_SIZE and board[end1_y][end1_x] == 0
                open2 = 0 <= end2_x < OMOK_SIZE and 0 <= end2_y < OMOK_SIZE and board[end2_y][end2_x] == 0
                if open1 or open2:
                    count += 1
            # 띈 사 체크 (예: XO_OOX 패턴)
            elif total == 3:
                # 양 끝 방향으로 하나 건너 돌이 있는지
                for sign in [1, -1]:
                    edge_cnt = pos_cnt if sign == 1 else neg_cnt
                    gap_x = x + sign*dx*(edge_cnt+1)
                    gap_y = y + sign*dy*(edge_cnt+1)
                    if 0 <= gap_x < OMOK_SIZE and 0 <= gap_y < OMOK_SIZE and board[gap_y][gap_x] == 0:
                        beyond_x = gap_x + sign*dx
                        beyond_y = gap_y + sign*dy
                        if 0 <= beyond_x < OMOK_SIZE and 0 <= beyond_y < OMOK_SIZE and board[beyond_y][beyond_x] == color:
                            count += 1

        elif target_len == 3:
            # 활삼(活三): 연속 3개 + 양쪽 빈칸 (열린 삼)
            if total == 3:
                end1_x, end1_y = x + dx*(pos_cnt+1), y + dy*(pos_cnt+1)
                end2_x, end2_y = x - dx*(neg_cnt+1), y - dy*(neg_cnt+1)
                open1 = 0 <= end1_x < OMOK_SIZE and 0 <= end1_y < OMOK_SIZE and board[end1_y][end1_x] == 0
                open2 = 0 <= end2_x < OMOK_SIZE and 0 <= end2_y < OMOK_SIZE and board[end2_y][end2_x] == 0
                if open1 and open2:
                    # 추가: 양끝 바깥이 상대 돌로 막혀있지 않은지
                    count += 1

    return count

def _is_forbidden_move(board, x, y):
    """렌주룰: 흑(1)의 금수 체크. board[y][x]에 이미 흑돌이 놓인 상태에서 호출."""
    color = 1  # black
    # 1. 장목(6목 이상)
    if _is_overline(board, x, y, color):
        return True, "overline"
    # 정확히 5목이면 금수가 아닌 승리
    if _check_five(board, x, y, color) == 5:
        return False, None
    # 2. 쌍사(Double Four)
    fours = _count_open_pattern(board, x, y, color, 4)
    if fours >= 2:
        return True, "double_four"
    # 3. 쌍삼(Double Three)
    threes = _count_open_pattern(board, x, y, color, 3)
    if threes >= 2:
        return True, "double_three"
    return False, None

def _calc_mmr_change(winner_mmr, loser_mmr, k=32):
    """Elo rating 변동 계산"""
    expected_w = 1 / (1 + 10**((loser_mmr - winner_mmr) / 400))
    expected_l = 1 - expected_w
    w_change = round(k * (1 - expected_w))
    l_change = round(k * (0 - expected_l))
    return w_change, l_change


@app.post("/api/omok/rooms")
async def create_omok_room(req: OmokRoomCreateRequest, user=Depends(get_current_user)):
    if req.bet_amount < 0:
        raise HTTPException(400, "베팅 금액이 올바르지 않습니다")
    db = await get_db()
    try:
        # 이미 진행 중인 방이 있는지 확인
        existing = await db.execute_fetchall(
            "SELECT id FROM omok_rooms WHERE (creator_id = ? OR opponent_id = ?) AND status IN ('WAITING','PLAYING')",
            (user["user_id"], user["user_id"])
        )
        if existing:
            raise HTTPException(400, "이미 참여 중인 오목 방이 있습니다")

        if req.bet_amount > 0:
            bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],))
            if not bal or bal[0]["points"] < req.bet_amount:
                raise HTTPException(400, "포인트가 부족합니다")
            await log_point_change(db, user["user_id"], -req.bet_amount, "omok", f"오목 베팅 ({req.bet_amount}P)")

        board = json.dumps(_empty_board())
        cursor = await db.execute(
            """INSERT INTO omok_rooms (creator_id, bet_amount, board, current_turn, creator_color)
               VALUES (?, ?, ?, 'B', 'B')""",
            (user["user_id"], req.bet_amount, board)
        )
        room_id = cursor.lastrowid
        await db.commit()
        return {"room_id": room_id}
    finally:
        await db.close()


@app.get("/api/omok/rooms")
async def list_omok_rooms(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT r.*, u1.nickname as creator_name, u2.nickname as opponent_name
               FROM omok_rooms r
               JOIN users u1 ON r.creator_id = u1.id
               LEFT JOIN users u2 ON r.opponent_id = u2.id
               WHERE r.status IN ('WAITING','PLAYING')
               ORDER BY r.created_at DESC"""
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/omok/rooms/{room_id}")
async def get_omok_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT r.*, u1.nickname as creator_name, u2.nickname as opponent_name
               FROM omok_rooms r
               JOIN users u1 ON r.creator_id = u1.id
               LEFT JOIN users u2 ON r.opponent_id = u2.id
               WHERE r.id = ?""",
            (room_id,)
        )
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = dict(rows[0])
        room["board"] = json.loads(room["board"])
        # 승자 닉네임
        if room.get("winner_id"):
            w = await db.execute_fetchall("SELECT nickname FROM users WHERE id=?", (room["winner_id"],))
            room["winner_name"] = w[0]["nickname"] if w else None
        # 최근 수순
        moves = await db.execute_fetchall(
            "SELECT * FROM omok_moves WHERE room_id = ? ORDER BY move_number",
            (room_id,)
        )
        room["moves"] = [dict(m) for m in moves]
        return room
    finally:
        await db.close()


@app.post("/api/omok/rooms/{room_id}/join")
async def join_omok_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM omok_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "WAITING":
            raise HTTPException(400, "참가할 수 없는 상태입니다")
        if room["creator_id"] == user["user_id"]:
            raise HTTPException(400, "자신의 방에 참가할 수 없습니다")

        # 이미 다른 방에 참여 중인지
        existing = await db.execute_fetchall(
            "SELECT id FROM omok_rooms WHERE (creator_id = ? OR opponent_id = ?) AND status IN ('WAITING','PLAYING')",
            (user["user_id"], user["user_id"])
        )
        if existing:
            raise HTTPException(400, "이미 참여 중인 오목 방이 있습니다")

        if room["bet_amount"] > 0:
            bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],))
            if not bal or bal[0]["points"] < room["bet_amount"]:
                raise HTTPException(400, "포인트가 부족합니다")
            await log_point_change(db, user["user_id"], -room["bet_amount"], "omok", f"오목 베팅 ({room['bet_amount']}P)")

        await db.execute(
            "UPDATE omok_rooms SET opponent_id = ?, status = 'PLAYING' WHERE id = ?",
            (user["user_id"], room_id)
        )
        await db.commit()
        return {"message": "입장 완료"}
    finally:
        await db.close()


@app.post("/api/omok/rooms/{room_id}/move")
async def omok_move(room_id: int, req: OmokMoveRequest, user=Depends(get_current_user)):
    if not (0 <= req.x < OMOK_SIZE and 0 <= req.y < OMOK_SIZE):
        raise HTTPException(400, "좌표가 범위를 벗어났습니다")

    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM omok_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")

        # 차례 확인
        uid = user["user_id"]
        if room["current_turn"] == room["creator_color"]:
            if uid != room["creator_id"]:
                raise HTTPException(400, "상대방의 차례입니다")
        else:
            if uid != room["opponent_id"]:
                raise HTTPException(400, "상대방의 차례입니다")

        board = json.loads(room["board"])
        if board[req.y][req.x] != 0:
            raise HTTPException(400, "이미 돌이 놓인 자리입니다")

        current_color = 1 if room["current_turn"] == "B" else 2  # 1=black, 2=white
        board[req.y][req.x] = current_color

        result = {"winner": None, "reason": None, "forbidden": None}

        # 렌주룰: 흑 금수 체크
        if current_color == 1:
            forbidden, reason = _is_forbidden_move(board, req.x, req.y)
            if forbidden:
                board[req.y][req.x] = 0  # 되돌리기
                raise HTTPException(400, f"금수입니다: {reason}")

        # 5목 체크
        five_count = _check_five(board, req.x, req.y, current_color)
        if current_color == 1 and five_count == 5:
            result["winner"] = uid
            result["reason"] = "five"
        elif current_color == 2 and five_count >= 5:
            # 백은 6목 이상도 승리
            result["winner"] = uid
            result["reason"] = "five"

        move_count = room["move_count"] + 1
        next_turn = "W" if room["current_turn"] == "B" else "B"

        # 무승부 (225수)
        if not result["winner"] and move_count >= OMOK_SIZE * OMOK_SIZE:
            result["reason"] = "draw"

        # 수순 기록
        await db.execute(
            "INSERT INTO omok_moves (room_id, user_id, x, y, color, move_number) VALUES (?,?,?,?,?,?)",
            (room_id, uid, req.x, req.y, room["current_turn"], move_count)
        )

        if result["winner"]:
            await db.execute(
                "UPDATE omok_rooms SET board=?, move_count=?, status='FINISHED', winner_id=?, win_reason=?, finished_at=datetime('now','localtime') WHERE id=?",
                (json.dumps(board), move_count, result["winner"], result["reason"], room_id)
            )
            # 포인트 지급
            if room["bet_amount"] > 0:
                total_pot = room["bet_amount"] * 2
                await log_point_change(db, result["winner"], total_pot, "omok", f"오목 승리 +{total_pot}P")
            # MMR 업데이트
            loser_id = room["opponent_id"] if result["winner"] == room["creator_id"] else room["creator_id"]
            await _update_mmr(db, result["winner"], loser_id, "omok", "win")
            # 티커
            winner_name = (await db.execute_fetchall("SELECT nickname FROM users WHERE id=?", (result["winner"],)))[0]["nickname"]
            await insert_ticker(db, f"⚫ {winner_name}님이 오목에서 승리! (+{room['bet_amount']*2}P)" if room["bet_amount"] > 0 else f"⚫ {winner_name}님이 오목에서 승리!", "omok")
            # 관전 배팅 정산
            await _settle_spectator_bets(db, "omok", room_id, result["winner"])
        elif result["reason"] == "draw":
            await db.execute(
                "UPDATE omok_rooms SET board=?, move_count=?, status='FINISHED', win_reason='draw', finished_at=datetime('now','localtime') WHERE id=?",
                (json.dumps(board), move_count, room_id)
            )
            # 무승부: 베팅금 환불
            if room["bet_amount"] > 0:
                await log_point_change(db, room["creator_id"], room["bet_amount"], "omok", "오목 무승부 환불")
                await log_point_change(db, room["opponent_id"], room["bet_amount"], "omok", "오목 무승부 환불")
            await _update_mmr(db, room["creator_id"], room["opponent_id"], "omok", "draw")
            # 관전 배팅 무승부 환불
            await _settle_spectator_bets(db, "omok", room_id, 0, is_draw=True)
        else:
            await db.execute(
                "UPDATE omok_rooms SET board=?, current_turn=?, move_count=? WHERE id=?",
                (json.dumps(board), next_turn, move_count, room_id)
            )

        await db.commit()
        return {"board": board, "move_count": move_count, "result": result}
    finally:
        await db.close()


@app.post("/api/omok/rooms/{room_id}/resign")
async def omok_resign(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM omok_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")
        uid = user["user_id"]
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")

        winner_id = room["opponent_id"] if uid == room["creator_id"] else room["creator_id"]
        await db.execute(
            "UPDATE omok_rooms SET status='FINISHED', winner_id=?, win_reason='resign', finished_at=datetime('now','localtime') WHERE id=?",
            (winner_id, room_id)
        )
        if room["bet_amount"] > 0:
            total_pot = room["bet_amount"] * 2
            await log_point_change(db, winner_id, total_pot, "omok", f"오목 승리(기권) +{total_pot}P")
        await _update_mmr(db, winner_id, uid, "omok", "win")
        winner_name = (await db.execute_fetchall("SELECT nickname FROM users WHERE id=?", (winner_id,)))[0]["nickname"]
        await insert_ticker(db, f"⚫ {winner_name}님이 오목에서 승리(상대 기권)!", "omok")
        await _settle_spectator_bets(db, "omok", room_id, winner_id)
        await db.commit()
        return {"winner_id": winner_id}
    finally:
        await db.close()


@app.post("/api/omok/rooms/{room_id}/undo_request")
async def omok_undo_request(room_id: int, user=Depends(get_current_user)):
    """한수 무르기 요청"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM omok_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")
        uid = user["user_id"]
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")
        if room["undo_request_by"] is not None:
            raise HTTPException(400, "이미 무르기 요청이 있습니다")
        if room["move_count"] == 0:
            raise HTTPException(400, "무를 수가 없습니다")
        # 방금 내가 둔 경우에만 요청 가능 (현재 상대 차례)
        my_color = room["creator_color"] if uid == room["creator_id"] else ("W" if room["creator_color"] == "B" else "B")
        if room["current_turn"] == my_color:
            raise HTTPException(400, "아직 무르기를 요청할 수 없습니다 (내 차례)")
        await db.execute("UPDATE omok_rooms SET undo_request_by=? WHERE id=?", (uid, room_id))
        await db.commit()
        return {"message": "무르기 요청이 전송되었습니다"}
    finally:
        await db.close()


@app.post("/api/omok/rooms/{room_id}/undo_response")
async def omok_undo_response(room_id: int, req: UndoResponseRequest, user=Depends(get_current_user)):
    """한수 무르기 수락/거절"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM omok_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")
        if room["undo_request_by"] is None:
            raise HTTPException(400, "무르기 요청이 없습니다")
        uid = user["user_id"]
        if room["undo_request_by"] == uid:
            raise HTTPException(400, "자신의 요청에 응답할 수 없습니다")
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")

        if req.accept:
            # 마지막 수를 삭제하고 보드 재구성
            last_moves = await db.execute_fetchall(
                "SELECT * FROM omok_moves WHERE room_id=? ORDER BY move_number DESC LIMIT 1",
                (room_id,)
            )
            if not last_moves:
                raise HTTPException(400, "무를 수가 없습니다")
            last_move = last_moves[0]
            await db.execute("DELETE FROM omok_moves WHERE id=?", (last_move["id"],))

            # 보드 재구성
            new_board = [[0]*OMOK_SIZE for _ in range(OMOK_SIZE)]
            remaining = await db.execute_fetchall(
                "SELECT * FROM omok_moves WHERE room_id=? ORDER BY move_number ASC",
                (room_id,)
            )
            for m in remaining:
                color = 1 if m["color"] == "B" else 2
                new_board[m["y"]][m["x"]] = color

            move_count = len(remaining)
            restored_turn = last_move["color"]  # 요청자가 뒀던 색이 다시 차례
            await db.execute(
                "UPDATE omok_rooms SET board=?, current_turn=?, move_count=?, undo_request_by=NULL WHERE id=?",
                (json.dumps(new_board), restored_turn, move_count, room_id)
            )
        else:
            await db.execute("UPDATE omok_rooms SET undo_request_by=NULL WHERE id=?", (room_id,))

        await db.commit()
        return {"accepted": req.accept}
    finally:
        await db.close()


@app.post("/api/omok/rooms/{room_id}/cancel")
async def cancel_omok_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM omok_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404)
        room = rows[0]
        if room["creator_id"] != user["user_id"]:
            raise HTTPException(400, "방장만 취소할 수 있습니다")
        if room["status"] != "WAITING":
            raise HTTPException(400, "대기 중인 방만 취소할 수 있습니다")
        await db.execute("UPDATE omok_rooms SET status='CANCELLED' WHERE id=?", (room_id,))
        if room["bet_amount"] > 0:
            await log_point_change(db, user["user_id"], room["bet_amount"], "omok", "오목 방 취소 환불")
        await db.commit()
        return {"message": "방이 취소되었습니다"}
    finally:
        await db.close()


@app.post("/api/omok/rooms/{room_id}/rematch")
async def omok_rematch(room_id: int, user=Depends(get_current_user)):
    """한판더하기: 흑백 스왑하고 새 게임"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM omok_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404)
        room = rows[0]
        if room["status"] != "FINISHED":
            raise HTTPException(400, "끝난 게임만 재경기 가능합니다")
        uid = user["user_id"]
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")

        # 베팅금 차감
        if room["bet_amount"] > 0:
            for pid in [room["creator_id"], room["opponent_id"]]:
                bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (pid,))
                if not bal or bal[0]["points"] < room["bet_amount"]:
                    raise HTTPException(400, "포인트가 부족한 참가자가 있습니다")
            for pid in [room["creator_id"], room["opponent_id"]]:
                await log_point_change(db, pid, -room["bet_amount"], "omok", f"오목 재경기 베팅 ({room['bet_amount']}P)")

        # 흑백 스왑
        new_creator_color = "W" if room["creator_color"] == "B" else "B"
        board = json.dumps(_empty_board())
        await db.execute(
            """UPDATE omok_rooms SET status='PLAYING', board=?, current_turn='B',
               creator_color=?, winner_id=NULL, win_reason=NULL, move_count=0,
               game_number=?, finished_at=NULL WHERE id=?""",
            (board, new_creator_color, room["game_number"] + 1, room_id)
        )
        # 수순 삭제
        await db.execute("DELETE FROM omok_moves WHERE room_id = ?", (room_id,))
        await db.commit()
        return {"message": "재경기 시작", "creator_color": new_creator_color}
    finally:
        await db.close()


@app.get("/api/omok/history")
async def omok_history(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT r.*, u1.nickname as creator_name, u2.nickname as opponent_name, uw.nickname as winner_name
               FROM omok_rooms r
               JOIN users u1 ON r.creator_id = u1.id
               LEFT JOIN users u2 ON r.opponent_id = u2.id
               LEFT JOIN users uw ON r.winner_id = uw.id
               WHERE (r.creator_id = ? OR r.opponent_id = ?) AND r.status = 'FINISHED'
               ORDER BY r.finished_at DESC LIMIT 30""",
            (user["user_id"], user["user_id"])
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# CHESS (체스)
# ═══════════════════════════════════════════════

INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@app.post("/api/chess/rooms")
async def create_chess_room(req: ChessRoomCreateRequest, user=Depends(get_current_user)):
    if req.bet_amount < 0:
        raise HTTPException(400, "베팅 금액이 올바르지 않습니다")
    db = await get_db()
    try:
        existing = await db.execute_fetchall(
            "SELECT id FROM chess_rooms WHERE (creator_id = ? OR opponent_id = ?) AND status IN ('WAITING','PLAYING')",
            (user["user_id"], user["user_id"])
        )
        if existing:
            raise HTTPException(400, "이미 참여 중인 체스 방이 있습니다")

        if req.bet_amount > 0:
            bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],))
            if not bal or bal[0]["points"] < req.bet_amount:
                raise HTTPException(400, "포인트가 부족합니다")
            await log_point_change(db, user["user_id"], -req.bet_amount, "chess", f"체스 베팅 ({req.bet_amount}P)")

        # 방장은 랜덤 컬러 (w/b)
        creator_color = random.choice(["w", "b"])
        cursor = await db.execute(
            """INSERT INTO chess_rooms (creator_id, bet_amount, fen, current_turn, creator_color)
               VALUES (?, ?, ?, 'w', ?)""",
            (user["user_id"], req.bet_amount, INITIAL_FEN, creator_color)
        )
        room_id = cursor.lastrowid
        await db.commit()
        return {"room_id": room_id, "creator_color": creator_color}
    finally:
        await db.close()


@app.get("/api/chess/rooms")
async def list_chess_rooms(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT r.*, u1.nickname as creator_name, u2.nickname as opponent_name
               FROM chess_rooms r
               JOIN users u1 ON r.creator_id = u1.id
               LEFT JOIN users u2 ON r.opponent_id = u2.id
               WHERE r.status IN ('WAITING','PLAYING')
               ORDER BY r.created_at DESC"""
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/chess/rooms/{room_id}")
async def get_chess_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT r.*, u1.nickname as creator_name, u2.nickname as opponent_name
               FROM chess_rooms r
               JOIN users u1 ON r.creator_id = u1.id
               LEFT JOIN users u2 ON r.opponent_id = u2.id
               WHERE r.id = ?""",
            (room_id,)
        )
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = dict(rows[0])
        # 승자 닉네임
        if room.get("winner_id"):
            w = await db.execute_fetchall("SELECT nickname FROM users WHERE id=?", (room["winner_id"],))
            room["winner_name"] = w[0]["nickname"] if w else None
        moves = await db.execute_fetchall(
            "SELECT * FROM chess_moves WHERE room_id = ? ORDER BY move_number", (room_id,)
        )
        room["moves"] = [dict(m) for m in moves]
        return room
    finally:
        await db.close()


@app.post("/api/chess/rooms/{room_id}/join")
async def join_chess_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM chess_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404)
        room = rows[0]
        if room["status"] != "WAITING":
            raise HTTPException(400, "참가할 수 없는 상태입니다")
        if room["creator_id"] == user["user_id"]:
            raise HTTPException(400, "자신의 방에 참가할 수 없습니다")

        existing = await db.execute_fetchall(
            "SELECT id FROM chess_rooms WHERE (creator_id = ? OR opponent_id = ?) AND status IN ('WAITING','PLAYING')",
            (user["user_id"], user["user_id"])
        )
        if existing:
            raise HTTPException(400, "이미 참여 중인 체스 방이 있습니다")

        if room["bet_amount"] > 0:
            bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],))
            if not bal or bal[0]["points"] < room["bet_amount"]:
                raise HTTPException(400, "포인트가 부족합니다")
            await log_point_change(db, user["user_id"], -room["bet_amount"], "chess", f"체스 베팅 ({room['bet_amount']}P)")

        await db.execute(
            "UPDATE chess_rooms SET opponent_id = ?, status = 'PLAYING' WHERE id = ?",
            (user["user_id"], room_id)
        )
        await db.commit()
        return {"message": "입장 완료"}
    finally:
        await db.close()


@app.post("/api/chess/rooms/{room_id}/move")
async def chess_move(room_id: int, req: ChessMoveRequest, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM chess_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404)
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")

        uid = user["user_id"]
        # 차례 확인
        if room["current_turn"] == room["creator_color"]:
            if uid != room["creator_id"]:
                raise HTTPException(400, "상대방의 차례입니다")
        else:
            if uid != room["opponent_id"]:
                raise HTTPException(400, "상대방의 차례입니다")

        move_count = room["move_count"] + 1
        next_turn = "b" if room["current_turn"] == "w" else "w"

        # 수순 기록
        await db.execute(
            "INSERT INTO chess_moves (room_id, user_id, move_from, move_to, piece, promotion, fen_after, move_number) VALUES (?,?,?,?,?,?,?,?)",
            (room_id, uid, req.move_from, req.move_to, "", req.promotion, req.fen_after, move_count)
        )

        result = {"winner": None, "reason": None}

        if req.is_checkmate:
            result["winner"] = uid
            result["reason"] = "checkmate"
        elif req.is_stalemate or req.is_draw:
            result["reason"] = "draw"

        if result["winner"]:
            await db.execute(
                "UPDATE chess_rooms SET fen=?, move_count=?, status='FINISHED', winner_id=?, win_reason=?, last_move=?, finished_at=datetime('now','localtime') WHERE id=?",
                (req.fen_after, move_count, result["winner"], result["reason"], f"{req.move_from}-{req.move_to}", room_id)
            )
            if room["bet_amount"] > 0:
                total_pot = room["bet_amount"] * 2
                await log_point_change(db, result["winner"], total_pot, "chess", f"체스 승리 +{total_pot}P")
            loser_id = room["opponent_id"] if result["winner"] == room["creator_id"] else room["creator_id"]
            await _update_mmr(db, result["winner"], loser_id, "chess", "win")
            winner_name = (await db.execute_fetchall("SELECT nickname FROM users WHERE id=?", (result["winner"],)))[0]["nickname"]
            await insert_ticker(db, f"♟️ {winner_name}님이 체스에서 승리! (+{room['bet_amount']*2}P)" if room["bet_amount"] > 0 else f"♟️ {winner_name}님이 체스에서 승리!", "chess")
            await _settle_spectator_bets(db, "chess", room_id, result["winner"])
        elif result["reason"] == "draw":
            await db.execute(
                "UPDATE chess_rooms SET fen=?, move_count=?, status='FINISHED', win_reason='draw', last_move=?, finished_at=datetime('now','localtime') WHERE id=?",
                (req.fen_after, move_count, f"{req.move_from}-{req.move_to}", room_id)
            )
            if room["bet_amount"] > 0:
                await log_point_change(db, room["creator_id"], room["bet_amount"], "chess", "체스 무승부 환불")
                await log_point_change(db, room["opponent_id"], room["bet_amount"], "chess", "체스 무승부 환불")
            await _update_mmr(db, room["creator_id"], room["opponent_id"], "chess", "draw")
            await _settle_spectator_bets(db, "chess", room_id, 0, is_draw=True)
        else:
            await db.execute(
                "UPDATE chess_rooms SET fen=?, current_turn=?, move_count=?, last_move=? WHERE id=?",
                (req.fen_after, next_turn, move_count, f"{req.move_from}-{req.move_to}", room_id)
            )

        await db.commit()
        return {"fen": req.fen_after, "move_count": move_count, "result": result}
    finally:
        await db.close()


@app.post("/api/chess/rooms/{room_id}/resign")
async def chess_resign(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM chess_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404)
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")
        uid = user["user_id"]
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")

        winner_id = room["opponent_id"] if uid == room["creator_id"] else room["creator_id"]
        await db.execute(
            "UPDATE chess_rooms SET status='FINISHED', winner_id=?, win_reason='resign', finished_at=datetime('now','localtime') WHERE id=?",
            (winner_id, room_id)
        )
        if room["bet_amount"] > 0:
            total_pot = room["bet_amount"] * 2
            await log_point_change(db, winner_id, total_pot, "chess", f"체스 승리(기권) +{total_pot}P")
        await _update_mmr(db, winner_id, uid, "chess", "win")
        winner_name = (await db.execute_fetchall("SELECT nickname FROM users WHERE id=?", (winner_id,)))[0]["nickname"]
        await insert_ticker(db, f"♟️ {winner_name}님이 체스에서 승리(상대 기권)!", "chess")
        await _settle_spectator_bets(db, "chess", room_id, winner_id)
        await db.commit()
        return {"winner_id": winner_id}
    finally:
        await db.close()


@app.post("/api/chess/rooms/{room_id}/undo_request")
async def chess_undo_request(room_id: int, user=Depends(get_current_user)):
    """한수 무르기 요청"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM chess_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")
        uid = user["user_id"]
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")
        if room["undo_request_by"] is not None:
            raise HTTPException(400, "이미 무르기 요청이 있습니다")
        if room["move_count"] == 0:
            raise HTTPException(400, "무를 수가 없습니다")
        my_color = room["creator_color"] if uid == room["creator_id"] else ("b" if room["creator_color"] == "w" else "w")
        if room["current_turn"] == my_color:
            raise HTTPException(400, "아직 무르기를 요청할 수 없습니다 (내 차례)")
        await db.execute("UPDATE chess_rooms SET undo_request_by=? WHERE id=?", (uid, room_id))
        await db.commit()
        return {"message": "무르기 요청이 전송되었습니다"}
    finally:
        await db.close()


@app.post("/api/chess/rooms/{room_id}/undo_response")
async def chess_undo_response(room_id: int, req: UndoResponseRequest, user=Depends(get_current_user)):
    """한수 무르기 수락/거절"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM chess_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "게임이 진행 중이 아닙니다")
        if room["undo_request_by"] is None:
            raise HTTPException(400, "무르기 요청이 없습니다")
        uid = user["user_id"]
        if room["undo_request_by"] == uid:
            raise HTTPException(400, "자신의 요청에 응답할 수 없습니다")
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")

        if req.accept:
            # 마지막 수 삭제 후 이전 FEN으로 복원
            last_moves = await db.execute_fetchall(
                "SELECT * FROM chess_moves WHERE room_id=? ORDER BY move_number DESC LIMIT 1",
                (room_id,)
            )
            if not last_moves:
                raise HTTPException(400, "무를 수가 없습니다")
            last_move = last_moves[0]
            await db.execute("DELETE FROM chess_moves WHERE id=?", (last_move["id"],))

            # 이전 FEN 복원
            prev_moves = await db.execute_fetchall(
                "SELECT * FROM chess_moves WHERE room_id=? ORDER BY move_number DESC LIMIT 1",
                (room_id,)
            )
            if prev_moves:
                prev_fen = prev_moves[0]["fen_after"]
                prev_last_move = f"{prev_moves[0]['move_from']}-{prev_moves[0]['move_to']}"
            else:
                prev_fen = INITIAL_FEN
                prev_last_move = None

            move_count = last_move["move_number"] - 1
            # 무른 수를 둔 플레이어 색깔 다시 차례
            # last_move의 user_id가 요청자(undo_request_by)
            requester_color = room["creator_color"] if room["undo_request_by"] == room["creator_id"] else ("b" if room["creator_color"] == "w" else "w")
            # FEN에서 turn 추출 대신 직접 계산
            restored_turn = requester_color

            await db.execute(
                "UPDATE chess_rooms SET fen=?, current_turn=?, move_count=?, last_move=?, undo_request_by=NULL WHERE id=?",
                (prev_fen, restored_turn, move_count, prev_last_move, room_id)
            )
        else:
            await db.execute("UPDATE chess_rooms SET undo_request_by=NULL WHERE id=?", (room_id,))

        await db.commit()
        return {"accepted": req.accept}
    finally:
        await db.close()


@app.post("/api/chess/rooms/{room_id}/cancel")
async def cancel_chess_room(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM chess_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404)
        room = rows[0]
        if room["creator_id"] != user["user_id"]:
            raise HTTPException(400, "방장만 취소할 수 있습니다")
        if room["status"] != "WAITING":
            raise HTTPException(400, "대기 중인 방만 취소할 수 있습니다")
        await db.execute("UPDATE chess_rooms SET status='CANCELLED' WHERE id=?", (room_id,))
        if room["bet_amount"] > 0:
            await log_point_change(db, user["user_id"], room["bet_amount"], "chess", "체스 방 취소 환불")
        await db.commit()
        return {"message": "방이 취소되었습니다"}
    finally:
        await db.close()


@app.post("/api/chess/rooms/{room_id}/rematch")
async def chess_rematch(room_id: int, user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM chess_rooms WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404)
        room = rows[0]
        if room["status"] != "FINISHED":
            raise HTTPException(400, "끝난 게임만 재경기 가능합니다")
        uid = user["user_id"]
        if uid != room["creator_id"] and uid != room["opponent_id"]:
            raise HTTPException(400, "참가자가 아닙니다")

        if room["bet_amount"] > 0:
            for pid in [room["creator_id"], room["opponent_id"]]:
                bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (pid,))
                if not bal or bal[0]["points"] < room["bet_amount"]:
                    raise HTTPException(400, "포인트가 부족한 참가자가 있습니다")
            for pid in [room["creator_id"], room["opponent_id"]]:
                await log_point_change(db, pid, -room["bet_amount"], "chess", f"체스 재경기 베팅 ({room['bet_amount']}P)")

        new_creator_color = "b" if room["creator_color"] == "w" else "w"
        await db.execute(
            """UPDATE chess_rooms SET status='PLAYING', fen=?, current_turn='w',
               creator_color=?, winner_id=NULL, win_reason=NULL, move_count=0,
               last_move=NULL, game_number=?, finished_at=NULL WHERE id=?""",
            (INITIAL_FEN, new_creator_color, room["game_number"] + 1, room_id)
        )
        await db.execute("DELETE FROM chess_moves WHERE room_id = ?", (room_id,))
        await db.commit()
        return {"message": "재경기 시작", "creator_color": new_creator_color}
    finally:
        await db.close()


@app.get("/api/chess/history")
async def chess_history(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT r.*, u1.nickname as creator_name, u2.nickname as opponent_name, uw.nickname as winner_name
               FROM chess_rooms r
               JOIN users u1 ON r.creator_id = u1.id
               LEFT JOIN users u2 ON r.opponent_id = u2.id
               LEFT JOIN users uw ON r.winner_id = uw.id
               WHERE (r.creator_id = ? OR r.opponent_id = ?) AND r.status = 'FINISHED'
               ORDER BY r.finished_at DESC LIMIT 30""",
            (user["user_id"], user["user_id"])
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# MMR & GAME LEADERBOARD
# ═══════════════════════════════════════════════

async def _update_mmr(db, winner_id, loser_id, game_type, result):
    """MMR 업데이트. result = 'win' | 'draw'"""
    # 현재 MMR 조회/생성
    for uid in [winner_id, loser_id]:
        await db.execute(
            "INSERT OR IGNORE INTO game_mmr (user_id, game_type) VALUES (?, ?)",
            (uid, game_type)
        )
    w_rows = await db.execute_fetchall("SELECT * FROM game_mmr WHERE user_id=? AND game_type=?", (winner_id, game_type))
    l_rows = await db.execute_fetchall("SELECT * FROM game_mmr WHERE user_id=? AND game_type=?", (loser_id, game_type))
    w_mmr = w_rows[0]["mmr"]
    l_mmr = l_rows[0]["mmr"]

    if result == "win":
        w_change, l_change = _calc_mmr_change(w_mmr, l_mmr)
        await db.execute("UPDATE game_mmr SET mmr=mmr+?, wins=wins+1 WHERE user_id=? AND game_type=?", (w_change, winner_id, game_type))
        await db.execute("UPDATE game_mmr SET mmr=MAX(0,mmr+?), losses=losses+1 WHERE user_id=? AND game_type=?", (l_change, loser_id, game_type))
    elif result == "draw":
        # 무승부: 약간의 MMR 이동 (낮은 쪽이 조금 오름)
        expected_w = 1 / (1 + 10**((l_mmr - w_mmr) / 400))
        w_change = round(16 * (0.5 - expected_w))
        await db.execute("UPDATE game_mmr SET mmr=MAX(0,mmr+?), draws=draws+1 WHERE user_id=? AND game_type=?", (w_change, winner_id, game_type))
        await db.execute("UPDATE game_mmr SET mmr=MAX(0,mmr+?), draws=draws+1 WHERE user_id=? AND game_type=?", (-w_change, loser_id, game_type))


@app.get("/api/mmr/leaderboard")
async def mmr_leaderboard(game_type: str = "omok", user=Depends(get_current_user)):
    if game_type not in ("omok", "chess"):
        raise HTTPException(400, "유효하지 않은 게임 타입")
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT m.*, u.nickname
               FROM game_mmr m JOIN users u ON m.user_id = u.id
               WHERE m.game_type = ?
               ORDER BY m.mmr DESC LIMIT 50""",
            (game_type,)
        )
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/mmr/me")
async def my_mmr(user=Depends(get_current_user)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM game_mmr WHERE user_id = ?", (user["user_id"],)
        )
        result = {}
        for r in rows:
            result[r["game_type"]] = dict(r)
        return result
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# SPECTATOR BETTING (관전 배팅)
# ═══════════════════════════════════════════════

async def _settle_spectator_bets(db, game_type: str, room_id: int, winner_id: int, is_draw: bool = False):
    """게임 종료 시 관전 배팅 정산"""
    bets = await db.execute_fetchall(
        "SELECT * FROM spectator_bets WHERE game_type = ? AND room_id = ? AND status = 'PENDING'",
        (game_type, room_id)
    )
    if not bets:
        return

    if is_draw:
        # 무승부: 전액 환불
        for b in bets:
            await log_point_change(db, b["user_id"], b["amount"], "관전배팅", f"관전배팅 무승부 환불 +{b['amount']}P")
            await db.execute("UPDATE spectator_bets SET status='REFUNDED', payout=? WHERE id=?", (b["amount"], b["id"]))
        return

    # 승자/패자 풀 계산
    total_pool = sum(b["amount"] for b in bets)
    winner_pool = sum(b["amount"] for b in bets if b["predicted_winner_id"] == winner_id)

    if winner_pool == 0:
        # 아무도 맞추지 못함: 전액 환불
        for b in bets:
            await log_point_change(db, b["user_id"], b["amount"], "관전배팅", f"관전배팅 환불 (승자 예측자 없음)")
            await db.execute("UPDATE spectator_bets SET status='REFUNDED', payout=? WHERE id=?", (b["amount"], b["id"]))
        return

    # 비례 배분 정산
    for b in bets:
        if b["predicted_winner_id"] == winner_id:
            payout = int(total_pool * (b["amount"] / winner_pool))
            profit = payout - b["amount"]
            await log_point_change(db, b["user_id"], profit, "관전배팅", f"관전배팅 적중! +{profit}P (배당 {payout/b['amount']:.2f}x)")
            await db.execute("UPDATE spectator_bets SET status='WON', payout=? WHERE id=?", (payout, b["id"]))
        else:
            await db.execute("UPDATE spectator_bets SET status='LOST', payout=0 WHERE id=?", (b["id"],))


@app.post("/api/spectator-bet/{game_type}/{room_id}")
async def place_spectator_bet(game_type: str, room_id: int, req: SpectatorBetRequest, user=Depends(get_current_user)):
    """관전 배팅 (오목/체스 진행 중인 게임에 승자 예측 배팅)"""
    if game_type not in ("omok", "chess"):
        raise HTTPException(400, "omok 또는 chess만 가능합니다")
    if req.amount <= 0:
        raise HTTPException(400, "배팅 포인트는 1 이상이어야 합니다")

    db = await get_db()
    try:
        # 게임 상태 확인
        table = "omok_rooms" if game_type == "omok" else "chess_rooms"
        rows = await db.execute_fetchall(f"SELECT * FROM {table} WHERE id = ?", (room_id,))
        if not rows:
            raise HTTPException(404, "방을 찾을 수 없습니다")
        room = rows[0]
        if room["status"] != "PLAYING":
            raise HTTPException(400, "진행 중인 게임에만 배팅할 수 있습니다")

        # 참가자는 배팅 불가
        uid = user["user_id"]
        if uid == room["creator_id"] or uid == room["opponent_id"]:
            raise HTTPException(400, "게임 참가자는 관전 배팅할 수 없습니다")

        # 예측 대상이 게임 참가자인지 확인
        if req.predicted_winner_id not in (room["creator_id"], room["opponent_id"]):
            raise HTTPException(400, "유효하지 않은 예측 대상입니다")

        # 중복 배팅 확인
        existing = await db.execute_fetchall(
            "SELECT id FROM spectator_bets WHERE game_type=? AND room_id=? AND user_id=?",
            (game_type, room_id, uid)
        )
        if existing:
            raise HTTPException(400, "이미 이 게임에 배팅했습니다")

        # 포인트 확인 & 차감
        bal = await db.execute_fetchall("SELECT points FROM point_balances WHERE user_id = ?", (uid,))
        if not bal or bal[0]["points"] < req.amount:
            raise HTTPException(400, "포인트가 부족합니다")

        await log_point_change(db, uid, -req.amount, "관전배팅", f"관전배팅 ({game_type} #{room_id})")
        await db.execute(
            "INSERT INTO spectator_bets (game_type, room_id, user_id, predicted_winner_id, amount) VALUES (?,?,?,?,?)",
            (game_type, room_id, uid, req.predicted_winner_id, req.amount)
        )
        await db.commit()

        # 현재 배팅 현황 반환
        bets = await db.execute_fetchall(
            """SELECT sb.*, u.nickname FROM spectator_bets sb
               JOIN users u ON sb.user_id = u.id
               WHERE sb.game_type=? AND sb.room_id=? AND sb.status='PENDING'""",
            (game_type, room_id)
        )
        return {"message": f"{req.amount}P 관전 배팅 완료!", "bets": [dict(b) for b in bets]}
    finally:
        await db.close()


@app.get("/api/spectator-bet/{game_type}/{room_id}")
async def get_spectator_bets(game_type: str, room_id: int, user=Depends(get_current_user)):
    """관전 배팅 현황 조회"""
    db = await get_db()
    try:
        bets = await db.execute_fetchall(
            """SELECT sb.*, u.nickname,
                      pw.nickname as predicted_winner_name
               FROM spectator_bets sb
               JOIN users u ON sb.user_id = u.id
               JOIN users pw ON sb.predicted_winner_id = pw.id
               WHERE sb.game_type=? AND sb.room_id=?
               ORDER BY sb.created_at""",
            (game_type, room_id)
        )
        total_pool = sum(b["amount"] for b in bets if b["status"] == "PENDING")
        my_bet = None
        for b in bets:
            if b["user_id"] == user["user_id"]:
                my_bet = dict(b)
        return {
            "bets": [dict(b) for b in bets],
            "total_pool": total_pool,
            "my_bet": my_bet,
        }
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# WEEKLY REWARDS (주간 보상)
# ═══════════════════════════════════════════════

WEEKLY_REWARDS = {1: 3000, 2: 2000, 3: 1000}  # 1등 3000P, 2등 2000P, 3등 1000P


def _get_week_range(reference_date=None):
    """이번 주 월요일~일요일 범위 반환"""
    if reference_date is None:
        reference_date = dt.now()
    monday = reference_date - timedelta(days=reference_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def _get_last_week_range():
    """지난 주 월요일~일요일 범위 반환"""
    today = dt.now()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")


@app.get("/api/weekly/omok-leaderboard")
async def weekly_omok_leaderboard(user=Depends(get_current_user)):
    """이번 주 오목 MMR 상위 리더보드"""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT m.*, u.nickname
               FROM game_mmr m JOIN users u ON m.user_id = u.id
               WHERE m.game_type = 'omok'
               ORDER BY m.mmr DESC LIMIT 50"""
        )
        week_start, week_end = _get_week_range()
        # 이번 주 보상 지급 여부 확인
        already_rewarded = await db.execute_fetchall(
            "SELECT id FROM weekly_rewards WHERE reward_type='omok' AND week_start=?", (week_start,)
        )
        return {
            "leaderboard": [dict(r) for r in rows],
            "week_start": week_start,
            "week_end": week_end,
            "rewarded": len(already_rewarded) > 0,
        }
    finally:
        await db.close()


@app.get("/api/weekly/nordle-leaderboard")
async def weekly_nordle_leaderboard(user=Depends(get_current_user)):
    """이번 주 노들 주간 리더보드 (풀이 수 기준)"""
    db = await get_db()
    try:
        week_start, week_end = _get_week_range()
        rows = await db.execute_fetchall(
            """SELECT g.user_id, u.nickname,
                      COUNT(*) as solved_count,
                      ROUND(AVG(json_array_length(g.guesses)), 1) as avg_attempts,
                      MIN(json_array_length(g.guesses)) as best_attempts
               FROM nordle_games g
               JOIN users u ON g.user_id = u.id
               WHERE g.solved = 1 AND g.date BETWEEN ? AND ?
               GROUP BY g.user_id
               ORDER BY solved_count DESC, avg_attempts ASC
               LIMIT 50""",
            (week_start, week_end)
        )
        already_rewarded = await db.execute_fetchall(
            "SELECT id FROM weekly_rewards WHERE reward_type='nordle' AND week_start=?", (week_start,)
        )
        return {
            "leaderboard": [dict(r) for r in rows],
            "week_start": week_start,
            "week_end": week_end,
            "rewarded": len(already_rewarded) > 0,
        }
    finally:
        await db.close()


@app.post("/api/admin/weekly-rewards")
async def admin_give_weekly_rewards(reward_type: str = "all", user=Depends(get_admin_user)):
    """주간 보상 지급 (omok, nordle, 또는 all)"""
    db = await get_db()
    try:
        week_start, week_end = _get_week_range()
        results = []

        if reward_type in ("omok", "all"):
            # 이미 지급 체크
            already = await db.execute_fetchall(
                "SELECT id FROM weekly_rewards WHERE reward_type='omok' AND week_start=?", (week_start,)
            )
            if already:
                results.append("오목: 이미 이번 주 보상 지급 완료")
            else:
                rows = await db.execute_fetchall(
                    """SELECT m.user_id, u.nickname, m.mmr
                       FROM game_mmr m JOIN users u ON m.user_id = u.id
                       WHERE m.game_type = 'omok' AND (m.wins + m.losses) > 0
                       ORDER BY m.mmr DESC LIMIT 3"""
                )
                for i, r in enumerate(rows):
                    rank = i + 1
                    amount = WEEKLY_REWARDS.get(rank, 0)
                    if amount > 0:
                        await log_point_change(db, r["user_id"], amount, "주간보상", f"오목 주간 {rank}등 보상 (+{amount}P)")
                        await db.execute(
                            "INSERT INTO weekly_rewards (reward_type, week_start, week_end, user_id, rank, amount) VALUES (?,?,?,?,?,?)",
                            ("omok", week_start, week_end, r["user_id"], rank, amount)
                        )
                        results.append(f"오목 {rank}등 {r['nickname']} +{amount}P (MMR {r['mmr']})")
                if not rows:
                    results.append("오목: 이번 주 대국 기록 없음")

        if reward_type in ("nordle", "all"):
            already = await db.execute_fetchall(
                "SELECT id FROM weekly_rewards WHERE reward_type='nordle' AND week_start=?", (week_start,)
            )
            if already:
                results.append("노들: 이미 이번 주 보상 지급 완료")
            else:
                rows = await db.execute_fetchall(
                    """SELECT g.user_id, u.nickname,
                              COUNT(*) as solved_count,
                              ROUND(AVG(json_array_length(g.guesses)), 1) as avg_attempts
                       FROM nordle_games g
                       JOIN users u ON g.user_id = u.id
                       WHERE g.solved = 1 AND g.date BETWEEN ? AND ?
                       GROUP BY g.user_id
                       ORDER BY solved_count DESC, avg_attempts ASC
                       LIMIT 3""",
                    (week_start, week_end)
                )
                for i, r in enumerate(rows):
                    rank = i + 1
                    amount = WEEKLY_REWARDS.get(rank, 0)
                    if amount > 0:
                        await log_point_change(db, r["user_id"], amount, "주간보상", f"노들 주간 {rank}등 보상 (+{amount}P)")
                        await db.execute(
                            "INSERT INTO weekly_rewards (reward_type, week_start, week_end, user_id, rank, amount) VALUES (?,?,?,?,?,?)",
                            ("nordle", week_start, week_end, r["user_id"], rank, amount)
                        )
                        results.append(f"노들 {rank}등 {r['nickname']} +{amount}P ({r['solved_count']}문제)")
                if not rows:
                    results.append("노들: 이번 주 풀이 기록 없음")

        await db.commit()
        # 전광판 알림
        if any("등" in r for r in results):
            await insert_ticker(db, f"🏆 주간 보상 지급! {' | '.join(r for r in results if '등' in r)}", "weekly_reward")
            await db.commit()
        return {"message": " | ".join(results)}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# STATIC FILES (프론트엔드 빌드 서빙)
# ═══════════════════════════════════════════════

DIST_DIR = os.path.join(os.path.dirname(__file__), "..", "client", "dist")

if os.path.isdir(DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(DIST_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(DIST_DIR, "index.html"))
