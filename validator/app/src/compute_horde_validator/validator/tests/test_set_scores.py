import asyncio
import uuid
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from compute_horde.executor_class import DEFAULT_EXECUTOR_CLASS
from django.utils.timezone import now

from compute_horde_validator.validator.models import (
    Miner,
    SyntheticJob,
    SyntheticJobBatch,
    SystemEvent,
    Weights,
)
from compute_horde_validator.validator.tasks import reveal_scores, set_scores

from .helpers import (
    NUM_NEURONS,
    MockHyperparameters,
    MockMetagraph,
    MockSubtensor,
    check_system_events,
    throw_error,
)


def setup_db():
    for i in range(NUM_NEURONS):
        Miner.objects.update_or_create(hotkey=f"hotkey_{i}")

    job_batch = SyntheticJobBatch.objects.create(
        started_at=now(),
        accepting_results_until=now(),
        scored=False,
    )
    for i in range(NUM_NEURONS):
        SyntheticJob.objects.create(
            batch=job_batch,
            score=0,
            job_uuid=uuid.uuid4(),
            miner=Miner.objects.get(hotkey=f"hotkey_{i}"),
            miner_address="ignore",
            miner_address_ip_version=4,
            miner_port=9999,
            executor_class=DEFAULT_EXECUTOR_CLASS,
            status=SyntheticJob.Status.COMPLETED,
        )


@patch("bittensor.subtensor", lambda *args, **kwargs: MockSubtensor())
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__no_batches_found(settings):
    set_scores()
    assert SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 0


@patch("bittensor.subtensor", lambda *args, **kwargs: MockSubtensor())
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight_success(settings):
    setup_db()
    set_scores()
    assert SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 1
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_SUCCESS,
        SystemEvent.EventSubType.SET_WEIGHTS_SUCCESS,
        1,
    )


@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_FAILURE_BACKOFF", 0)
@patch(
    "bittensor.subtensor",
    lambda *args, **kwargs: MockSubtensor(mocked_set_weights=lambda: (False, "error")),
)
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight_failure(settings):
    setup_db()
    set_scores()
    assert SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 2
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.SET_WEIGHTS_ERROR,
        1,
    )
    # end of retries system event
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE, SystemEvent.EventSubType.GIVING_UP, 1
    )


def set_weights_succeed_third_time():
    global weight_set_attempts
    weight_set_attempts += 1
    return (False, "error") if weight_set_attempts < 3 else (True, "")


@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 3)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_FAILURE_BACKOFF", 0)
@patch(
    "bittensor.subtensor",
    lambda *args, **kwargs: MockSubtensor(mocked_set_weights=set_weights_succeed_third_time),
)
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight_eventual_success(settings):
    global weight_set_attempts
    weight_set_attempts = 0
    setup_db()
    set_scores()
    assert SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 3
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.SET_WEIGHTS_ERROR,
        2,
    )
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_SUCCESS,
        SystemEvent.EventSubType.SET_WEIGHTS_SUCCESS,
        1,
    )


@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_FAILURE_BACKOFF", 0)
@patch("bittensor.subtensor", lambda *args, **kwargs: MockSubtensor(mocked_set_weights=throw_error))
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight_exception(settings):
    setup_db()
    set_scores()
    assert SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 2
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.WRITING_TO_CHAIN_GENERIC_ERROR,
        1,
    )
    # end of retries system event
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE, SystemEvent.EventSubType.GIVING_UP, 1
    )


@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_FAILURE_BACKOFF", 0)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_HARD_TTL", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_TTL", 1)
@patch("bittensor.subtensor", lambda *args, **kwargs: MockSubtensor())
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight_timeout(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False  # to make it timeout
    setup_db()
    set_scores()
    assert SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 2
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.WRITING_TO_CHAIN_TIMEOUT,
        1,
    )
    # end of retries system event
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE, SystemEvent.EventSubType.GIVING_UP, 1
    )


@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_FAILURE_BACKOFF", 0)
@patch("bittensor.subtensor", lambda *args, **kwargs: MockSubtensor(mocked_metagraph=throw_error))
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__metagraph_fetch_exception(settings):
    setup_db()
    set_scores()
    assert SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 2
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.SUBTENSOR_CONNECTIVITY_ERROR,
        1,
    )
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE, SystemEvent.EventSubType.GENERIC_ERROR, 1
    )
    # did not retry
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE, SystemEvent.EventSubType.GIVING_UP, 0
    )


@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_FAILURE_BACKOFF", 0)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_HARD_TTL", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_TTL", 1)
@patch(
    "bittensor.subtensor",
    lambda *args, **kwargs: MockSubtensor(
        hyperparameters=MockHyperparameters(
            commit_reveal_weights_enabled=True,
            commit_reveal_weights_interval=20,
        ),
    ),
)
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight__commit(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    setup_db()
    set_scores()
    assert (
        SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).count() == 1
    ), SystemError.objects.all()
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_SUCCESS,
        SystemEvent.EventSubType.COMMIT_WEIGHTS_SUCCESS,
        1,
    )
    assert Weights.objects.count() == 1


@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 1)
@patch(
    "bittensor.subtensor",
    lambda *args, **kwargs: MockSubtensor(
        hyperparameters=MockHyperparameters(
            commit_reveal_weights_enabled=True,
            commit_reveal_weights_interval=20,
        ),
    ),
)
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight__double_commit_failure(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    setup_db()
    set_scores()

    weights = Weights.objects.all()
    assert len(weights) == 1
    assert weights[0].revealed_at is None

    setup_db()
    set_scores()
    assert Weights.objects.count() == 1
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.COMMIT_WEIGHTS_UNREVEALED_ERROR,
        1,
    )


mocked_metagraph = MockMetagraph()


@patch(
    "bittensor.subtensor",
    lambda *args, **kwargs: MockSubtensor(
        mocked_metagraph=lambda: mocked_metagraph,
        hyperparameters=MockHyperparameters(
            commit_reveal_weights_enabled=True,
            commit_reveal_weights_interval=20,
        ),
    ),
)
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
def test_set_scores__set_weight__reveal(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    setup_db()
    set_scores()

    last_weights = Weights.objects.order_by("-id").first()
    assert last_weights
    assert last_weights.revealed_at is None

    reveal_scores()
    last_weights.refresh_from_db()
    assert last_weights.revealed_at is None
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.REVEAL_WEIGHTS_ERROR,
        0,  # nothing happened because it's too early to reveal weights
    )

    # wait for the interval to pass
    class _MockBlock:
        def item(self) -> int:
            return 1020

    mocked_metagraph.block = _MockBlock()

    from bittensor import subtensor

    assert subtensor().metagraph(netuid=1).block.item() == 1020
    reveal_scores()

    last_weights.refresh_from_db()
    assert last_weights.revealed_at is not None
    check_system_events(
        SystemEvent.EventType.WEIGHT_SETTING_SUCCESS,
        SystemEvent.EventSubType.REVEAL_WEIGHTS_SUCCESS,
        1,
    )


# ! This test is the last because otherwise it breaks other tests
# ! (probably it doesn't release lock properly, so other tests cannot set scores)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_ATTEMPTS", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_FAILURE_BACKOFF", 0)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_HARD_TTL", 1)
@patch("compute_horde_validator.validator.tasks.WEIGHT_SETTING_TTL", 1)
@patch("bittensor.subtensor", lambda *args, **kwargs: MockSubtensor())
@pytest.mark.django_db(databases=["default", "default_alias"], transaction=True)
@pytest.mark.asyncio
async def test_set_scores__multiple_starts(settings):
    # to ensure the other tasks will be run at the same time
    settings.CELERY_TASK_ALWAYS_EAGER = False
    await sync_to_async(setup_db)()

    tasks = [sync_to_async(set_scores, thread_sensitive=False)() for _ in range(5)]
    await asyncio.gather(*tasks)

    assert await SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).acount() == 2
    await sync_to_async(check_system_events)(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE,
        SystemEvent.EventSubType.WRITING_TO_CHAIN_TIMEOUT,
        1,
    )
    # end of retries system event
    await sync_to_async(check_system_events)(
        SystemEvent.EventType.WEIGHT_SETTING_FAILURE, SystemEvent.EventSubType.GIVING_UP, 1
    )
