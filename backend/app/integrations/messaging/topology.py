"""Application-side names and bounds for durable RabbitMQ command queues."""

from dataclasses import dataclass


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
    exchange: str
    download_queue: str
    download_routing_key: str
    analysis_queue: str = "video.analysis"
    analysis_routing_key: str = "analysis.requested"
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
            self.analysis_queue,
            self.analysis_routing_key,
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
                self.analysis_queue,
                self.analysis_routing_key,
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
    def analysis(self) -> DurableQueueTopology:
        return self.durable_queues[1]

    @property
    def download(self) -> DurableQueueTopology:
        return self.durable_queues[0]

    @property
    def report(self) -> DurableQueueTopology:
        return self.durable_queues[2]

    @property
    def imports(self) -> DurableQueueTopology:
        return self.durable_queues[3]
