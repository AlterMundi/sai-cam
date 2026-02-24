"""
Kafka Publisher for SAI-Cam

Publishes IPFS CID notifications to a Kafka topic using kafka-python-ng.
The kafka module is imported lazily so the service can start without it.
"""

import json
import time


class KafkaPublisher:
    """Publishes CID-ready events to a Kafka topic."""

    def __init__(self, config: dict, logger):
        """
        Initialize the Kafka publisher.

        Args:
            config: kafka sub-dict from the main config.
                    Expected keys:
                      enabled             - bool (default False)
                      bootstrap_servers   - list or comma-separated string
                      topic               - target topic name
                      security_protocol   - e.g. 'PLAINTEXT', 'SASL_SSL' (optional)
                      sasl_mechanism      - e.g. 'PLAIN', 'SCRAM-SHA-256' (optional)
                      sasl_plain_username - (optional)
                      sasl_plain_password - (optional)
            logger: standard logging.Logger (or RateLimitedLogger)
        """
        self.logger = logger
        self._producer = None
        self.enabled = False

        if not config.get("enabled", False):
            self.logger.info("KafkaPublisher: kafka.enabled=false, Kafka disabled")
            return

        # Lazy import — kafka-python-ng is an optional dependency
        try:
            from kafka import KafkaProducer  # noqa: F401 (checked below)
            self._KafkaProducer = KafkaProducer
        except ImportError:
            self.logger.error(
                "kafka.enabled=true but kafka-python-ng not installed — Kafka disabled"
            )
            return

        self.topic = config.get("topic", "sai-cam-cids")

        # Build producer kwargs
        bootstrap = config.get("brokers", config.get("bootstrap_servers", "localhost:9092"))
        if isinstance(bootstrap, str):
            bootstrap = [s.strip() for s in bootstrap.split(",")]

        producer_kwargs = {
            "bootstrap_servers": bootstrap,
            "acks": 1,
            "retries": 5,
            "retry_backoff_ms": 1000,
            "linger_ms": 100,
            "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
            "key_serializer": lambda k: k.encode("utf-8") if k else None,
        }

        security_protocol = config.get("security_protocol")
        if security_protocol:
            producer_kwargs["security_protocol"] = security_protocol

        sasl_mechanism = config.get("sasl_mechanism")
        if sasl_mechanism:
            producer_kwargs["sasl_mechanism"] = sasl_mechanism

        sasl_username = config.get("sasl_username") or config.get("sasl_plain_username")
        if sasl_username:
            producer_kwargs["sasl_plain_username"] = sasl_username

        sasl_password = config.get("sasl_password") or config.get("sasl_plain_password")
        if sasl_password:
            producer_kwargs["sasl_plain_password"] = sasl_password

        try:
            self._producer = self._KafkaProducer(**producer_kwargs)
            self.enabled = True
            self.logger.info(
                f"KafkaPublisher initialised: bootstrap={bootstrap} topic={self.topic}"
            )
        except Exception as e:
            self.logger.error(f"KafkaPublisher: failed to create producer: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def publish_cid(self, cid: str, metadata: dict) -> bool:
        """Publish a CID-ready event to Kafka.

        Args:
            cid: IPFS CID string returned by IPFSClient.add_image.
            metadata: Dict with keys expected by consumers:
                        device_id, camera_id, filename, timestamp (ISO-8601),
                        epoch_ms, location, image_size_bytes, content_type

        Returns:
            True if the message was enqueued successfully, False otherwise.
        """
        if not self.enabled or self._producer is None:
            return False

        message = {
            "ipfs_cid": cid,
            "device_id": metadata.get("device_id", ""),
            "camera_id": metadata.get("camera_id", ""),
            "filename": metadata.get("filename", ""),
            "timestamp": metadata.get("timestamp", ""),
            "epoch_ms": metadata.get("epoch_ms", int(time.time() * 1000)),
            "location": metadata.get("location", {}),
            "image_size_bytes": metadata.get("image_size_bytes", 0),
            "content_type": metadata.get("content_type", "image/jpeg"),
        }

        key = metadata.get("device_id") or None

        try:
            self._producer.send(self.topic, key=key, value=message)
            self.logger.debug(
                f"KafkaPublisher: enqueued CID={cid} device={key} topic={self.topic}"
            )
            return True
        except Exception as e:
            self.logger.error(f"KafkaPublisher: failed to publish CID={cid}: {e}", exc_info=True)
            return False

    def flush(self, timeout: int = 5):
        """Flush pending messages. Call before shutdown.

        Args:
            timeout: Max seconds to wait for in-flight messages to be sent.
        """
        if not self.enabled or self._producer is None:
            return
        try:
            self._producer.flush(timeout=timeout)
            self.logger.debug("KafkaPublisher: flush complete")
        except Exception as e:
            self.logger.error(f"KafkaPublisher: flush error: {e}", exc_info=True)
