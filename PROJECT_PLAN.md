
# GodLife Discord Bot — MVP 기획서 (수정본 v0.2, 2025-11-11 (KST))

## 0. 개요
- 목적: 개인 루틴·목표 관리와 일일 리마인더를 **DM 중심 + 버튼/모달**로 제공합니다.
- 기술: **discord.py**, aiosqlite, holidays, tzdata, python-dotenv
- 실행 환경: 서버 상시 가동(게이트웨이 연결), 단일 프로세스
- 하루 경계: **04:00 (Asia/Seoul)** — `local_day = (now_kst - 4h).date()`
- 명령 체계(4개만 사용): `/routine`, `/goal`, `/report`, `/settings`
  - 이후 조작은 **버튼/모달 우선**
  - 공수 과다·불가 영역은 **임시 서브명령** 허용(추후 버튼/모달로 대체)

---

## 1. 범위(Scope)
### 포함(MVP)
- 일일 루틴 CRUD(주말 포함/제외)
- 목표 CRUD(일간/주간/월간)
- 달성도 리포트(전체/최근 30일/최근 7일)
- 사용자별 기본 리마인더 시각
- 한국 공휴일·주말 자동 제외(분모 제외)
- 스킵/면책 등록(분모 제외)
- “특정 시각까지 미달성 시” 리마인더
- 하루 경계 04:00

### 제외(후순위)
- 팀/랭킹, 가중치/뱃지, 외부 동기화(Notion/Sheets), 웹 대시보드, 다국어, 고급 RRULE

---

## 2. 스토리보드(사용자 흐름)
4개의 명령어가 각 기능의 **진입점**입니다. 진입 이후는 버튼/모달로 흐름을 이어갑니다.

### `/routine` — 루틴 패널
- DM에 루틴 패널 임베드 + 버튼 View 표시
- 오늘 유효 루틴 N개 목록(주말/공휴일/면책 반영)
- 각 항목 버튼: **[✅ 완료][↩ 되돌리기][🛌 스킵]**
- 상단/하단 버튼: **[루틴 추가]**
- 루틴 추가 모달: 이름, 주말 모드(`평일만/주말만/전체`), 마감 시각(HH:MM), 메모

### `/goal` — 목표 패널
- 목표 리스트, 각 항목에 **[+1 진행]** 버튼
- **[목표 추가]** 모달: 제목, 주기(`일간/주간/월간`), 타깃(정수), 마감(선택), 이월(bool)

### `/report` — 기간 선택 → 리포트
- 버튼: **[전체][30일][7일]**
- 선택 시 임베드 리포트(달성률·스테REAK·요약)

### `/settings` — 설정 모달
- 리마인더 기본 시각(HH:MM) 입력
- (확장 여지) 타임존, 데이터 초기화 토글 등

> 임시 서브명령(필요 시만 활성화): `/routine add|edit|delete`, `/goal add|edit|delete`, `/report scope:…`, `/settings reminder:…`

---

## 3. 인터랙션 사양
### 버튼 `custom_id` 규칙
- 루틴: `rt:done|undo|skip:<routine_id>:<yyyymmdd>`
- 목표: `goal:inc:<goal_id>`
- 리포트: `ui:report:<scope>` (`all|30d|7d`)
- 설정: `ui:settings`

### 모달
- **루틴 추가**: `name`, `weekend_mode`, `deadline_time(HH:MM)`, `notes`
- **목표 추가**: `title`, `period`, `target`, `deadline(optional)`, `carry_over(bool)`
- **스킵 사유**: `reason(optional)`, `apply_day(default=today)`
- **설정**: `reminder_time(HH:MM)`

---

## 4. 시간·캘린더 규칙
- 타임존: `Asia/Seoul`, `now_kst()` 유틸
- **하루 경계**: `local_day = (now_kst - 4h).date()`
- 유효일(분모) 산정:
  1) 주말 모드(평일만/주말만/전체)  
  2) **한국 공휴일 제외**: `holidays.KR`(연도별 캐시)  
  3) **면책 기간 제외**: `exemption` 테이블 조회

---

## 5. 데이터 모델(SQLite + aiosqlite)
```sql
-- 유저 설정
CREATE TABLE user_settings (
  user_id TEXT PRIMARY KEY,
  tz TEXT NOT NULL DEFAULT 'Asia/Seoul',
  reminder_time TEXT NOT NULL DEFAULT '08:00',  -- HH:MM
  created_at TEXT NOT NULL
);

-- 루틴
CREATE TABLE routine (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  weekend_mode TEXT NOT NULL CHECK(weekend_mode IN ('weekday','weekend','all')),
  deadline_time TEXT,                -- HH:MM
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- 루틴 체크인
CREATE TABLE routine_checkin (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  routine_id INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  local_day TEXT NOT NULL,           -- YYYY-MM-DD (04:00 경계)
  checked_at TEXT,                   -- 완료 시각
  undone_at TEXT,                    -- 되돌리기 시각
  skipped INTEGER NOT NULL DEFAULT 0,
  skip_reason TEXT,
  UNIQUE (routine_id, local_day)
);

-- 목표
CREATE TABLE goal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  period TEXT NOT NULL CHECK(period IN ('daily','weekly','monthly')),
  target INTEGER NOT NULL,
  current INTEGER NOT NULL DEFAULT 0,
  carry_over INTEGER NOT NULL DEFAULT 0,
  deadline TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- 목표 진행 로그
CREATE TABLE goal_progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  delta INTEGER NOT NULL,
  value_after INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

-- 면책(스킵) 기간
CREATE TABLE exemption (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  start_day TEXT NOT NULL,           -- YYYY-MM-DD
  end_day TEXT NOT NULL,             -- YYYY-MM-DD
  reason TEXT
);

-- 인덱스
CREATE INDEX idx_checkin_user_day ON routine_checkin(user_id, local_day);
CREATE INDEX idx_goal_user ON goal(user_id, active);
```

---

## 6. 리포트 계산
- **루틴 달성률** = `완료 일수 / 유효 일수`  
  - 유효 일수: 집계 구간 내 `is_valid_day(user, weekend_mode, date)` 참인 날짜 수  
  - 완료 일수: 해당 날짜에 `skipped=0 AND checked_at NOT NULL`  
- **스테REAK**: 유효 날짜 기준 연속 완료
- **구간**: `all`, `last_30d`, `last_7d`
- **목표 달성**: period 경계에서 `current >= target`이면 달성(이월은 carry_over 규칙 따름)

---

## 7. 리마인더·스케줄러
- **일일 프롬프트**: `user_settings.reminder_time`에 DM으로 “오늘의 루틴” 카드 발송  
  - 유효 루틴 0개면 생략
- **미달성 리마인더**: `routine.deadline_time`(없으면 user 기본) 시각에 미완료 루틴 있으면 1회 DM
- **구현**: 봇 기동 시 당일 예약 생성 → `asyncio` 타이머 대기 → 발송  
  - 5분 주기 보정 루프(프로세스 재시작 시 누락 복구)  
  - 중복 방지 키: `user_id:local_day:daily_prompt`, `user_id:local_day:reminder_sent`

---

## 8. 명령어 사양(4개)
- **`/routine`**: 루틴 패널 표시(DM). 이후 조작은 버튼/모달.  
- **`/goal`**: 목표 패널 표시(DM). 이후 조작은 버튼/모달.  
- **`/report`**: 기간 버튼 노출 → 임베드 리포트.  
- **`/settings`**: 설정 모달(리마인더 기본 시각).  

> 임시 서브명령(선택): `/routine add|edit|delete`, `/goal add|edit|delete`, `/report scope:…`, `/settings reminder:…`

---

## 9. 권한·프라이버시
- DM 중심 동작, 서버 권한 최소화(테스트 서버 초대 필요)
- 데이터 삭제/초기화는 확인 모달 제공
- 로깅은 최소한의 메타데이터만 저장(개인 메시지 본문 저장 금지 권장)

---

## 10. 개발·테스트 일정(3일)
- **Day 1**: 프로젝트 세팅/DB/시간 유틸, `/routine` 패널 + 루틴 CRUD, 체크인(완료/되돌리기/스킵)
- **Day 2**: `/goal` 패널 + 목표 CRUD(+1), 리마인더 스케줄러, 주말·공휴일·면책 반영
- **Day 3**: `/report` 계산/임베드, `/settings` 모달, 보정 루프/중복 방지, 테스트

---

## 11. 리스크 및 스코프 컷
- **시간 경계/캘린더**: 단일 유틸 함수로만 처리해 일관성 유지
- **프로세스 다운**: 보정 루프 도입, 일일 프롬프트/리마인더 멱등 키
- **UX 대체 경로**: 버튼/모달 어려운 구간은 임시 서브명령 허용
- **스코프 컷**: 목표 기능/리포트 일부를 Day 3에 후순위로 밀어 루틴·리마인더를 우선 완성

---

## 12. 추후 확장
- 고급 반복(RRULE), 팀/챌린지, 가중치·뱃지, 외부 동기화(Notion/Sheets), 대시보드, 다국어(i18n)
