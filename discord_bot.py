from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import discord
from discord import app_commands

from programmers_check import (
    KST,
    ConfigError,
    SummaryResult,
    build_member_stats_message,
    build_overall_ranking_message,
    build_stats,
    build_summary_message,
    build_weekly_ranking_message,
    fetch_commits,
    format_commit_notification,
    get_kst_date_range,
    github_session,
    load_friends,
    load_state,
    parse_kst_date,
    save_state,
    solution_commits,
    truncate_discord_content,
)


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")


class ProgrammersBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        if DISCORD_GUILD_ID:
            guild = discord.Object(id=int(DISCORD_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()


bot = ProgrammersBot()


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def manual_poll_messages() -> list[str]:
    friends = load_friends()
    session = github_session()
    target_date = datetime.now(KST).date()
    since_utc, until_utc = get_kst_date_range(target_date)
    state, state_exists = load_state()
    messages: list[str] = []
    changed = False

    for friend in friends:
        try:
            commits = solution_commits(fetch_commits(session, friend, since_utc, until_utc))
        except Exception as exc:
            messages.append(f"⚠️ {friend.name} 확인 실패: {exc}")
            continue

        repo_key = friend.repo_key
        current_shas = [commit.sha for commit in commits if commit.sha]
        seen = set(state.get(repo_key, []))

        if not state_exists or repo_key not in state:
            state[repo_key] = current_shas
            changed = True
            messages.append(f"{friend.name}: 상태 초기화 완료")
            continue

        new_commits = [commit for commit in reversed(commits) if commit.sha and commit.sha not in seen]
        if not new_commits:
            continue

        total_count = len(solution_commits(fetch_commits(session, friend)))
        for index, commit in enumerate(new_commits, start=1):
            messages.append(format_commit_notification(friend, commit, total_count - len(new_commits) + index))

        state[repo_key] = list(dict.fromkeys(current_shas + state.get(repo_key, [])))[:500]
        changed = True

    if changed:
        save_state(state)

    return messages or ["새 커밋이 없습니다."]


def manual_summary_message(date_text: str | None) -> str:
    friends = sorted(load_friends(), key=lambda friend: friend.name)
    session = github_session()
    target_date = parse_kst_date(date_text) if date_text else datetime.now(KST).date() - timedelta(days=1)
    since_utc, until_utc = get_kst_date_range(target_date)

    results: list[SummaryResult] = []
    for friend in friends:
        try:
            commits = solution_commits(fetch_commits(session, friend, since_utc, until_utc))
            results.append(SummaryResult(friend=friend, count=len(commits)))
        except Exception as exc:
            results.append(SummaryResult(friend=friend, error=str(exc)))

    stats = build_stats(session, friends, today=target_date)
    return build_summary_message(target_date, results, stats)


def weekly_message() -> str:
    today = datetime.now(KST).date()
    session = github_session()
    return build_weekly_ranking_message(build_stats(session, load_friends(), today=today), today)


def ranking_message() -> str:
    session = github_session()
    return build_overall_ranking_message(build_stats(session, load_friends()))


def stats_message(name: str) -> str:
    session = github_session()
    return build_member_stats_message(build_stats(session, load_friends()), name)


async def send_long(interaction: discord.Interaction, content: str) -> None:
    await interaction.followup.send(truncate_discord_content(content))


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user}")


@bot.tree.command(name="help", description="사용 가능한 명령어를 보여줍니다.")
async def help_command(interaction: discord.Interaction) -> None:
    message = "\n".join(
        [
            "**PGCHECK 명령어**",
            "`/poll` - 지금 기준으로 새 풀이 커밋을 확인합니다.",
            "`/summary` - 밤 12시 요약과 같은 형식으로 전날 기록을 보여줍니다.",
            "`/summary date:2026-05-18` - 지정한 KST 날짜의 요약을 보여줍니다.",
            "`/weekly` - 이번 주 누적 COMMIT 랭킹을 보여줍니다.",
            "`/ranking` - 난이도 점수 기반 종합 랭킹을 보여줍니다.",
            "`/stats name:박강호` - 개인 스탯을 보여줍니다.",
        ]
    )
    await interaction.response.send_message(message)


@bot.tree.command(name="poll", description="새 Programmers 풀이 커밋을 지금 확인합니다.")
async def poll_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        messages = await run_blocking(manual_poll_messages)
    except ConfigError as exc:
        await interaction.followup.send(f"설정 오류: {exc}")
        return
    except Exception as exc:
        await interaction.followup.send(f"실행 오류: {exc}")
        return

    for message in messages:
        await send_long(interaction, message)


@bot.tree.command(name="summary", description="전날 또는 지정 날짜의 Programmers 요약을 보여줍니다.")
@app_commands.describe(date="KST 날짜. 예: 2026-05-18")
async def summary_command(interaction: discord.Interaction, date: str | None = None) -> None:
    await interaction.response.defer(thinking=True)
    try:
        message = await run_blocking(manual_summary_message, date)
    except ConfigError as exc:
        message = f"설정 오류: {exc}"
    except Exception as exc:
        message = f"실행 오류: {exc}"
    await send_long(interaction, message)


@bot.tree.command(name="weekly", description="이번 주 COMMIT 랭킹을 보여줍니다.")
async def weekly_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        message = await run_blocking(weekly_message)
    except Exception as exc:
        message = f"실행 오류: {exc}"
    await send_long(interaction, message)


@bot.tree.command(name="ranking", description="난이도 점수 기반 종합 랭킹을 보여줍니다.")
async def ranking_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        message = await run_blocking(ranking_message)
    except Exception as exc:
        message = f"실행 오류: {exc}"
    await send_long(interaction, message)


@bot.tree.command(name="stats", description="이름으로 개인 스탯을 보여줍니다.")
@app_commands.describe(name="멤버 이름. 예: 박강호")
async def stats_command(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(thinking=True)
    try:
        message = await run_blocking(stats_message, name)
    except Exception as exc:
        message = f"실행 오류: {exc}"
    await send_long(interaction, message)


def main() -> int:
    if not DISCORD_BOT_TOKEN:
        print("DISCORD_BOT_TOKEN 환경변수가 없습니다.", file=os.sys.stderr)
        return 2
    bot.run(DISCORD_BOT_TOKEN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
