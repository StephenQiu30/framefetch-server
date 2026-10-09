"""Application-side names and bounds for durable RabbitMQ command queues."""

from dataclasses import dataclass

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractQueue


@dataclass(frozen=True, slots=True)
class DurableQueueTopology:
    queue: str
    routing_key: str
    message_ttl_ms: int = 86_400_000
    max_length: int = 10_000

    def __post_init__(self) -> None:
        for value in (self.queue, self.routing_key):
            if not value or value != value.strip():
                raise ValueError("RabbitMQ topology names cannot be blank")
        if self.message_ttl_ms <= 0 or self.max_length <= 0:
            raise ValueError("RabbitMQ queue bounds must be positive")

    @property
    def dead_queue(self) -> str:
        return f"{self.queue}.dead"

    @property
    def dead_routing_key(self) -> str:
        return self.dead_queue


@dataclass(frozen=True, slots=True)
class RabbitMqTopology:
    exchange: str = "video.events"
    download_queue: str = "video.download"
    download_routing_key: str = "download.requested"
    report_queue: str = "video.analysis-report"
    report_routing_key: str = "analysis.report.publish.requested"
    message_ttl_ms: int = 86_400_000
    max_length: int = 10_000
    import_queue: str = "video.import"
    import_routing_key: str = "content.import.verify.requested"

    def __post_init__(self) -> None:
        names = (
            self.exchange,
            self.download_queue,
            self.download_routing_key,
            self.report_queue,
            self.report_routing_key,
            self.import_queue,
            self.import_routing_key,
        )
        if any(not value or value != value.strip() for value in names):
            raise ValueError("RabbitMQ topology names cannot be blank")
        if self.message_ttl_ms <= 0 or self.max_length <= 0:
            raise ValueError("RabbitMQ queue bounds must be positive")

    @property
    def dead_exchange(self) -> str:
        return f"{self.exchange}.dead"

    @property
    def dead_queue(self) -> str:
        return f"{self.download_queue}.dead"

    @property
    def dead_routing_key(self) -> str:
        return f"{self.download_queue}.dead"

    @property
    def durable_queues(self) -> tuple[DurableQueueTopology, ...]:
        return (
            DurableQueueTopology(
                self.download_queue,
                self.download_routing_key,
                self.message_ttl_ms,
                self.max_length,
            ),
            DurableQueueTopology(
                self.report_queue,
                self.report_routing_key,
                self.message_ttl_ms,
                self.max_length,
            ),
            DurableQueueTopology(
                self.import_queue,
                self.import_routing_key,
                self.message_ttl_ms,
                self.max_length,
            ),
        )

    @property
    def download(self) -> DurableQueueTopology:
        return self.durable_queues[0]

    @property
    def report(self) -> DurableQueueTopology:
        return self.durable_queues[1]

    @property
    def imports(self) -> DurableQueueTopology:
        return self.durable_queues[2]


async def declare_durable_queue(
    channel: AbstractChannel, topology: RabbitMqTopology, binding: DurableQueueTopology
) -> AbstractQueue:
    """Idempotently apply one business queue, its bounds and dead-letter binding."""
    exchange = await channel.declare_exchange(
        topology.exchange, type=ExchangeType.TOPIC, durable=True
    )
    dead_exchange = await channel.declare_exchange(
        topology.dead_exchange, type=ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(
        binding.queue,
        durable=True,
        arguments={
            "x-message-ttl": binding.message_ttl_ms,
            "x-max-length": binding.max_length,
            "x-dead-letter-exchange": topology.dead_exchange,
            "x-dead-letter-routing-key": binding.dead_routing_key,
        },
    )
    dead_queue = await channel.declare_queue(
        binding.dead_queue,
        durable=True,
        arguments={"x-max-length": binding.max_length},
    )
    await queue.bind(exchange, routing_key=binding.routing_key)
    await dead_queue.bind(dead_exchange, routing_key=binding.dead_routing_key)
    return queue
