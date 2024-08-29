import asyncio
import datetime
import logging
import time
from functools import cached_property

import bittensor
from compute_horde.base_requests import BaseRequest
from compute_horde.executor_class import ExecutorClass
from compute_horde.miner_client.base import (
    AbstractMinerClient,
    UnsupportedMessageReceived,
)
from compute_horde.mv_protocol import miner_requests, validator_requests
from compute_horde.mv_protocol.miner_requests import (
    BaseMinerRequest,
    UnauthorizedError,
    V0AcceptJobRequest,
    V0DeclineJobRequest,
    V0ExecutorFailedRequest,
    V0ExecutorManifestRequest,
    V0ExecutorReadyRequest,
    V0JobFailedRequest,
    V0JobFinishedRequest,
    V0MachineSpecsRequest,
)
from compute_horde.mv_protocol.validator_requests import (
    AuthenticationPayload,
    JobFinishedReceiptPayload,
    JobStartedReceiptPayload,
    V0AuthenticateRequest,
    V0JobFinishedReceiptRequest,
    V0JobStartedReceiptRequest,
)
from compute_horde.transport import AbstractTransport, WSTransport
from compute_horde.utils import MachineSpecs
from django.conf import settings

from compute_horde_validator.validator.models import (
    SystemEvent,
)

logger = logging.getLogger(__name__)


class MinerClient(AbstractMinerClient):
    def __init__(
        self,
        miner_hotkey: str,
        miner_address: str,
        miner_port: int,
        job_uuid: str,
        my_keypair: bittensor.Keypair,
        transport: AbstractTransport | None = None,
    ) -> None:
        self.job_uuid = job_uuid

        self.miner_hotkey = miner_hotkey
        self.miner_address = miner_address
        self.miner_port = miner_port
        self.my_keypair = my_keypair

        loop = asyncio.get_running_loop()
        self.miner_manifest = loop.create_future()
        self.online_executor_count = 0

        # for waiting on miner responses (replaces JobState)
        self.miner_ready_or_declining_future = loop.create_future()
        self.miner_ready_or_declining_timestamp: int = 0
        self.miner_finished_or_failed_future = loop.create_future()
        self.miner_finished_or_failed_timestamp: int = 0
        self.miner_machine_specs: MachineSpecs | None = None  # what should we do with this???

        name = f"{miner_hotkey}({miner_address}:{miner_port})"
        transport = transport or WSTransport(name, self.miner_url())
        super().__init__(name, transport)

    @cached_property
    def my_hotkey(self):
        return self.my_keypair.ss58_address

    def miner_url(self) -> str:
        return (
            f"ws://{self.miner_address}:{self.miner_port}/v0.1/validator_interface/{self.my_hotkey}"
        )

    def accepted_request_type(self) -> type[BaseRequest]:
        return BaseMinerRequest

    def incoming_generic_error_class(self) -> type[BaseRequest]:
        return miner_requests.GenericError

    def outgoing_generic_error_class(self) -> type[BaseRequest]:
        return validator_requests.GenericError

    async def notify_generic_error(self, msg: BaseRequest):
        # TODO: make empty
        msg = f"Received error message from miner {self.miner_name}: {msg.model_dump_json()}"
        await SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).acreate(
            type=SystemEvent.EventType.MINER_SYNTHETIC_JOB_FAILURE,
            subtype=SystemEvent.EventSubType.GENERIC_ERROR,
            long_description=msg,
            data={},
        )

    async def notify_unauthorized_error(self, msg: UnauthorizedError):
        # TODO: make empty
        msg = f"Unauthorized in {self.miner_name}: {msg.code}, details: {msg.details}"
        await SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).acreate(
            type=SystemEvent.EventType.MINER_SYNTHETIC_JOB_FAILURE,
            subtype=SystemEvent.EventSubType.UNAUTHORIZED,
            long_description=msg,
            data={},
        )

    async def handle_manifest_request(self, msg: V0ExecutorManifestRequest) -> None:
        # TODO: make empty
        try:
            self.miner_manifest.set_result(msg.manifest)
        except asyncio.InvalidStateError:
            logger.warning(f"Received manifest from {msg} but future was already set")

    async def handle_machine_specs_request(self, msg: V0MachineSpecsRequest) -> None:
        # TODO: make empty
        self.miner_machine_specs = msg.specs

    async def handle_message(self, msg: BaseRequest) -> None:
        if isinstance(msg, self.incoming_generic_error_class()):
            logger.warning(
                f"Received error message from miner {self.miner_name}: {msg.model_dump_json()}"
            )
            await self.notify_generic_error(msg)
            return
        elif isinstance(msg, UnauthorizedError):
            logger.error(f"Unauthorized in {self.miner_name}: {msg.code}, details: {msg.details}")
            await self.notify_unauthorized_error(msg)
            return
        elif isinstance(msg, V0ExecutorManifestRequest):
            await self.handle_manifest_request(msg)
            return

        if isinstance(msg, V0AcceptJobRequest):
            logger.info(f"Miner {self.miner_name} accepted job")
        elif isinstance(
            msg, V0DeclineJobRequest | V0ExecutorFailedRequest | V0ExecutorReadyRequest
        ):
            try:
                self.miner_ready_or_declining_future.set_result(msg)
                self.miner_ready_or_declining_timestamp = time.time()
            except asyncio.InvalidStateError:
                logger.warning(f"Received {msg} from {self.miner_name} but future was already set")
        elif isinstance(msg, V0JobFailedRequest | V0JobFinishedRequest):
            try:
                self.miner_finished_or_failed_future.set_result(msg)
                self.miner_finished_or_failed_timestamp = time.time()
            except asyncio.InvalidStateError:
                logger.warning(f"Received {msg} from {self.miner_name} but future was already set")
        elif isinstance(msg, V0MachineSpecsRequest):
            await self.handle_machine_specs_request(msg)
        else:
            raise UnsupportedMessageReceived(msg)

    def generate_authentication_message(self):
        payload = AuthenticationPayload(
            validator_hotkey=self.my_hotkey,
            miner_hotkey=self.miner_hotkey,
            timestamp=int(time.time()),
        )
        return V0AuthenticateRequest(
            payload=payload, signature=f"0x{self.my_keypair.sign(payload.blob_for_signing()).hex()}"
        )

    def generate_job_started_receipt_message(
        self,
        job_uuid: str,
        miner_hotkey: str,
        executor_class: ExecutorClass,
        accepted_timestamp: float,
        max_timeout: int,
    ) -> V0JobStartedReceiptRequest:
        time_accepted = datetime.datetime.fromtimestamp(accepted_timestamp, datetime.UTC)
        receipt_payload = JobStartedReceiptPayload(
            job_uuid=job_uuid,
            miner_hotkey=miner_hotkey,
            validator_hotkey=self.my_hotkey,
            executor_class=executor_class,
            time_accepted=time_accepted,
            max_timeout=max_timeout,
        )
        return V0JobStartedReceiptRequest(
            payload=receipt_payload,
            signature=f"0x{self.my_keypair.sign(receipt_payload.blob_for_signing()).hex()}",
        )

    async def send_job_started_receipt_message(
        self,
        job_uuid: str,
        miner_hotkey: str,
        executor_class: ExecutorClass,
        accepted_timestamp: float,
        max_timeout: int,
    ):
        try:
            receipt_message = self.generate_job_started_receipt_message(
                job_uuid,
                miner_hotkey,
                executor_class,
                accepted_timestamp,
                max_timeout,
            )
            await self.send_model(
                receipt_message,
                error_event_callback=self.get_job_error_event_callback(job_uuid, miner_hotkey),
            )
            logger.debug(f"Sent job started receipt for {job_uuid}")
        except Exception as e:
            comment = f"Failed to send job started receipt to miner {self.miner_name} for job {job_uuid}: {e}"
            logger.warning(comment)
            await self.save_receipt_event(
                job_uuid=job_uuid,
                miner_hotkey=miner_hotkey,
                subtype=SystemEvent.EventSubType.RECEIPT_SEND_ERROR,
                long_description=comment,
            )

    def generate_job_finished_receipt_message(
        self,
        job_uuid: str,
        miner_hotkey: str,
        started_timestamp: float,
        time_took_seconds: float,
        score: float,
    ) -> V0JobFinishedReceiptRequest:
        time_started = datetime.datetime.fromtimestamp(started_timestamp, datetime.UTC)
        receipt_payload = JobFinishedReceiptPayload(
            job_uuid=job_uuid,
            miner_hotkey=miner_hotkey,
            validator_hotkey=self.my_hotkey,
            time_started=time_started,
            time_took_us=int(time_took_seconds * 1_000_000),
            score_str=f"{score:.6f}",
        )
        return V0JobFinishedReceiptRequest(
            payload=receipt_payload,
            signature=f"0x{self.my_keypair.sign(receipt_payload.blob_for_signing()).hex()}",
        )

    async def send_job_finished_receipt_message(
        self,
        job_uuid: str,
        miner_hotkey: str,
        started_timestamp: float,
        time_took_seconds: float,
        score: float,
    ):
        try:
            receipt_message = self.generate_job_finished_receipt_message(
                job_uuid, miner_hotkey, started_timestamp, time_took_seconds, score
            )
            await self.send_model(
                receipt_message,
                error_event_callback=self.get_job_error_event_callback(job_uuid, miner_hotkey),
            )
            logger.debug(f"Sent job finished receipt for {job_uuid}")
        except Exception as e:
            comment = f"Failed to send job finished receipt to miner {self.miner_name} for job {job_uuid}: {e}"
            logger.warning(comment)
            await self.save_receipt_event(
                job_uuid=job_uuid,
                miner_hotkey=miner_hotkey,
                subtype=SystemEvent.EventSubType.RECEIPT_SEND_ERROR,
                long_description=comment,
            )

    def get_job_error_event_callback(self, job_uuid: str, miner_hotkey: str):
        async def handle_send_error_event(msg: str):
            # TODO: make empty
            await SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).acreate(
                type=SystemEvent.EventType.MINER_ORGANIC_JOB_FAILURE,
                subtype=SystemEvent.EventSubType.MINER_SEND_ERROR,
                long_description=msg,
                data={"job_uuid": job_uuid, "miner_hotkey": miner_hotkey},
            )

        return handle_send_error_event

    async def save_receipt_event(
        self, job_uuid: str, miner_hotkey: str, subtype: str, long_description: str
    ):
        data = {"job_uuid": job_uuid, "miner_hotkey": miner_hotkey}
        await SystemEvent.objects.using(settings.DEFAULT_DB_ALIAS).acreate(
            type=SystemEvent.EventType.RECEIPT_FAILURE,
            subtype=subtype,
            long_description=long_description,
            data=data,
        )

    async def connect(self) -> None:
        await super().connect()
        await self.transport.send(self.generate_authentication_message().model_dump_json())
