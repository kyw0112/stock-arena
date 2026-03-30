# Stock Arena - 사내 모의투자 리그

## 프로젝트 구조
```
stock-arena/
├── server/
│   ├── main.py           # FastAPI 메인 (모든 API)
│   ├── database.py       # SQLite + 스키마
│   ├── auth.py           # JWT 인증
│   ├── models.py         # Pydantic 모델
│   └── requirements.txt
├── client/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx       # 전체 UI (대시보드/매매/랭킹/게시판/베팅/관리)
│       ├── api.js        # API 클라이언트
│       └── style.css
└── README.md
```

## 폐쇄망 세팅 가이드

### 1. Python 패키지 가져오기

외부 PC에서:
```bash
pip download -d ./packages fastapi uvicorn[standard] aiosqlite python-jose[cryptography] passlib[bcrypt]
```
→ `packages/` 폴더를 USB로 내부망에 복사

내부망에서:
```bash
pip install --no-index --find-links=./packages fastapi uvicorn aiosqlite python-jose passlib
```

※ python-jose, passlib 없어도 동작함 (sha256 + 수동JWT 폴백 구현됨)
→ 최소 필수: fastapi, uvicorn, aiosqlite

### 2. Node 패키지 가져오기

외부 PC에서:
```bash
cd client
npm install
# node_modules 폴더째로 USB 복사
```

### 3. 서버 실행

```bash
cd server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 프론트 개발 모드

```bash
cd client
npm run dev
# → http://localhost:3000 (API는 :8000으로 프록시)
```

### 5. 프론트 빌드 (배포용)

```bash
cd client
npm run build
# → client/dist/ 생성됨
# FastAPI가 자동으로 dist 폴더 서빙
# http://서버IP:8000 으로 접속
```

## 초기 설정

### 1. 관리자 로그인
- 사번: `admin` / 비밀번호: `admin`
- **반드시 로그인 후 비밀번호 변경하세요**

### 2. IP 화이트리스트 등록
- 관리 탭 → IP 화이트리스트 → 동기들 IP 추가
- IP 미등록 시 화이트리스트 미적용 (전체 허용)

### 3. 종목 DB 로드
KRX에서 전종목 CSV 다운 후 JSON 변환해서 관리 페이지에 입력:
```json
[
  {"code": "005930", "name": "삼성전자", "market": "KOSPI"},
  {"code": "000660", "name": "SK하이닉스", "market": "KOSPI"},
  ...
]
```

Claude에게 "KRX 전종목 리스트를 위 JSON 형식으로 만들어줘"라고 하면 됩니다.

### 4. 유저 가입 승인
- 동기들이 가입 → 관리 탭에서 승인 버튼 클릭

## 매일 운영

1. 관리 탭 접속
2. "업데이트 필요 종목" 확인
3. Claude에게: "이 종목들 오늘 종가 알려줘: 삼성전자, SK하이닉스, ..."
4. Claude가 알려준 JSON 붙여넣기
5. "종가 입력 & 체결" 클릭 → 끝!

## 수수료/세금
- 매수 수수료: 0.015%
- 매도 수수료: 0.015%
- 매도 세금: 0.2% (증권거래세 0.18% + 농특세 0.02%)

## 월간 리셋
- 매월 1일 관리 탭 → "월간 리셋 실행"
- 전원 시드 1억 초기화, 대기 주문 취소
- 이전 월 기록은 통산 기록으로 보존
