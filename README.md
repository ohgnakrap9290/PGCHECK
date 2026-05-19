# PGCHECK

BaekjoonHub가 자동 커밋한 Programmers 풀이 기록을 확인해서 Discord로 알려주는 자동화 프로젝트입니다.

현재 멤버는 박강호, 이정찬, 허윤혁입니다.

## 기능

### 1. 즉시 풀이 알림

GitHub Actions가 5분마다 각 멤버의 `programmers-study` 저장소를 확인합니다. 새 BaekjoonHub 풀이 커밋이 있으면 커밋 1개당 Discord 메시지 1개를 보냅니다.

```text
**✅ 박강호 1 COMMIT!**
------------------------
난이도: Lv. 000000
문제: 수 조작하기 1
총 누적: 6 COMMIT
------------------------
```

`총 누적`은 오늘 누적이 아니라 해당 저장소의 전체 BaekjoonHub 풀이 커밋 수입니다. 난이도는 Programmers 커밋 메시지의 `[level 0]` 값을 읽고, `0`이면 `000000`, `1`이면 `111111`처럼 표시합니다.

### 2. 밤 12시 요약

매일 00:00 KST에 전날 KST 날짜를 요약합니다. GitHub Actions cron은 UTC 기준이라 workflow는 `0 15 * * *`에 실행됩니다.

```text
**📌 2026-05-18 프로그래머스 기록**
완료 2/3명 · 총 6문제

✅ 박강호: 3 COMMIT
❌ 이정찬: 0 COMMIT
✅ 허윤혁: 2 COMMIT
```

Actions 예약 실행이 지연되거나 누락될 수 있어 00:10, 00:20 KST 재시도도 함께 설정되어 있습니다. `.state/sent_summaries.json`으로 같은 날짜 요약 중복 전송을 막습니다.

### 3. 랭킹과 스탯

난이도별 점수는 다음 기준을 사용합니다.

```text
Lv.0 = 1점
Lv.1 = 2점
Lv.2 = 5점
Lv.3 = 13점
Lv.4 = 34점
Lv.5 = 89점
```

종합 랭킹은 점수 기준입니다. 동점이면 총 COMMIT 수, 이름순으로 정렬합니다.

등수 태그:

```text
1등 [OPUS]
2등 [CODEX]
3등 [개허접]
```

개인 스탯에는 종합 순위, 현재 점수, 총 누적 COMMIT, 이번 주 COMMIT, 이번 달 COMMIT, 하루 최대 COMMIT, 현재 연속 풀이일, 최장 연속 풀이일, 마지막 풀이 시각, 난이도별 풀이 수가 표시됩니다.

### 4. 상시 랭킹판

`Programmers Commit Poll` workflow가 5분마다 같은 Discord 메시지를 수정해서 상시 랭킹판을 최신 상태로 유지합니다. 새 메시지를 계속 보내는 방식이 아니라, 처음 한 번 만든 랭킹판 메시지를 계속 edit합니다.

예시:

```text
**프로그래머스 랭킹판**
업데이트: 2026-05-19 18:35 KST

종합 랭킹
------------------------------------
**1st 박강호[OPUS]**   / Python / 6점 / 6 COMMIT
**2nd 허윤혁[CODEX]**  / C / 2점 / 2 COMMIT
**3rd 이정찬[개허접]** / C / 1점 / 1 COMMIT
------------------------------------
```

랭킹판 메시지 ID는 `.state/ranking_message.json`에 저장됩니다. 이 파일은 `.gitignore`에 넣으면 안 됩니다.

랭킹판은 `DISCORD_RANKING_WEBHOOK_URL` secret이 있으면 그 채널에 생성/수정됩니다. 이 값이 없으면 기존 `DISCORD_WEBHOOK_URL` 채널을 사용합니다. 커밋 알림과 밤 12시 요약은 계속 `DISCORD_WEBHOOK_URL`을 사용합니다.

## Discord 봇 명령어

웹훅은 메시지를 보내기만 할 수 있고 `/help` 같은 명령어를 받을 수 없습니다. slash command를 쓰려면 `discord_bot.py`를 별도 서버, PC, Railway, Render 같은 곳에서 계속 실행해야 합니다.

봇 명령어:

```text
/help
/poll
/summary
/summary date:2026-05-18
/weekly
/ranking
/stats name:박강호
```

`/help`는 사용 가능한 명령어 목록을 보여줍니다. `/poll`은 지금 기준 새 커밋을 확인합니다. `/summary`는 밤 12시에 오는 메시지와 같은 형식으로 요약을 보여줍니다. `/weekly`는 금주의 COMMIT 랭킹, `/ranking`은 난이도 점수 기반 종합 랭킹, `/stats`는 개인 스탯입니다.

봇 실행에 필요한 환경변수:

```text
DISCORD_BOT_TOKEN
FRIENDS_JSON
GH_TOKEN 선택
DISCORD_GUILD_ID 선택
```

`DISCORD_GUILD_ID`를 넣으면 해당 서버에 slash command가 더 빨리 반영됩니다. 없으면 전역 명령어로 등록되어 반영까지 시간이 걸릴 수 있습니다.

로컬 PowerShell 예시:

```powershell
pip install -r requirements.txt
$env:DISCORD_BOT_TOKEN='your bot token'
$env:FRIENDS_JSON='[{"name":"박강호","owner":"ohgnakrap9290","repo":"programmers-study"},{"name":"이정찬","owner":"jungchan06","repo":"programmers-study"},{"name":"허윤혁","owner":"flains","repo":"programmers-study"}]'
python discord_bot.py
```

Bot Token은 Discord Developer Portal에서 애플리케이션과 봇을 만든 뒤 발급합니다. 이 토큰은 절대 코드, README, workflow, 로그, 커밋 메시지에 넣지 않습니다.

## GitHub Secrets

GitHub 저장소에서 `Settings -> Secrets and variables -> Actions -> New repository secret`으로 아래 값을 추가합니다.

- `FRIENDS_JSON`: 멤버 저장소 정보
- `DISCORD_WEBHOOK_URL`: Discord Webhook URL
- `DISCORD_RANKING_WEBHOOK_URL`: 선택 사항. 상시 랭킹판 전용 Discord Webhook URL
- `GH_TOKEN`: 선택 사항. public 저장소만 확인한다면 없어도 됩니다.

`FRIENDS_JSON` 값:

```json
[
  {
    "name": "박강호",
    "owner": "ohgnakrap9290",
    "repo": "programmers-study"
  },
  {
    "name": "이정찬",
    "owner": "jungchan06",
    "repo": "programmers-study"
  },
  {
    "name": "허윤혁",
    "owner": "flains",
    "repo": "programmers-study"
  }
]
```

Discord Webhook URL은 Discord 채널 설정의 `Integrations` 메뉴에서 Webhook을 생성해서 복사합니다. Webhook URL은 secret에만 넣고 코드에는 넣지 않습니다.

## GitHub Actions

즉시 알림 workflow:

```text
Actions -> Programmers Commit Poll -> Run workflow
```

밤 12시 요약 workflow:

```text
Actions -> Programmers Nightly Summary -> Run workflow
```

개인 스탯/랭킹 수동 전송:

```text
Actions -> Programmers Manual Stats -> Run workflow
```

입력값:

```text
kind: stats, ranking, weekly, board 중 하나
name: stats일 때 사용할 이름. 예: 박강호
```

`kind=stats`는 개인 스탯을 보냅니다. `kind=ranking`은 종합 랭킹, `kind=weekly`는 금주의 랭킹, `kind=board`는 상시 랭킹판을 즉시 생성하거나 수정합니다.

cron 기준:

```text
*/5 * * * *      5분마다 즉시 알림 확인
0 15 * * *       00:00 KST 요약
10 15 * * *      00:10 KST 재시도
20 15 * * *      00:20 KST 재시도
```

GitHub Actions cron은 UTC 기준입니다.

## 로컬 테스트

PowerShell:

```powershell
pip install -r requirements.txt
$env:FRIENDS_JSON='[{"name":"박강호","owner":"ohgnakrap9290","repo":"programmers-study"},{"name":"이정찬","owner":"jungchan06","repo":"programmers-study"},{"name":"허윤혁","owner":"flains","repo":"programmers-study"}]'
python programmers_check.py poll --dry-run
python programmers_check.py summary --dry-run
python programmers_check.py summary --date 2026-05-18 --dry-run
python programmers_check.py weekly --dry-run
python programmers_check.py ranking --dry-run
python programmers_check.py board --dry-run
python programmers_check.py stats 박강호 --dry-run
```

`--dry-run`을 쓰면 Discord로 보내지 않고 stdout에만 출력합니다. `DISCORD_WEBHOOK_URL`이 없어도 stdout으로 출력됩니다.

## 상태 파일

즉시 알림은 `.state/seen_commits.json`에 이미 알린 commit SHA를 저장합니다. GitHub Actions 실행 환경은 매번 새로 만들어지므로, polling workflow가 상태 파일 변경분을 PGCHECK 저장소에 다시 commit/push합니다.

처음 실행할 때는 기존 오늘 커밋을 전부 알림으로 보내지 않고 이미 본 것으로 초기화합니다. 이후 새로 생긴 커밋부터 즉시 알림을 보냅니다.

상시 랭킹판은 `.state/ranking_message.json`에 Discord 메시지 ID를 저장합니다. 메시지가 삭제되었거나 찾을 수 없으면 다음 실행 때 새 랭킹판 메시지를 만들고 ID를 다시 저장합니다.

언어 표시는 커밋 상세 정보의 변경 파일 확장자를 보고 계산합니다. 확인한 언어는 `.state/commit_languages.json`에 캐시해서 5분마다 GitHub API를 과하게 호출하지 않게 합니다.
