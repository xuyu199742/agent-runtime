import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.errors import Conflict
from app.persistence.database import (
    AgentDefinition,
    EffectRecord,
    Message,
    ModelConfig,
    Run,
    RunTraceEvent,
    Session,
)
from app.persistence.repositories.effects import EffectStore
from app.persistence.repositories.runs import RunRepository, end_run
from app.runtime.errors import EffectIdempotencyConflictError


async def _running_run(factory, worker_id: str) -> str:
    suffix = uuid4().hex
    async with factory() as db:
        model = ModelConfig(name=f"effect-model-{suffix}", provider="openai", model_name="fake")
        db.add(model)
        await db.flush()
        agent = AgentDefinition(name=f"effect-agent-{suffix}", model_id=model.id)
        db.add(agent)
        await db.flush()
        session = Session(agent_id=agent.id, user_id=f"effect-user-{suffix}")
        db.add(session)
        await db.flush()
        message = Message(
            session_id=session.id, user_id=session.user_id, role="user", content="ticket"
        )
        db.add(message)
        await db.flush()
        run = Run(
            session_id=session.id,
            message_id=message.id,
            status="RUNNING",
            lease_owner=worker_id,
            lease_until=datetime.now(UTC) + timedelta(seconds=45),
        )
        db.add(run)
        await db.commit()
        return run.id


async def test_effect_identity_is_unique_within_provider_operation_scope():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    key = f"ticket-{uuid4().hex}"
    try:
        async with factory() as db:
            model = ModelConfig(name=f"effect-model-{key}", provider="openai", model_name="fake")
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"effect-agent-{key}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="effect-test-user")
            db.add(session)
            await db.flush()
            message = Message(
                session_id=session.id, user_id=session.user_id, role="user", content="create ticket"
            )
            db.add(message)
            await db.flush()
            run = Run(session_id=session.id, message_id=message.id)
            db.add(run)
            await db.flush()
            run_id = run.id
            db.add(
                EffectRecord(
                    provider_namespace="ticket-account-a",
                    operation_name="ticket.create",
                    business_key=key,
                    contract_version=1,
                    request_hash="a" * 64,
                    status="PREPARED",
                    origin_run_id=run_id,
                )
            )
            await db.commit()
        async with factory() as db:
            db.add(
                EffectRecord(
                    provider_namespace="ticket-account-a",
                    operation_name="ticket.create",
                    business_key=key,
                    contract_version=1,
                    request_hash="a" * 64,
                    status="PREPARED",
                    origin_run_id=run_id,
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()
        async with factory() as db:
            db.add(
                EffectRecord(
                    provider_namespace="ticket-account-b",
                    operation_name="ticket.create",
                    business_key=key,
                    contract_version=1,
                    request_hash="a" * 64,
                    status="PREPARED",
                    origin_run_id=run_id,
                )
            )
            await db.commit()
    finally:
        await engine.dispose()


async def test_only_one_run_can_claim_dispatch_for_shared_business_key():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    key = f"ticket-{uuid4().hex}"
    try:
        first_run = await _running_run(factory, "worker-a")
        second_run = await _running_run(factory, "worker-b")
        store = EffectStore(factory)
        first = await store.prepare(
            first_run, "worker-a", "account-a", "ticket.create", key, 1, "a" * 64
        )
        second = await store.prepare(
            second_run, "worker-b", "account-a", "ticket.create", key, 1, "a" * 64
        )
        assert first.id == second.id
        assert await store.claim_dispatch(first.id, first_run, "worker-a")
        assert not await store.claim_dispatch(first.id, second_run, "worker-b")
        async with factory() as db:
            row = await db.get(EffectRecord, first.id)
            assert row.status == "DISPATCHED"
            assert row.dispatch_run_id == first_run
            events = list(
                await db.scalars(
                    select(RunTraceEvent)
                    .where(RunTraceEvent.run_id == first_run)
                    .order_by(RunTraceEvent.sequence)
                )
            )
            assert [(event.event_type, event.ref_id) for event in events] == [
                ("effect.prepared", first.id),
                ("effect.dispatched", first.id),
            ]
    finally:
        await engine.dispose()


async def test_same_business_key_with_different_request_is_rejected():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    key = f"ticket-{uuid4().hex}"
    try:
        first_run = await _running_run(factory, "worker-a")
        second_run = await _running_run(factory, "worker-b")
        store = EffectStore(factory)
        await store.prepare(first_run, "worker-a", "account-a", "ticket.create", key, 1, "a" * 64)
        with pytest.raises(EffectIdempotencyConflictError):
            await store.prepare(
                second_run, "worker-b", "account-a", "ticket.create", key, 1, "b" * 64
            )
    finally:
        await engine.dispose()


async def test_admin_retry_rejects_run_with_unresolved_external_effect():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory, "worker-a")
        store = EffectStore(factory)
        effect = await store.prepare(
            run_id, "worker-a", "account-a", "ticket.create", f"ticket-{uuid4().hex}", 1, "a" * 64
        )
        assert await store.claim_dispatch(effect.id, run_id, "worker-a")
        async with factory() as db:
            assert await end_run(db, run_id, "worker-a", "FAILED", "EFFECT_UNCERTAIN")
        async with factory() as db:
            with pytest.raises(Conflict, match="未定案"):
                await RunRepository(db).retry(run_id)
    finally:
        await engine.dispose()


async def test_uncertain_effect_is_reconciled_and_replayed_without_dispatch():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    key = f"ticket-{uuid4().hex}"
    try:
        first_run = await _running_run(factory, "worker-a")
        second_run = await _running_run(factory, "worker-b")
        store = EffectStore(factory)
        effect = await store.prepare(
            first_run, "worker-a", "account-a", "ticket.create", key, 1, "a" * 64
        )
        assert await store.claim_dispatch(effect.id, first_run, "worker-a")
        await store.advance(effect.id, first_run, "worker-a", "unknown")
        assert await store.begin_reconcile(effect.id, second_run, "worker-b")
        await store.advance(
            effect.id,
            second_run,
            "worker-b",
            "observed_success",
            result_content='{"ticket_id":"T-1"}',
            external_ref="T-1",
        )
        replay = await store.prepare(
            second_run, "worker-b", "account-a", "ticket.create", key, 1, "a" * 64
        )
        assert replay.status == "SUCCEEDED"
        assert replay.result_content == '{"ticket_id":"T-1"}'
        assert not await store.claim_dispatch(effect.id, second_run, "worker-b")
    finally:
        await engine.dispose()
