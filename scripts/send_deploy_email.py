#!/usr/bin/env python3
"""
stock-arena 배포 ZIP을 Gmail로 전송하는 스크립트.

사용법:
    python3 scripts/send_deploy_email.py <zip_파일_경로>

환경 변수 (또는 ~/.claude/stock-arena-gmail.env):
    GMAIL_USER      : 보내는 Gmail 주소 (예: yourname@gmail.com)
    GMAIL_APP_PW    : Gmail 앱 비밀번호 (16자리, 공백 없이)
"""

import os
import sys
import smtplib
import pathlib
from email.message import EmailMessage
from email.utils import formatdate

RECIPIENT = "kyw0112@daou.co.kr"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
ENV_FILE = pathlib.Path.home() / ".claude" / "stock-arena-gmail.env"


def load_env_file():
    """~/.claude/stock-arena-gmail.env 에서 환경 변수 로드."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def send(zip_path: str):
    load_env_file()

    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    app_pw = os.environ.get("GMAIL_APP_PW", "").strip()

    if not gmail_user or not app_pw:
        print(
            "오류: GMAIL_USER와 GMAIL_APP_PW가 설정되어 있지 않습니다.\n"
            f"  {ENV_FILE} 파일을 만들고 아래 내용을 채워주세요:\n\n"
            "  GMAIL_USER=yourname@gmail.com\n"
            "  GMAIL_APP_PW=xxxxxxxxxxxx\n\n"
            "  Gmail 앱 비밀번호는 Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호 에서 발급."
        )
        sys.exit(1)

    zip_path = pathlib.Path(zip_path)
    if not zip_path.exists():
        print(f"오류: ZIP 파일이 없습니다: {zip_path}")
        sys.exit(1)

    subject = f"[Stock Arena] 내부 배포 패키지 - {zip_path.stem}"
    body = (
        f"Stock Arena 내부 배포 패키지를 첨부합니다.\n\n"
        f"파일명: {zip_path.name}\n"
        f"크기: {zip_path.stat().st_size / 1024:.1f} KB\n\n"
        "배포 방법:\n"
        "  1. ZIP 압축 해제\n"
        "  2. server/ 폴더: pip install -r requirements.txt 후 uvicorn main:app --host 0.0.0.0 --port 8000\n"
        "  3. client/dist/ 폴더는 FastAPI가 자동으로 정적 파일 서빙\n"
        "  4. 기존 stock_arena.db는 그대로 유지 (갈아끼지 않음)\n"
    )

    msg = EmailMessage()
    msg["From"] = gmail_user
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)

    with open(zip_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="zip",
            filename=zip_path.name,
        )

    print(f"Gmail SMTP 연결 중... ({SMTP_HOST}:{SMTP_PORT})")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(gmail_user, app_pw)
        smtp.send_message(msg)

    print(f"전송 완료: {RECIPIENT}")
    print(f"제목: {subject}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"사용법: python3 {sys.argv[0]} <zip_파일_경로>")
        sys.exit(1)
    send(sys.argv[1])
