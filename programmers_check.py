from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


GITHUB_API_URL = "https://api.github.com"
KST = ZoneInfo("Asia/Seoul")
DISCORD_LIMIT = 2000
STATE_PATH = Path(".state/seen_commits.json")
SOLUTION_COMMIT_MARKERS = ("-BaekjoonHub", "BaekjoonHub")


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Friend:
    name: str
    owner: str
    repo: str
    branch: str | None = None

    @property
    def repo_key(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    message: str
    url: str


@dataclass(frozen=True)
class SummaryResult:
    friend: Friend
    count: int = 0
    error: str | None = None


def is_solution_commit(commit: CommitInfo) -> bool:
    return any(marker in commit.message for marker in SOLUTION_COMMIT_MARKERS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Programmers 풀이 저장소의 GitHub 커밋을 확인하고 Discord로 알립니다."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    poll_parser = subparsers.add_parser("poll", help="새 커밋을 확인하고 즉시 알림을 보냅니다.")
    poll_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discord 전송과 상태 저장 없이 결과만 출력합니다.",
    )

    summary_parser = subparsers.add_parser("summary", help="KST 날짜별 커밋 요약을 보냅니다.")
    summary_parser.add_argument(
        "--date",
        type=parse_kst_date,
        help="요약할 KST 날짜입니다. 형식: YYYY-MM-DD",
    )
    summary_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discord로 보내지 않고 결과를 stdout에만 출력합니다.",
    )

    return parser.parse_args()


def parse_kst_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"날짜 값이 올바르지 않습니다: {value!r}. YYYY-MM-DD 형식을 사용하세요."
        ) from exc


def load_friends() -> list[Friend]:
    raw = os.getenv("FRIENDS_JSON")
    if not raw:
        raise ConfigError("FRIENDS_JSON 환경변수가 없습니다.")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"FRIENDS_JSON을 JSON으로 파싱할 수 없습니다: {exc}") from exc

    if not isinstance(data, list):
        raise ConfigError("FRIENDS_JSON은 JSON 배열이어야 합니다.")

    friends: list[Friend] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"FRIENDS_JSON의 {index}번째 항목은 객체여야 합니다.")

        missing = [key for key in ("name", "owner", "repo") if not item.get(key)]
        if missing:
            raise ConfigError(
                f"FRIENDS_JSON의 {index}번째 항목에 필수 값이 없습니다: {', '.join(missing)}"
            )

        branch = item.get("branch")
        if branch is not None and not isinstance(branch, str):
            raise ConfigError(f"FRIENDS_JSON의 {index}번째 branch 값은 문자열이어야 합니다.")

        friends.append(
            Friend(
                name=str(item["name"]),
                owner=str(item["owner"]),
                repo=str(item["repo"]),
                branch=branch,
            )
        )

    if not friends:
        raise ConfigError("FRIENDS_JSON에 멤버 정보가 없습니다.")

    return friends


def get_kst_date_range(target_date: date) -> tuple[str, str]:
    start_kst = datetime.combine(target_date, time.min, tzinfo=KST)
    end_kst = start_kst + timedelta(days=1) - timedelta(seconds=1)
    return to_utc_iso(start_kst), to_utc_iso(end_kst)


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def github_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pgcheck-programmers-checker",
        }
    )
    gh_token = os.getenv("GH_TOKEN")
    if gh_token:
        session.headers["Authorization"] = f"Bearer {gh_token}"
    return session


def fetch_commits(
    session: requests.Session,
    friend: Friend,
    since_utc: str,
    until_utc: str,
) -> list[CommitInfo]:
    commits: list[CommitInfo] = []
    url = f"{GITHUB_API_URL}/repos/{friend.owner}/{friend.repo}/commits"
    params: dict[str, Any] | None = {
        "since": since_utc,
        "until": until_utc,
        "per_page": 100,
    }
    if friend.branch:
        params["sha"] = friend.branch

    while url:
        response = session.get(url, params=params, timeout=20)
        if response.status_code >= 400:
            raise RuntimeError(format_github_error(response, friend))

        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"GitHub API 응답 형식이 예상과 다릅니다: {friend.repo_key}")

        for item in payload:
            if not isinstance(item, dict):
                continue
            commit = item.get("commit", {})
            message = ""
            if isinstance(commit, dict):
                message = str(commit.get("message", "")).splitlines()[0].strip()
            commits.append(
                CommitInfo(
                    sha=str(item.get("sha", "")),
                    message=message or "(커밋 메시지 없음)",
                    url=str(item.get("html_url", "")),
                )
            )

        url = response.links.get("next", {}).get("url")
        params = None

    return commits


def format_github_error(response: requests.Response, friend: Friend) -> str:
    try:
        body = response.json()
        message = body.get("message", response.text)
    except ValueError:
        message = response.text

    if response.status_code == 404:
        return f"{friend.repo_key} 저장소를 찾을 수 없거나 접근 권한이 없습니다."
    if response.status_code in (401, 403):
        return f"{friend.repo_key} 접근이 거부되었습니다. GH_TOKEN 권한 또는 API 제한을 확인하세요. ({message})"
    return f"{friend.repo_key} GitHub API 요청 실패: HTTP {response.status_code} ({message})"


def load_state() -> tuple[dict[str, list[str]], bool]:
    if not STATE_PATH.exists():
        return {}, False

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{STATE_PATH} 파일을 JSON으로 파싱할 수 없습니다: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"{STATE_PATH} 파일은 JSON 객체여야 합니다.")

    state: dict[str, list[str]] = {}
    for repo_key, shas in data.items():
        if isinstance(repo_key, str) and isinstance(shas, list):
            state[repo_key] = [str(sha) for sha in shas if sha]
    return state, True


def save_state(state: dict[str, list[str]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def send_discord_message(content: str, dry_run: bool = False) -> None:
    content = truncate_discord_content(content)
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    if dry_run or not webhook_url:
        if not webhook_url and not dry_run:
            print("DISCORD_WEBHOOK_URL이 없어 Discord 전송 대신 stdout에 출력합니다.", file=sys.stderr)
        print(content)
        return

    response = requests.post(webhook_url, json={"content": content}, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"Discord webhook 전송 실패: HTTP {response.status_code}")


def truncate_discord_content(content: str) -> str:
    if len(content) <= DISCORD_LIMIT:
        return content

    suffix = "\n...(Discord 2000자 제한으로 생략)"
    return content[: DISCORD_LIMIT - len(suffix)].rstrip() + suffix


def run_poll(dry_run: bool = False) -> int:
    friends = load_friends()
    session = github_session()
    target_date = datetime.now(KST).date()
    since_utc, until_utc = get_kst_date_range(target_date)
    state, state_exists = load_state()
    changed = False

    for friend in friends:
        try:
            commits = [commit for commit in fetch_commits(session, friend, since_utc, until_utc) if is_solution_commit(commit)]
        except Exception as exc:
            print(f"{friend.name} 확인 실패: {exc}", file=sys.stderr)
            continue

        repo_key = friend.repo_key
        current_shas = [commit.sha for commit in commits if commit.sha]
        seen = set(state.get(repo_key, []))

        if not state_exists or repo_key not in state:
            state[repo_key] = current_shas
            changed = True
            print(f"{repo_key} state initialized")
            continue

        new_commits = [commit for commit in reversed(commits) if commit.sha and commit.sha not in seen]
        for _commit in new_commits:
            send_discord_message(f"{friend.name} 1 COMMIT!", dry_run=dry_run)

        if new_commits:
            merged = list(dict.fromkeys(current_shas + state.get(repo_key, [])))
            state[repo_key] = merged[:500]
            changed = True

    if changed:
        if dry_run:
            print("dry-run: state file was not saved")
        else:
            save_state(state)
            print(f"state saved to {STATE_PATH}")
    else:
        print("no new commits")

    if not state_exists:
        print("state initialized")

    return 0


def run_summary(target_date: date | None = None, dry_run: bool = False) -> int:
    friends = sorted(load_friends(), key=lambda friend: friend.name)
    session = github_session()
    if target_date is None:
        target_date = datetime.now(KST).date() - timedelta(days=1)
    since_utc, until_utc = get_kst_date_range(target_date)

    results: list[SummaryResult] = []
    for friend in friends:
        try:
            commits = [commit for commit in fetch_commits(session, friend, since_utc, until_utc) if is_solution_commit(commit)]
            results.append(SummaryResult(friend=friend, count=len(commits)))
        except Exception as exc:
            print(f"{friend.name} 확인 실패: {exc}", file=sys.stderr)
            results.append(SummaryResult(friend=friend, error=str(exc)))

    lines = [f"{target_date.isoformat()} 프로그래머스 기록", ""]
    for result in results:
        if result.error:
            lines.append(f"⚠️ {result.friend.name} 확인 실패")
        elif result.count > 0:
            lines.append(f"✅ {result.friend.name} {result.count} COMMIT")
        else:
            lines.append(f"❌ {result.friend.name} 0")

    send_discord_message("\n".join(lines), dry_run=dry_run)
    return 0


def main() -> int:
    args = parse_args()

    try:
        if args.command == "poll":
            return run_poll(dry_run=args.dry_run)
        if args.command == "summary":
            return run_summary(target_date=args.date, dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        return 1

    print(f"알 수 없는 명령입니다: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
