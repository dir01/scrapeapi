import os
import logging
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    PeriodicExportingMetricReader,
    ConsoleMetricExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor

logger = logging.getLogger(__name__)

# Global tracer and meter instances
tracer: Optional[trace.Tracer] = None
meter: Optional[metrics.Meter] = None

# Metrics instruments
request_counter: Optional[metrics.Counter] = None
request_duration: Optional[metrics.Histogram] = None
scraping_success_counter: Optional[metrics.Counter] = None
scraping_duration: Optional[metrics.Histogram] = None
schema_validation_counter: Optional[metrics.Counter] = None
queue_size_gauge: Optional[metrics.UpDownCounter] = None


def get_resource() -> Resource:
    """Create OpenTelemetry resource with service information."""
    return Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "scrapeapi"),
            "service.version": os.getenv("OTEL_SERVICE_VERSION", "1.0.0"),
            "service.environment": os.getenv("OTEL_ENVIRONMENT", "development"),
            "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "scraping"),
        }
    )


def setup_tracing() -> None:
    """Initialize OpenTelemetry tracing."""
    resource = get_resource()
    provider = TracerProvider(resource=resource)

    # Configure exporters based on environment
    exporter_type = os.getenv("OTEL_EXPORTER_TYPE", "").lower()

    if exporter_type == "otlp":
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        exporter = OTLPSpanExporter(endpoint=endpoint)
        logger.info(f"Using OTLP exporter with endpoint: {endpoint}")
    elif exporter_type == "jaeger":
        endpoint = os.getenv(
            "OTEL_EXPORTER_JAEGER_ENDPOINT", "http://localhost:14268/api/traces"
        )
        exporter = JaegerExporter(endpoint=endpoint)
        logger.info(f"Using Jaeger exporter with endpoint: {endpoint}")
        exporter = ConsoleSpanExporter()
        logger.info("Using Console exporter for tracing")

    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)
    global tracer
    tracer = trace.get_tracer(__name__)


def setup_metrics() -> None:
    """Initialize OpenTelemetry metrics."""
    resource = get_resource()

    # Configure metric exporters
    exporter_type = os.getenv("OTEL_EXPORTER_TYPE", "").lower()

    if exporter_type == "otlp":
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        exporter = OTLPMetricExporter(endpoint=endpoint)
        logger.info(f"Using OTLP metric exporter with endpoint: {endpoint}")
    elif exporter_type == "console":
        exporter = ConsoleMetricExporter()
        logger.info("Using Console exporter for metrics")
    else:
        # No exporter - metrics collection disabled
        logger.info("No metric exporter configured - metrics disabled")
        return

    reader = PeriodicExportingMetricReader(
        exporter=exporter,
        export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "10000")),
    )

    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    global meter
    meter = metrics.get_meter(__name__)

    # Initialize metric instruments
    setup_metric_instruments()


def setup_metric_instruments() -> None:
    """Create metric instruments for the application."""
    global request_counter, request_duration, scraping_success_counter
    global scraping_duration, schema_validation_counter, queue_size_gauge

    if not meter:
        return

    # HTTP request metrics
    request_counter = meter.create_counter(
        name="scrapeapi_requests_total",
        description="Total number of HTTP requests",
        unit="1",
    )

    request_duration = meter.create_histogram(
        name="scrapeapi_request_duration_seconds",
        description="HTTP request duration in seconds",
        unit="s",
    )

    # Scraping operation metrics
    scraping_success_counter = meter.create_counter(
        name="scrapeapi_scraping_operations_total",
        description="Total number of scraping operations",
        unit="1",
    )

    scraping_duration = meter.create_histogram(
        name="scrapeapi_scraping_duration_seconds",
        description="Scraping operation duration in seconds",
        unit="s",
    )

    # Schema validation metrics
    schema_validation_counter = meter.create_counter(
        name="scrapeapi_schema_validations_total",
        description="Total number of schema validations",
        unit="1",
    )

    # Queue metrics
    queue_size_gauge = meter.create_up_down_counter(
        name="scrapeapi_queue_size",
        description="Current number of jobs in queue",
        unit="1",
    )


def setup_auto_instrumentation(app) -> None:
    """Setup automatic instrumentation for FastAPI and other libraries."""
    # FastAPI instrumentation
    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=server_request_hook,
        client_request_hook=client_request_hook,
        excluded_urls=os.getenv("OTEL_EXCLUDED_URLS", ""),
    )

    # HTTP client instrumentation
    HTTPXClientInstrumentor().instrument()

    # Asyncio instrumentation
    AsyncioInstrumentor().instrument()

    logger.info("Auto-instrumentation setup completed")


def server_request_hook(span: trace.Span, scope: dict) -> None:
    """Custom hook for incoming FastAPI requests."""
    if span and span.is_recording():
        # Add custom attributes
        if "path" in scope:
            span.set_attribute("http.route", scope["path"])

        # Add request size if available
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            span.set_attribute("http.request.size", int(content_length))


def client_request_hook(span: trace.Span, scope: dict, message: dict) -> None:
    """Custom hook for outgoing HTTP requests."""
    if span and span.is_recording():
        # Add custom attributes for outgoing requests
        span.set_attribute("component", "http_client")


def initialize_telemetry(app) -> None:
    """Initialize all OpenTelemetry components."""
    # Check if telemetry is enabled
    if os.getenv("OTEL_ENABLED", "true").lower() != "true":
        logger.info("OpenTelemetry disabled via OTEL_ENABLED environment variable")
        return

    logger.info("Initializing OpenTelemetry...")

    try:
        setup_tracing()
        setup_metrics()
        setup_auto_instrumentation(app)
        logger.info("OpenTelemetry initialization completed successfully")
    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        # Don't fail the application if telemetry setup fails
        pass


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    if tracer is None:
        return trace.get_tracer(__name__)
    return tracer


def get_meter() -> metrics.Meter:
    """Get the global meter instance."""
    if meter is None:
        return metrics.get_meter(__name__)
    return meter
