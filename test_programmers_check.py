from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import programmers_check
from programmers_check import CommitInfo, Friend


class RunPollTests(unittest.TestCase):
    def test_manual_commit_uses_configured_title_and_level(self) -> None:
        friend = Friend(name="박강호", owner="ohgnakrap9290", repo="programmers-study")

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                manual_path = Path(".state/manual_commits.json")
                manual_path.parent.mkdir()
                manual_path.write_text(
                    json.dumps(
                        [
                            {
                                "name": "박강호",
                                "date": "2026-06-16",
                                "count": 1,
                                "level": 0,
                                "title": "공백으로 구분하기 1",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                commits = programmers_check.load_manual_commits(friend)

                self.assertEqual(len(commits), 1)
                self.assertEqual(programmers_check.problem_title(commits[0], friend), "공백으로 구분하기 1")
                self.assertEqual(programmers_check.problem_level(commits[0], friend), "Lv. 000000")
            finally:
                os.chdir(previous_cwd)

    def test_manual_report_resends_seen_commit_without_changing_state(self) -> None:
        friend = Friend(name="테스터", owner="owner", repo="repo")
        commit = CommitInfo(
            sha="already-seen",
            message="[level 1] Title: 테스트 문제, Time: 1 ms -BaekjoonHub",
            url="https://example.com/commit",
            committed_at=datetime.now(timezone.utc),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                state_path = Path(".state/seen_commits.json")
                state_path.parent.mkdir()
                original_state = {friend.repo_key: [commit.sha]}
                state_path.write_text(json.dumps(original_state), encoding="utf-8")

                with (
                    patch.object(programmers_check, "load_friends", return_value=[friend]),
                    patch.object(programmers_check, "github_session"),
                    patch.object(programmers_check, "fetch_commits", return_value=[commit]),
                    patch.object(programmers_check, "fetch_solution_commits", return_value=[commit]),
                    patch.object(
                        programmers_check,
                        "commit_problem_key",
                        return_value=("path:problem", False),
                    ),
                    patch.object(programmers_check, "send_discord_message") as send_message,
                ):
                    result = programmers_check.run_poll(report_today=True, skip_board=True)

                self.assertEqual(result, 0)
                send_message.assert_called_once()
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), original_state)
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
