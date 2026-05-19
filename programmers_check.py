from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter
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
SUMMARY_STATE_PATH = Path(".state/sent_summaries.json")
RANKING_STATE_PATH = Path(".state/ranking_message.json")
LANGUAGE_CACHE_PATH = Path(".state/commit_languages.json")
SOLUTION_COMMIT_MARKERS = ("-BaekjoonHub", "BaekjoonHub")

# Programmers Lv.0~5 체감 난이도 차이를 반영한 점수입니다.
LEVEL_POINTS = {0: 1, 1: 2, 2: 5, 3: 13, 4: 34, 5: 89}
RANK_TAGS = {1: "OPUS", 2: "CODEX", 3: "개허접"}
LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".java": "Java",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".go": "Go",
    ".rs": "Rust",
}


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
    committed_at: datetime

    @property
    def kst_date(self) -> date:
        return self.committed_at.astimezone(KST).date()


@dataclass(frozen=True)
class MemberStats:
    friend: Friend
    commits: tuple[CommitInfo, ...]
    score: int
    level_counts: dict[int, int]
    language_counts: dict[str, int]
    primary_language: str
    total_commits: int
    week_commits: int
    month_commits: int
    max_daily_commits: int
    current_streak: int
    longest_streak: int
    last_solved_at: datetime | None


@dataclass(frozen=True)
class SummaryResult:
    friend: Friend
    count: int = 0
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Programmers 풀이 GitHub 커밋을 확인하고 Discord로 알립니다.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    poll_parser = subparsers.add_parser("poll", help="새 풀이 커밋을 확인하고 즉시 알림을 보냅니다.")
    poll_parser.add_argument("--dry-run", action="store_true", help="Discord 전송과 상태 저장 없이 결과만 출력합니다.")
    poll_parser.add_argument("--skip-board", action="store_true", help="상시 랭킹판 업데이트를 건너뜁니다.")

    summary_parser = subparsers.add_parser("summary", help="KST 날짜별 풀이 기록 요약을 보냅니다.")
    summary_parser.add_argument("--date", type=parse_kst_date, help="요약할 KST 날짜입니다. 형식: YYYY-MM-DD")
    summary_parser.add_argument("--dry-run", action="store_true", help="Discord로 보내지 않고 stdout에만 출력합니다.")
    summary_parser.add_argument("--once", action="store_true", help="해당 날짜 요약을 이미 보냈다면 다시 보내지 않습니다.")

    weekly_parser = subparsers.add_parser("weekly", help="이번 주 COMMIT 랭킹을 보냅니다.")
    weekly_parser.add_argument("--dry-run", action="store_true", help="Discord로 보내지 않고 stdout에만 출력합니다.")

    ranking_parser = subparsers.add_parser("ranking", help="난이도 점수 기반 종합 랭킹을 보냅니다.")
    ranking_parser.add_argument("--dry-run", action="store_true", help="Discord로 보내지 않고 stdout에만 출력합니다.")

    board_parser = subparsers.add_parser("board", help="상시 랭킹판 메시지를 생성하거나 수정합니다.")
    board_parser.add_argument("--dry-run", action="store_true", help="Discord로 보내지 않고 stdout에만 출력합니다.")

    stats_parser = subparsers.add_parser("stats", help="개인 스탯을 보냅니다.")
    stats_parser.add_argument("name", help="멤버 이름")
    stats_parser.add_argument("--dry-run", action="store_true", help="Discord로 보내지 않고 stdout에만 출력합니다.")

    return parser.parse_args()


def parse_kst_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"날짜 값이 올바르지 않습니다: {value!r}. YYYY-MM-DD 형식을 사용하세요.") from exc


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
            raise ConfigError(f"FRIENDS_JSON의 {index}번째 항목에 필수 값이 없습니다: {', '.join(missing)}")

        branch = item.get("branch")
        if branch is not None and not isinstance(branch, str):
            raise ConfigError(f"FRIENDS_JSON의 {index}번째 branch 값은 문자열이어야 합니다.")

        friends.append(Friend(name=str(item["name"]), owner=str(item["owner"]), repo=str(item["repo"]), branch=branch))

    if not friends:
        raise ConfigError("FRIENDS_JSON에 멤버 정보가 없습니다.")
    return friends


def get_kst_date_range(target_date: date) -> tuple[str, str]:
    start_kst = datetime.combine(target_date, time.min, tzinfo=KST)
    end_kst = start_kst + timedelta(days=1) - timedelta(seconds=1)
    return to_utc_iso(start_kst), to_utc_iso(end_kst)


def get_kst_week_range(target_date: date | None = None) -> tuple[date, date]:
    target_date = target_date or datetime.now(KST).date()
    start = target_date - timedelta(days=target_date.weekday())
    return start, target_date


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_github_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
    since_utc: str | None = None,
    until_utc: str | None = None,
) -> list[CommitInfo]:
    commits: list[CommitInfo] = []
    url = f"{GITHUB_API_URL}/repos/{friend.owner}/{friend.repo}/commits"
    params: dict[str, Any] | None = {"per_page": 100}
    if since_utc:
        params["since"] = since_utc
    if until_utc:
        params["until"] = until_utc
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
            committed_at = datetime.now(timezone.utc)
            if isinstance(commit, dict):
                message = str(commit.get("message", "")).splitlines()[0].strip()
                date_value = None
                committer = commit.get("committer", {})
                author = commit.get("author", {})
                if isinstance(committer, dict):
                    date_value = committer.get("date")
                if not date_value and isinstance(author, dict):
                    date_value = author.get("date")
                committed_at = parse_github_datetime(str(date_value) if date_value else None)

            commits.append(
                CommitInfo(
                    sha=str(item.get("sha", "")),
                    message=message or "(커밋 메시지 없음)",
                    url=str(item.get("html_url", "")),
                    committed_at=committed_at,
                )
            )

        url = response.links.get("next", {}).get("url")
        params = None

    return commits


def fetch_commit_files(session: requests.Session, friend: Friend, sha: str) -> list[str]:
    url = f"{GITHUB_API_URL}/repos/{friend.owner}/{friend.repo}/commits/{sha}"
    response = session.get(url, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(format_github_error(response, friend))

    payload = response.json()
    files = payload.get("files", []) if isinstance(payload, dict) else []
    if not isinstance(files, list):
        return []

    filenames: list[str] = []
    for item in files:
        if isinstance(item, dict) and item.get("filename"):
            filenames.append(str(item["filename"]))
    return filenames


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


def is_solution_commit(commit: CommitInfo) -> bool:
    return any(marker in commit.message for marker in SOLUTION_COMMIT_MARKERS)


def solution_commits(commits: list[CommitInfo]) -> list[CommitInfo]:
    return [commit for commit in commits if is_solution_commit(commit)]


def problem_title(commit: CommitInfo) -> str:
    message = commit.message.replace("-BaekjoonHub", "").replace("BaekjoonHub", "").strip()
    match = re.search(r"Title:\s*(.*?)(?:,\s*Time:|$)", message)
    if match:
        return match.group(1).strip()
    return message or "풀이 커밋"


def problem_level_number(commit: CommitInfo) -> int | None:
    match = re.search(r"\[level\s*(\d+)\]", commit.message, flags=re.IGNORECASE)
    if not match:
        return None
    level = int(match.group(1))
    return level if level in LEVEL_POINTS else None


def problem_level(commit: CommitInfo) -> str:
    level = problem_level_number(commit)
    if level is None:
        return "Lv. ??????"
    return f"Lv. {str(level) * 6}"


def commit_points(commit: CommitInfo) -> int:
    level = problem_level_number(commit)
    if level is None:
        return 1
    return LEVEL_POINTS[level]


def language_from_filename(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower()
    return LANGUAGE_EXTENSIONS.get(suffix)


def load_language_cache() -> dict[str, str]:
    data = load_json_file(LANGUAGE_CACHE_PATH, {})
    if not isinstance(data, dict):
        raise ConfigError(f"{LANGUAGE_CACHE_PATH} 파일은 JSON 객체여야 합니다.")
    return {str(key): str(value) for key, value in data.items() if value}


def save_language_cache(cache: dict[str, str]) -> None:
    write_json_file(LANGUAGE_CACHE_PATH, cache)


def commit_language(
    session: requests.Session,
    friend: Friend,
    commit: CommitInfo,
    cache: dict[str, str],
) -> tuple[str | None, bool]:
    if not commit.sha:
        return None, False

    cache_key = f"{friend.repo_key}:{commit.sha}"
    if cache_key in cache:
        return cache[cache_key], False

    try:
        filenames = fetch_commit_files(session, friend, commit.sha)
    except Exception as exc:
        print(f"{friend.name} 언어 확인 실패: {exc}", file=sys.stderr)
        return None, False

    languages = [language for filename in filenames if (language := language_from_filename(filename))]
    if not languages:
        return None, False

    language = Counter(languages).most_common(1)[0][0]
    cache[cache_key] = language
    return language, True


def rank_tag(rank: int) -> str:
    tag = RANK_TAGS.get(rank)
    return f"[{tag}]" if tag else ""


def rank_label(rank: int) -> str:
    if 10 <= rank % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def display_width(value: str) -> int:
    width = 0
    for char in value:
        width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
    return width


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} 파일을 JSON으로 파싱할 수 없습니다: {exc}") from exc


def write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_state() -> tuple[dict[str, list[str]], bool]:
    if not STATE_PATH.exists():
        return {}, False

    data = load_json_file(STATE_PATH, {})
    if not isinstance(data, dict):
        raise ConfigError(f"{STATE_PATH} 파일은 JSON 객체여야 합니다.")

    state: dict[str, list[str]] = {}
    for repo_key, shas in data.items():
        if isinstance(repo_key, str) and isinstance(shas, list):
            state[repo_key] = [str(sha) for sha in shas if sha]
    return state, True


def save_state(state: dict[str, list[str]]) -> None:
    write_json_file(STATE_PATH, state)


def load_summary_state() -> set[str]:
    data = load_json_file(SUMMARY_STATE_PATH, [])
    if not isinstance(data, list):
        raise ConfigError(f"{SUMMARY_STATE_PATH} 파일은 JSON 배열이어야 합니다.")
    return {str(item) for item in data}


def save_summary_state(sent_dates: set[str]) -> None:
    write_json_file(SUMMARY_STATE_PATH, sorted(sent_dates))


def load_ranking_state() -> dict[str, str]:
    data = load_json_file(RANKING_STATE_PATH, {})
    if not isinstance(data, dict):
        raise ConfigError(f"{RANKING_STATE_PATH} 파일은 JSON 객체여야 합니다.")
    message_id = data.get("message_id")
    return {"message_id": str(message_id)} if message_id else {}


def save_ranking_state(message_id: str) -> None:
    write_json_file(RANKING_STATE_PATH, {"message_id": message_id})


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


def ranking_webhook_url() -> str | None:
    return os.getenv("DISCORD_RANKING_WEBHOOK_URL") or os.getenv("DISCORD_WEBHOOK_URL")


def create_discord_webhook_message(content: str) -> str:
    webhook_url = ranking_webhook_url()
    if not webhook_url:
        raise ConfigError("DISCORD_RANKING_WEBHOOK_URL 또는 DISCORD_WEBHOOK_URL 환경변수가 없습니다.")

    response = requests.post(
        webhook_url,
        params={"wait": "true"},
        json={"content": truncate_discord_content(content)},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Discord ranking message 생성 실패: HTTP {response.status_code}")

    payload = response.json()
    message_id = payload.get("id")
    if not message_id:
        raise RuntimeError("Discord ranking message ID를 응답에서 찾을 수 없습니다.")
    return str(message_id)


def edit_discord_webhook_message(message_id: str, content: str) -> bool:
    webhook_url = ranking_webhook_url()
    if not webhook_url:
        raise ConfigError("DISCORD_RANKING_WEBHOOK_URL 또는 DISCORD_WEBHOOK_URL 환경변수가 없습니다.")

    response = requests.patch(
        f"{webhook_url}/messages/{message_id}",
        json={"content": truncate_discord_content(content)},
        timeout=20,
    )
    if response.status_code == 404:
        return False
    if response.status_code >= 400:
        raise RuntimeError(f"Discord ranking message 수정 실패: HTTP {response.status_code}")
    return True


def truncate_discord_content(content: str) -> str:
    if len(content) <= DISCORD_LIMIT:
        return content

    suffix = "\n...(Discord 2000자 제한으로 생략)"
    return content[: DISCORD_LIMIT - len(suffix)].rstrip() + suffix


def format_commit_notification(friend: Friend, commit: CommitInfo, total_count: int) -> str:
    return "\n".join(
        [
            f"**✅ {friend.name} 1 COMMIT!**",
            "------------------------",
            f"난이도: {problem_level(commit)}",
            f"문제: {problem_title(commit)}",
            f"총 누적: {total_count} COMMIT",
            "------------------------",
        ]
    )


def build_stats(session: requests.Session, friends: list[Friend], today: date | None = None) -> list[MemberStats]:
    today = today or datetime.now(KST).date()
    week_start, week_end = get_kst_week_range(today)
    month_start = today.replace(day=1)
    stats: list[MemberStats] = []
    language_cache = load_language_cache()
    language_cache_changed = False

    for friend in friends:
        commits = tuple(solution_commits(fetch_commits(session, friend)))
        level_counts: Counter[int] = Counter()
        language_counts: Counter[str] = Counter()
        daily_counts: Counter[date] = Counter()
        score = 0

        for commit in commits:
            level = problem_level_number(commit)
            if level is not None:
                level_counts[level] += 1
            language, language_changed = commit_language(session, friend, commit, language_cache)
            if language:
                language_counts[language] += 1
            language_cache_changed = language_cache_changed or language_changed
            score += commit_points(commit)
            daily_counts[commit.kst_date] += 1

        solved_dates = set(daily_counts)
        primary_language = language_counts.most_common(1)[0][0] if language_counts else "Unknown"
        stats.append(
            MemberStats(
                friend=friend,
                commits=commits,
                score=score,
                level_counts={level: level_counts.get(level, 0) for level in range(6)},
                language_counts=dict(language_counts),
                primary_language=primary_language,
                total_commits=len(commits),
                week_commits=sum(1 for commit in commits if week_start <= commit.kst_date <= week_end),
                month_commits=sum(1 for commit in commits if month_start <= commit.kst_date <= today),
                max_daily_commits=max(daily_counts.values(), default=0),
                current_streak=calculate_current_streak(solved_dates, today),
                longest_streak=calculate_longest_streak(solved_dates),
                last_solved_at=max((commit.committed_at for commit in commits), default=None),
            )
        )

    if language_cache_changed:
        save_language_cache(language_cache)

    return stats


def calculate_current_streak(solved_dates: set[date], today: date) -> int:
    streak = 0
    cursor = today
    while cursor in solved_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def calculate_longest_streak(solved_dates: set[date]) -> int:
    if not solved_dates:
        return 0

    longest = 0
    current = 0
    previous: date | None = None
    for solved_date in sorted(solved_dates):
        if previous is None or solved_date == previous + timedelta(days=1):
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous = solved_date
    return longest


def sorted_weekly(stats: list[MemberStats]) -> list[MemberStats]:
    return sorted(stats, key=lambda item: (-item.week_commits, item.friend.name))


def sorted_ranking(stats: list[MemberStats]) -> list[MemberStats]:
    return sorted(stats, key=lambda item: (-item.score, -item.total_commits, item.friend.name))


def rank_lookup(stats: list[MemberStats]) -> dict[str, int]:
    return {item.friend.name: rank for rank, item in enumerate(sorted_ranking(stats), start=1)}


def build_weekly_ranking_message(stats: list[MemberStats], target_date: date | None = None) -> str:
    week_start, week_end = get_kst_week_range(target_date)
    lines = [f"**🏁 금주의 랭킹 ({week_start} ~ {week_end})**"]
    for rank, item in enumerate(sorted_weekly(stats), start=1):
        lines.append(f"{rank}등 {item.friend.name}: {item.week_commits} COMMIT")
    return "\n".join(lines)


def build_overall_ranking_message(stats: list[MemberStats]) -> str:
    lines = ["**🏆 종합 랭킹**"]
    for rank, item in enumerate(sorted_ranking(stats), start=1):
        lines.append(
            f"{rank}등 {item.friend.name}{rank_tag(rank)} / {item.primary_language}: "
            f"{item.score}점 / {item.total_commits} COMMIT"
        )
    return "\n".join(lines)


def build_ranking_board_message(stats: list[MemberStats]) -> str:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    ranked = sorted_ranking(stats)
    left_width = max(
        (display_width(f"{rank_label(rank)} {item.friend.name}{rank_tag(rank)}") for rank, item in enumerate(ranked, start=1)),
        default=0,
    )
    lines = [
        "**프로그래머스 랭킹판**",
        f"업데이트: {now}",
        "",
        "종합 랭킹",
        "------------------------------------",
    ]
    for rank, item in enumerate(ranked, start=1):
        left = f"{rank_label(rank)} {item.friend.name}{rank_tag(rank)}"
        padding = " " * (left_width - display_width(left))
        lines.append(f"**{left}**{padding} / {item.primary_language} / {item.score}점 / {item.total_commits} COMMIT")

    lines.append("------------------------------------")
    return "\n".join(lines)


def build_member_stats_message(stats: list[MemberStats], name: str) -> str:
    ranks = rank_lookup(stats)
    target = next((item for item in stats if item.friend.name == name), None)
    if target is None:
        known_names = ", ".join(item.friend.name for item in stats)
        return f"찾을 수 없는 이름입니다: {name}\n가능한 이름: {known_names}"

    rank = ranks[target.friend.name]
    last_solved = "-"
    if target.last_solved_at:
        last_solved = target.last_solved_at.astimezone(KST).strftime("%Y-%m-%d %H:%M")

    lines = [
        f"**📊 {target.friend.name} 스탯**",
        f"종합 순위: {rank}등 {rank_tag(rank)}",
        f"주 언어: {target.primary_language}",
        f"현재 점수: {target.score}점",
        f"총 누적: {target.total_commits} COMMIT",
        f"이번 주: {target.week_commits} COMMIT",
        f"이번 달: {target.month_commits} COMMIT",
        f"하루 최대: {target.max_daily_commits} COMMIT",
        f"현재 연속: {target.current_streak}일",
        f"최장 연속: {target.longest_streak}일",
        f"마지막 풀이: {last_solved}",
        "",
        "난이도 분포",
    ]
    for level in range(6):
        lines.append(f"Lv.{level}: {target.level_counts.get(level, 0)}문제")
    if target.language_counts:
        lines.extend(["", "언어 분포"])
        for language, count in sorted(target.language_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"{language}: {count}문제")
    return "\n".join(lines)


def build_summary_message(target_date: date, results: list[SummaryResult], stats: list[MemberStats] | None = None) -> str:
    total = sum(result.count for result in results if result.error is None)
    solved = sum(1 for result in results if result.error is None and result.count > 0)
    lines = [
        f"**📌 {target_date.isoformat()} 프로그래머스 기록**",
        f"완료 {solved}/{len(results)}명 · 총 {total}문제",
        "",
    ]

    for result in results:
        if result.error:
            lines.append(f"⚠️ {result.friend.name}: 확인 실패")
        elif result.count > 0:
            lines.append(f"✅ {result.friend.name}: {result.count} COMMIT")
        else:
            lines.append(f"❌ {result.friend.name}: 0 COMMIT")

    if stats:
        lines.extend(["", build_weekly_ranking_message(stats, target_date), "", build_overall_ranking_message(stats)])

    return "\n".join(lines)


def update_ranking_board(session: requests.Session, friends: list[Friend], dry_run: bool = False) -> None:
    stats = build_stats(session, friends)
    content = build_ranking_board_message(stats)

    if dry_run or not ranking_webhook_url():
        print(content)
        return

    ranking_state = load_ranking_state()
    message_id = ranking_state.get("message_id")
    if message_id and edit_discord_webhook_message(message_id, content):
        print(f"ranking board updated: {message_id}")
        return

    new_message_id = create_discord_webhook_message(content)
    save_ranking_state(new_message_id)
    print(f"ranking board created: {new_message_id}")


def run_poll(dry_run: bool = False, skip_board: bool = False) -> int:
    friends = load_friends()
    session = github_session()
    target_date = datetime.now(KST).date()
    since_utc, until_utc = get_kst_date_range(target_date)
    state, state_exists = load_state()
    changed = False

    for friend in friends:
        try:
            commits = solution_commits(fetch_commits(session, friend, since_utc, until_utc))
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
        if new_commits:
            try:
                total_count = len(solution_commits(fetch_commits(session, friend)))
            except Exception as exc:
                print(f"{friend.name} 총 누적 확인 실패: {exc}", file=sys.stderr)
                total_count = len(set(state.get(repo_key, []) + current_shas))

            for index, commit in enumerate(new_commits, start=1):
                send_discord_message(
                    format_commit_notification(friend, commit, total_count - len(new_commits) + index),
                    dry_run=dry_run,
                )

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

    if not skip_board:
        update_ranking_board(session, friends, dry_run=dry_run)

    return 0


def run_summary(target_date: date | None = None, dry_run: bool = False, once: bool = False) -> int:
    friends = sorted(load_friends(), key=lambda friend: friend.name)
    session = github_session()
    if target_date is None:
        target_date = datetime.now(KST).date() - timedelta(days=1)
    target_date_key = target_date.isoformat()

    if once:
        sent_dates = load_summary_state()
        if target_date_key in sent_dates:
            print(f"{target_date_key} summary already sent")
            return 0

    since_utc, until_utc = get_kst_date_range(target_date)
    results: list[SummaryResult] = []
    for friend in friends:
        try:
            commits = solution_commits(fetch_commits(session, friend, since_utc, until_utc))
            results.append(SummaryResult(friend=friend, count=len(commits)))
        except Exception as exc:
            print(f"{friend.name} 확인 실패: {exc}", file=sys.stderr)
            results.append(SummaryResult(friend=friend, error=str(exc)))

    stats: list[MemberStats] | None = None
    try:
        stats = build_stats(session, friends, today=target_date)
    except Exception as exc:
        print(f"랭킹 계산 실패: {exc}", file=sys.stderr)

    send_discord_message(build_summary_message(target_date, results, stats), dry_run=dry_run)
    if once and not dry_run:
        sent_dates = load_summary_state()
        sent_dates.add(target_date_key)
        save_summary_state(sent_dates)
    return 0


def run_weekly(dry_run: bool = False) -> int:
    target_date = datetime.now(KST).date()
    session = github_session()
    stats = build_stats(session, load_friends(), today=target_date)
    send_discord_message(build_weekly_ranking_message(stats, target_date), dry_run=dry_run)
    return 0


def run_ranking(dry_run: bool = False) -> int:
    session = github_session()
    stats = build_stats(session, load_friends())
    send_discord_message(build_overall_ranking_message(stats), dry_run=dry_run)
    return 0


def run_board(dry_run: bool = False) -> int:
    session = github_session()
    update_ranking_board(session, load_friends(), dry_run=dry_run)
    return 0


def run_stats(name: str, dry_run: bool = False) -> int:
    session = github_session()
    stats = build_stats(session, load_friends())
    send_discord_message(build_member_stats_message(stats, name), dry_run=dry_run)
    return 0


def main() -> int:
    args = parse_args()

    try:
        if args.command == "poll":
            return run_poll(dry_run=args.dry_run, skip_board=args.skip_board)
        if args.command == "summary":
            return run_summary(target_date=args.date, dry_run=args.dry_run, once=args.once)
        if args.command == "weekly":
            return run_weekly(dry_run=args.dry_run)
        if args.command == "ranking":
            return run_ranking(dry_run=args.dry_run)
        if args.command == "board":
            return run_board(dry_run=args.dry_run)
        if args.command == "stats":
            return run_stats(name=args.name, dry_run=args.dry_run)
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
