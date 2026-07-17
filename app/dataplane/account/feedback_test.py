from __future__ import annotations

import unittest

from app.control.account.enums import FeedbackKind
from app.dataplane.account import AccountDirectory
from app.dataplane.account.selector import current_strategy, set_strategy
from app.dataplane.account.table import AccountRuntimeTable
from app.dataplane.shared.enums import StatusId


def _runtime_table() -> AccountRuntimeTable:
    table = AccountRuntimeTable()
    table._append_slot(
        token="console-token",
        pool_id=0,
        status_id=int(StatusId.ACTIVE),
        quota_auto=0,
        quota_fast=30,
        quota_expert=0,
        quota_heavy=-1,
        quota_grok_4_3=-1,
        quota_console=20,
        total_auto=0,
        total_fast=30,
        total_expert=0,
        total_heavy=0,
        total_grok_4_3=0,
        total_console=20,
        window_auto=0,
        window_fast=86_400,
        window_expert=0,
        window_heavy=0,
        window_grok_4_3=0,
        window_console=3_600,
        reset_auto=0,
        reset_fast=0,
        reset_expert=0,
        reset_heavy=0,
        reset_grok_4_3=0,
        reset_console=0,
        health=1.0,
        last_use_s=0,
        last_fail_s=0,
        fail_count=0,
        tags=[],
    )
    return table


class AccountDirectoryConsoleFeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.previous_strategy = current_strategy()
        set_strategy("quota")

    async def asyncTearDown(self) -> None:
        set_strategy(self.previous_strategy)

    async def test_console_429_lowers_health_without_zeroing_quota(self) -> None:
        table = _runtime_table()
        directory = AccountDirectory(repository=None)  # type: ignore[arg-type]
        directory._table = table

        await directory.feedback(
            "console-token",
            FeedbackKind.RATE_LIMITED,
            5,
            now_s_val=100,
        )

        self.assertEqual(table.quota_console_by_idx[0], 20)
        self.assertLess(table.health_by_idx[0], 1.0)
        self.assertEqual(table.last_fail_at_by_idx[0], 100)

    async def test_non_console_429_keeps_authoritative_zeroing(self) -> None:
        table = _runtime_table()
        directory = AccountDirectory(repository=None)  # type: ignore[arg-type]
        directory._table = table

        await directory.feedback(
            "console-token",
            FeedbackKind.RATE_LIMITED,
            1,
            now_s_val=100,
        )

        self.assertEqual(table.quota_fast_by_idx[0], 0)


if __name__ == "__main__":
    unittest.main()
