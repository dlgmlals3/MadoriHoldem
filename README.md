# 마도리 홀덤 (MadoriHoldem)

Python FastAPI + WebSocket 기반 텍사스 홀덤 포커 서버. 단일 HTML 파일 웹 클라이언트와 AI 봇을 포함합니다.

---

## 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 서버 실행

**Windows:**
```
run_server.bat
```
**또는 직접:**
```bash
cd server
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 클라이언트 열기

**Windows:**
```
run_client.bat
```
브라우저에서 `http://localhost:8080` 접속.

> **직접 열기:** `client/index.html` 을 브라우저로 열어도 됩니다.
> 단, 파일 URL(`file://`)에서는 WebSocket 연결 시 서버 주소를 수동 입력해야 합니다.

### 4. 테스트 실행

**Windows:**
```
run_tests.bat
```
**또는 직접:**
```bash
cd server
python -m pytest tests/ -v
```

---

## 프로젝트 구조

```
MadoriHoldem/
├── client/                  # 웹 클라이언트
│   ├── index.html           # 단일 페이지 앱 (HTML + CSS + JS)
│   └── dealer.jpg           # 딜러 이미지
│
├── server/                  # FastAPI 서버
│   ├── main.py              # WebSocket 라우터, 턴 타이머, AI 스케줄러
│   ├── game/
│   │   ├── card.py          # Card, Deck (Fisher-Yates 셔플)
│   │   ├── betting.py       # BettingRound, 사이드팟 계산
│   │   ├── hand_evaluator.py# 7장 → 최강 5장, 족보 판정
│   │   ├── game_state.py    # FSM (WAITING→PRE_FLOP→…→HAND_END)
│   │   ├── room_manager.py  # 방 생성/참가/퇴장
│   │   └── ai_strategy.py   # AI 봇 의사결정
│   └── tests/
│       ├── test_betting.py  # BettingRound / 사이드팟 / 순서 테스트
│       └── test_hand_eval.py# 패 족보 테스트
│
├── docs/                    # 설계 문서
│   ├── RULES.md             # 게임 룰 및 서버 구현 요약
│   ├── HOLDEM_FLOW.md       # 홀덤 순서 상세 (블라인드~쇼다운)
│   ├── IMPL_PLAN.md         # 버그 분석 및 구현 계획
│   └── holdem_prd.docx      # 초기 PRD
│
├── tools/                   # 개발/테스트 보조 도구
│   ├── test_client.py       # 2인 자동 시뮬레이션 (WebSocket)
│   └── interactive_client.py# 터미널 대화형 클라이언트
│
├── run_server.bat           # 서버 실행 (Windows)
├── run_client.bat           # 클라이언트 HTTP 서버 실행 (Windows)
├── run_tests.bat            # 단위 테스트 실행 (Windows)
└── requirements.txt         # Python 의존성
```

---

## 게임 설정 (기본값)

| 항목 | 값 |
|------|----|
| 시작 칩 | 100,000 |
| 스몰 블라인드 | 500 |
| 빅 블라인드 | 1,000 |
| 턴 타임아웃 | 30초 |
| 최대 인원 | 9명 (빈 자리는 AI 봇 자동 채움) |

---

## 주요 게임 흐름

```
블라인드 포스팅 → 홀카드 배분 (딜 애니메이션 3.5초)
→ PRE_FLOP 베팅
→ FLOP (커뮤니티 3장)
→ TURN (커뮤니티 4장)
→ RIVER (커뮤니티 5장)
→ SHOWDOWN / HAND_END
→ 5초 후 다음 핸드 자동 시작
```

- **방장**: 닉네임 `마도리`로 접속한 플레이어. 게임 시작 버튼 권한.
- **AI 봇**: 빈 자리에 자동 배치. 0.4~1.0초 랜덤 딜레이 후 행동.
- **헤즈업**: 버튼 = SB, 상대 = BB. 프리플랍에서 SB가 먼저 행동.

---

## WebSocket 이벤트 요약

| 방향 | 이벤트 | 설명 |
|------|--------|------|
| C→S | `join_room` | 방 입장 |
| C→S | `player_action` | fold / check / call / raise / allin |
| C→S | `start_game` | 게임 시작 (방장 전용) |
| S→C | `deal_hole_cards` | 홀카드 배분 (개인 전송) |
| S→C | `game_state` | 테이블 상태 갱신 |
| S→C | `action_required` | 해당 플레이어 행동 요청 |
| S→C | `showdown` | 쇼다운 결과 |
| S→C | `hand_end` | 폴드 승리 |

---

## 개발자 도구

```bash
# 자동 2인 시뮬레이션 (서버 실행 후)
python tools/test_client.py

# 터미널 대화형 클라이언트
python tools/interactive_client.py alice Alice ROOM1
python tools/interactive_client.py bob   Bob   ROOM1
```
