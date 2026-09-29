from __future__ import annotations

import asyncio

import pytest
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.provider_credential_lease import ProviderCredentialLocks


@pytest.mark.asyncio
async def test_one_credential_is_held_by_one_operation_at_a_time() -> None:
    locks = ProviderCredentialLocks()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with locks.hold("douyin.com", "session"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()
    # A non-waiting caller is refused while the credential is busy.
    with pytest.raises(RunnerFailure) as busy:
        async with locks.hold("douyin.com", "session"):
            pass
    assert busy.value.code == "provider_session_unavailable"
    # Other credentials are independent.
    async with locks.hold("bilibili.com", "session"):
        pass

    waiter_entered = asyncio.Event()

    async def waiter() -> None:
        async with locks.hold("douyin.com", "session", wait_seconds=5):
            waiter_entered.set()

    queued = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    assert not waiter_entered.is_set()
    release.set()
    await asyncio.wait_for(asyncio.gather(task, queued), 5)
    assert waiter_entered.is_set()


@pytest.mark.asyncio
async def test_waiting_caller_times_out_and_lock_survives_cancellation() -> None:
    locks = ProviderCredentialLocks()
    async with locks.hold("x.com", "session"):
        with pytest.raises(RunnerFailure):
            async with locks.hold("x.com", "session", wait_seconds=0.05):
                pass

    async def cancelled_holder() -> None:
        async with locks.hold("x.com", "session"):
            await asyncio.Event().wait()

    task = asyncio.create_task(cancelled_holder())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    # Cancellation releases the credential for the next operation.
    async with locks.hold("x.com", "session"):
        pass
