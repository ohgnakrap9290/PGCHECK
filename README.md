# PGCHECK

BaekjoonHub가 자동으로 커밋하는 Programmers 풀이 저장소를 확인해서 Discord로 알림을 보내는 자동화 프로젝트입니다.

현재 멤버:

- 박강호: `ohgnakrap9290/programmers-study`
- 이정찬: `jungchan06/programmers-study`
- 허윤혁: `flains/programmers-study`

## 동작 방식

즉시 알림은 GitHub Actions에서 5분마다 실행됩니다. 각 멤버의 오늘 KST 기준 BaekjoonHub 풀이 커밋을 확인하고, 이전 실행 이후 새 풀이 커밋이 있으면 커밋 1개당 Discord 메시지 1개를 보냅니다.

즉시 알림 메시지 예시:

```text
**✅ 박강호 1 COMMIT!**
------------------------
난이도: Lv. 000000
문제: 문자열로 변환
총 누적: 12 COMMIT
------------------------
```

`총 누적`은 오늘 누적이 아니라 해당 저장소의 전체 BaekjoonHub 풀이 커밋 누적 수입니다.
난이도는 숫자를 6번 반복해서 표시합니다. 예를 들어 0단계는 `000000`, 1단계는 `111111`입니다.

야간 요약은 매일 00:00 KST에 실행됩니다. 예약 실행은 직전 KST 날짜의 풀이 수를 멤버별로 집계하고, 이름 기준 가나다순으로 정렬해서 보냅니다.

야간 요약 예시:

```text
**📌 2026-05-18 프로그래머스 기록**
완료 2/3명 · 총 6문제

✅ 박강호: 5 COMMIT
✅ 이정찬: 1 COMMIT
❌ 허윤혁: 0 COMMIT
```

`Initial commit`, README 수정, 일반 커밋은 제외하고 `BaekjoonHub`가 들어간 풀이 커밋만 카운트합니다.

## GitHub Secrets

GitHub 저장소에서 `Settings -> Secrets and variables -> Actions -> New repository secret`으로 이동해 아래 값을 추가합니다.

- `FRIENDS_JSON`: 멤버 저장소 정보
- `DISCORD_WEBHOOK_URL`: Discord Webhook URL
- `GH_TOKEN`: 선택 사항. public 저장소만 확인한다면 필요하지 않습니다.

`FRIENDS_JSON`에는 아래 값을 그대로 넣습니다.

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

Discord Webhook URL은 Discord 채널 설정의 `연동` 또는 `Integrations` 메뉴에서 Webhook을 생성한 뒤 복사해서 `DISCORD_WEBHOOK_URL` secret에 넣습니다. Webhook URL은 코드, README, workflow, 로그, 커밋 메시지에 넣지 않습니다.

## GitHub Actions 수동 실행

즉시 알림 테스트:

```text
Actions -> Programmers Commit Poll -> Run workflow
```

야간 요약 테스트:

```text
Actions -> Programmers Nightly Summary -> Run workflow
```

수동 요약은 기본으로 오늘 KST 날짜를 요약합니다. 날짜 입력값을 넣으면 해당 날짜를 요약합니다.

## 로컬 테스트

PowerShell 예시:

```powershell
pip install -r requirements.txt
$env:FRIENDS_JSON='[{"name":"박강호","owner":"ohgnakrap9290","repo":"programmers-study"},{"name":"이정찬","owner":"jungchan06","repo":"programmers-study"},{"name":"허윤혁","owner":"flains","repo":"programmers-study"}]'
python programmers_check.py poll --dry-run
python programmers_check.py summary --dry-run
python programmers_check.py summary --date 2026-05-18 --dry-run
```

`--dry-run`을 사용하면 Discord로 전송하지 않고 stdout에만 출력합니다. `DISCORD_WEBHOOK_URL`이 없어도 stdout에 출력됩니다.

## 스케줄

GitHub Actions cron은 UTC 기준입니다.

- `*/5 * * * *`: 5분마다 즉시 알림 체크
- `0 15 * * *`: 매일 15:00 UTC 실행, 한국 시간으로 00:00 KST

두 workflow 파일은 `main` 브랜치의 `.github/workflows/` 아래에 있어야 예약 실행이 표시됩니다.

스크립트의 날짜 기준은 `Asia/Seoul`입니다. 야간 요약 예약 실행은 기본적으로 실행 시점의 전날 KST 날짜를 집계합니다. 예를 들어 2026-05-19 00:00 KST에 실행되면 2026-05-18 기록을 요약합니다.

## 상태 파일

즉시 알림은 `.state/seen_commits.json`에 이미 알림을 보낸 commit SHA를 저장합니다. GitHub Actions는 실행 간 로컬 파일을 유지하지 않으므로, polling workflow가 변경된 상태 파일을 이 저장소에 다시 commit/push합니다.

첫 실행 때 상태 파일이 없으면 오늘 이미 존재하는 커밋을 모두 본 것으로 표시하고 알림을 보내지 않습니다. 이후 실행부터 새 풀이 커밋만 즉시 알림으로 전송합니다. 새 멤버 저장소가 추가되어 상태 파일에 아직 없을 때도 해당 저장소의 현재 풀이 커밋을 먼저 초기화하므로 기존 커밋을 한 번에 보내지 않습니다.
