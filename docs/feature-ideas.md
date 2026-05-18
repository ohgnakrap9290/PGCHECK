# PGCHECK 기능 아이디어 메모

## 목표

Programmers 풀이 커밋 알림을 단순 체크에서 경쟁/성장형 시스템으로 확장한다.

## 확정하고 싶은 방향

### 1. 금주의 랭킹

- "오늘의 랭킹"보다 "금주의 랭킹"을 우선한다.
- 기준은 이번 주 KST 월요일 00:00부터 현재까지의 BaekjoonHub 풀이 커밋 수.
- 출력 예시:

```text
**🏆 금주의 랭킹**
1등 박강호: 18 COMMIT
2등 이정찬: 11 COMMIT
3등 허윤혁: 4 COMMIT
```

### 2. 종합 랭킹

- 단순 commit 수가 아니라 난이도별 점수제로 정한다.
- Programmers 커밋 메시지의 `[level N]`에서 난이도를 추출한다.
- 제안 점수:

```text
Lv. 0 = 1점
Lv. 1 = 2점
Lv. 2 = 5점
Lv. 3 = 13점
Lv. 4 = 34점
Lv. 5 = 89점
```

점수 배분 이유:

- Lv.0, Lv.1은 입문/기초 문제라 낮게 둔다.
- Lv.2부터 체감 난이도가 크게 올라가므로 5점으로 벌린다.
- Lv.3 이상은 해결 빈도가 낮고 난이도 차이가 커서 피보나치형 가중치를 쓴다.
- 쉬운 문제 대량 풀이도 의미 있지만, 높은 난이도 풀이가 랭킹에 확실히 반영되게 한다.

출력 예시:

```text
**👑 종합 랭킹**
1등 박강호[OPUS]: 42점 / 20 COMMIT
2등 이정찬[CODEX]: 31점 / 15 COMMIT
3등 허윤혁[개허접]: 9점 / 6 COMMIT
```

등수 태그:

```text
1등 = OPUS
2등 = CODEX
3등 = 개허접
```

### 3. Discord 명령어

Webhook만으로는 사용자가 Discord에 명령어를 입력했을 때 응답하는 기능을 만들 수 없다.

명령어를 지원하려면 별도 Discord Bot 또는 Discord Interactions endpoint가 필요하다.

가능한 명령어:

```text
/poll
/summary
/weekly
/ranking
/stats 이름
```

동작 아이디어:

- `/poll`: 지금 시점 기준 새 풀이 커밋 체크
- `/summary`: 지금 시점 기준 오늘 KST 요약 출력
- `/weekly`: 금주의 랭킹 출력
- `/ranking`: 종합 점수 랭킹 출력
- `/stats 박강호`: 개인별 상세 스탯 출력

구현 선택지:

1. Discord Bot을 별도 서버에서 상시 실행
2. Vercel/Cloudflare Workers 같은 서버리스 endpoint로 Discord Interactions 처리
3. 명령어가 GitHub Actions `workflow_dispatch`를 호출하게 연결

### 4. 개인별 스탯

`/stats 이름` 명령어로 출력하고 싶은 항목:

필수:

- 하루 최대 COMMIT 수
- 현재 종합 점수
- 종합 랭킹 등수
- 총 풀이 COMMIT 수
- 난이도별 풀이 수

출력 예시:

```text
**📊 박강호 스탯**
종합 등수: 1등 [OPUS]
현재 점수: 42점
총 풀이: 20 COMMIT
하루 최고: 6 COMMIT

난이도 분포
Lv.0: 10문제
Lv.1: 6문제
Lv.2: 3문제
Lv.3: 1문제
Lv.4: 0문제
Lv.5: 0문제
```

추가 후보:

- 현재 연속 풀이 일수
- 최장 연속 풀이 일수
- 이번 주 풀이 수
- 이번 달 풀이 수
- 평균 일일 풀이 수
- 마지막 풀이 시간
- 가장 많이 푼 난이도
- 최고 난이도 풀이
- Lv.2 이상 풀이 수
- 주간 성장률
- 지난주 대비 증감

### 5. 야간 요약 확장

기존 야간 요약에 아래 정보를 추가할 수 있다.

```text
**📌 2026-05-18 프로그래머스 기록**
완료 2/3명 · 총 6문제

✅ 박강호: 5 COMMIT
✅ 이정찬: 1 COMMIT
❌ 허윤혁: 0 COMMIT

**🏆 금주의 랭킹**
1등 박강호: 18 COMMIT
2등 이정찬: 11 COMMIT
3등 허윤혁: 4 COMMIT

**👑 종합 랭킹**
1등 박강호[OPUS]: 42점
2등 이정찬[CODEX]: 31점
3등 허윤혁[개허접]: 9점
```

## 구현 시 필요한 상태 파일

현재:

- `.state/seen_commits.json`
- `.state/sent_summaries.json`

추가 가능:

- `.state/member_stats.json`

다만 저장소 전체 커밋을 매번 GitHub API로 다시 계산할 수도 있다. 멤버 수와 커밋 수가 적은 동안은 재계산 방식이 단순하다.
