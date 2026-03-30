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
import json
import os
import re
import random
from datetime import datetime as dt, timedelta

from database import get_db, init_db, current_month, INITIAL_SEED, FEE_RATE, TAX_RATE
from auth import hash_password, verify_password, create_token, decode_token
from models import *


# ── App Setup ─────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield

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

        rankings.append({
            "user_id": uid,
            "nickname": u["nickname"],
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

            rankings.append({
                "user_id": u["id"],
                "nickname": u["nickname"],
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


@app.post("/api/points/daily-free")
async def daily_free_charge(user=Depends(get_current_user)):
    """일일 무료 200P 충전 (하루 1회)"""
    db = await get_db()
    try:
        today = dt.now().strftime("%Y-%m-%d")
        rows = await db.execute_fetchall(
            "SELECT count FROM daily_activity WHERE user_id = ? AND date = ? AND activity_type = 'free_charge'",
            (user["user_id"], today)
        )
        if rows and rows[0]["count"] > 0:
            raise HTTPException(400, "오늘 이미 무료 충전을 받았습니다")

        await db.execute(
            "INSERT INTO daily_activity (user_id, date, activity_type, count) VALUES (?, ?, 'free_charge', 1) "
            "ON CONFLICT(user_id, date, activity_type) DO UPDATE SET count = count + 1",
            (user["user_id"], today)
        )
        new_balance = await log_point_change(db, user["user_id"], 200, "무료 충전", "일일 무료 200P 충전")
        await db.commit()
        return {"message": "무료 200P 충전 완료!", "points": new_balance}
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
            rankings.append({
                "rank": i + 1,
                "user_id": r["user_id"],
                "nickname": r["nickname"],
                "points": r["points"],
            })
        return {"rankings": rankings}
    finally:
        await db.close()


# ═══════════════════════════════════════════════
# RPS (가위바위보)
# ═══════════════════════════════════════════════

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

        computer = random.choice(["rock", "paper", "scissors"])
        if req.choice == computer:
            result = "draw"
            payout = 0
        elif (req.choice == "rock" and computer == "scissors") or \
             (req.choice == "paper" and computer == "rock") or \
             (req.choice == "scissors" and computer == "paper"):
            result = "win"
            payout = req.wager
        else:
            result = "lose"
            payout = -req.wager

        if payout != 0:
            desc = f"가위바위보 {result} (배팅 {req.wager}P)"
            await log_point_change(db, user["user_id"], payout, "가위바위보", desc)

        await db.execute(
            """INSERT INTO rps_games (user_id, player_choice, computer_choice, result, wager, payout)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user["user_id"], req.choice, computer, result, req.wager, payout)
        )
        await db.commit()

        new_bal = await db.execute_fetchall(
            "SELECT points FROM point_balances WHERE user_id = ?", (user["user_id"],)
        )
        return {
            "player_choice": req.choice,
            "computer_choice": computer,
            "result": result,
            "payout": payout,
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

        # 방 생성
        cursor = await db.execute(
            """INSERT INTO dice_rooms (creator_id, mode, dice_min, dice_max, entry_fee, total_pot)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user["user_id"], req.mode, req.dice_min, req.dice_max, req.entry_fee, req.entry_fee)
        )
        room_id = cursor.lastrowid

        # 방장 자동 입장 + 참가비 차감
        await db.execute(
            "INSERT INTO dice_players (room_id, user_id, is_ready) VALUES (?, ?, 1)",
            (room_id, user["user_id"])
        )
        await log_point_change(db, user["user_id"], -req.entry_fee, "주사위 참가", f"방 #{room_id} 생성")
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

        # 입장
        await db.execute(
            "INSERT INTO dice_players (room_id, user_id) VALUES (?, ?)",
            (room_id, user["user_id"])
        )
        await log_point_change(db, user["user_id"], -room["entry_fee"], "주사위 참가", f"방 #{room_id} 입장")
        await db.execute(
            "UPDATE dice_rooms SET total_pot = total_pot + ? WHERE id = ?",
            (room["entry_fee"], room_id)
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

        # 참가비 환불 및 퇴장
        await db.execute(
            "DELETE FROM dice_players WHERE room_id = ? AND user_id = ?",
            (room_id, user["user_id"])
        )
        await log_point_change(db, user["user_id"], room["entry_fee"], "주사위 환불", f"방 #{room_id} 퇴장")
        await db.execute(
            "UPDATE dice_rooms SET total_pot = total_pot - ? WHERE id = ?",
            (room["entry_fee"], room_id)
        )
        await db.commit()
        return {"message": "방에서 나갔습니다. 참가비가 환불됩니다."}
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

        # 전원 준비 체크 (첫 라운드만)
        if room["current_round"] == 0:
            not_ready = [p for p in alive_players if not p["is_ready"]]
            if not_ready:
                raise HTTPException(400, "모든 참가자가 준비해야 합니다")

        new_round = room["current_round"] + 1
        await db.execute(
            "UPDATE dice_rooms SET status = 'ROLLING', current_round = ? WHERE id = ?",
            (new_round, room_id)
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
            """SELECT dp.user_id, COALESCE(pb.points, 0) as points
               FROM dice_players dp
               LEFT JOIN point_balances pb ON dp.user_id = pb.user_id
               WHERE dp.room_id = ?""",
            (room_id,)
        )

        participating = []
        excluded = []
        for p in all_players:
            if p["points"] >= room["entry_fee"]:
                participating.append(p["user_id"])
            else:
                excluded.append(p["user_id"])

        if len(participating) < 2:
            raise HTTPException(400, f"포인트가 충분한 참가자가 {len(participating)}명뿐입니다 (최소 2명)")

        # 참가비 차감 + 플레이어 리셋
        for uid in participating:
            await db.execute(
                "UPDATE dice_players SET is_alive = 1, eliminated_round = NULL WHERE room_id = ? AND user_id = ?",
                (room_id, uid)
            )
            await log_point_change(db, uid, -room["entry_fee"], "주사위 참가", f"방 #{room_id} 한판더")
        for uid in excluded:
            await db.execute(
                "UPDATE dice_players SET is_alive = 0 WHERE room_id = ? AND user_id = ?",
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
                        "UPDATE dice_players SET is_alive = 1, eliminated_round = NULL WHERE room_id = ? AND user_id = ?",
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
                    """UPDATE dice_rooms SET status = 'WAITING', winner_id = ?,
                       finished_at = datetime('now','localtime') WHERE id = ?""",
                    (winner_id, room_id)
                )
                await log_point_change(db, winner_id, room["total_pot"], "주사위 우승", f"방 #{room_id} 우승 ({room['total_pot']}P)")
                await _update_dice_stats(db, room_id, winner_id, room["total_pot"])
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

        # 아직 결판 안 난 상태에서만 환불 (pot > 0이면 아직 판돈이 남아있음)
        if room["total_pot"] > 0:
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
