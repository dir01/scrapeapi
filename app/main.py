import os
import json
import tempfile
import uuid
import asyncio
import time
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# scrapegraph-ai graphs
from scrapegraphai.graphs import SmartScraperGraph, SmartScraperMultiGraph, SearchGraph

# JSON Schema validation
import jsonschema  # type: ignore

# JSON Schema to Pydantic conversion
from json_schema_to_pydantic import create_model

# OpenTelemetry
from .telemetry import initialize_telemetry, get_tracer, get_meter
from .telemetry import (
    request_counter, request_duration, scraping_success_counter,
    scraping_duration, schema_validation_counter, queue_size_gauge
)

# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI(title="scrapegraph-ai HTTP API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenTelemetry
initialize_telemetry(app)

# In-memory job store (replace with Redis/DB if needed)
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = asyncio.Lock()

GraphName = Literal["smart", "multi", "search"]


class ScrapeRequest(BaseModel):
    graph: GraphName = Field(description="Which graph to run: smart|multi|search")
    user_prompt: str = Field(description="Instruction describing what to extract")

    # One of the following depending on graph type
    website_url: Optional[str] = None
    website_html: Optional[str] = None
    sources: Optional[List[str]] = None  # for multi; also used as fallback for smart

    # For SearchGraph
    search_query: Optional[str] = None
    max_results: Optional[int] = None

    # Structured output
    output_schema: Optional[Union[Dict[str, Any], str]] = Field(
        default=None,
        description=(
            "Desired output shape. Accepts either: \n"
            "1) JSON Schema object (dict), or\n"
            "2) JSON-like example string describing the structure (Pydantic-style example).\n"
            "If omitted, the LLM decides the shape."
        ),
    )

    # Graph/runtime config passthrough
    llm: Optional[Dict[str, Any]] = (
        None  # {model, api_key, api_base, temperature, provider-specific...}
    )
    headless: Optional[bool] = None
    loader_kwargs: Optional[Dict[str, Any]] = (
        None  # e.g., {"proxy": {"server": "http://host:port"}}
    )
    verbose: Optional[bool] = None
    additional_config: Optional[Dict[str, Any]] = None  # free-form extras

    # Execution
    timeout_sec: Optional[int] = Field(
        default=180, description="Server-side timeout for a job run"
    )


class StartResponse(BaseModel):
    request_id: str
    status: Literal["queued", "running", "completed", "failed"]
    graph: GraphName
    user_prompt: str
    website_url: Optional[str] = None
    sources: Optional[List[str]] = None
    result: Any = None
    error: str = ""


class PollResponse(StartResponse):
    pass


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/scrape", response_model=StartResponse)
async def start_scrape(req: ScrapeRequest):
    tracer = get_tracer()
    start_time = time.time()
    
    with tracer.start_as_current_span("scrape_request") as span:
        span.set_attribute("graph.type", req.graph)
        span.set_attribute("request.has_schema", req.output_schema is not None)
        if req.website_url:
            span.set_attribute("target.url", req.website_url)
        
        print(f"🔍 Received request with schema: {req.output_schema}")
        print(f"🔍 Schema type: {type(req.output_schema)}")
        
        # Validate JSON Schema if provided
        if req.output_schema is not None:
            if isinstance(req.output_schema, dict) and ("type" in req.output_schema or "$schema" in req.output_schema):
                with tracer.start_as_current_span("schema_validation") as schema_span:
                    schema_span.set_attribute("schema.type", req.output_schema.get("type", "unknown"))
                    
                    # Validate it's a valid JSON Schema
                    try:
                        jsonschema.Draft7Validator.check_schema(req.output_schema)
                        schema_span.set_attribute("validation.json_schema", True)
                    except jsonschema.SchemaError as e:
                        schema_span.set_attribute("validation.json_schema", False)
                        schema_span.record_exception(e)
                        if schema_validation_counter:
                            schema_validation_counter.add(1, {"status": "invalid_schema", "graph": req.graph})
                        raise HTTPException(
                            400, 
                            detail=f"Invalid JSON Schema: {str(e)}. Please provide a valid JSON Schema object with proper 'type' and 'properties' fields."
                        )
                    
                    # Test if it can be converted to Pydantic model
                    try:
                        test_model = create_model(req.output_schema)
                        schema_span.set_attribute("validation.pydantic_conversion", True)
                        print(f"✅ Schema validation passed, can create Pydantic model: {test_model}")
                        if schema_validation_counter:
                            schema_validation_counter.add(1, {"status": "valid", "graph": req.graph})
                    except Exception as e:
                        schema_span.set_attribute("validation.pydantic_conversion", False)
                        schema_span.record_exception(e)
                        if schema_validation_counter:
                            schema_validation_counter.add(1, {"status": "pydantic_conversion_failed", "graph": req.graph})
                        raise HTTPException(
                            400,
                            detail=f"JSON Schema cannot be converted to Pydantic model: {str(e)}. Please ensure your schema uses supported JSON Schema features."
                        )
    
        # Validate inputs quickly
        if req.graph == "smart":
            if not (
                req.website_url
                or req.website_html
                or (req.sources and len(req.sources) > 0)
            ):
                raise HTTPException(
                    400,
                    detail="smart graph requires website_url or website_html or sources[0]",
                )
        elif req.graph == "multi":
            if not (req.sources and len(req.sources) > 0):
                raise HTTPException(400, detail="multi graph requires sources: [url, ...]")
        elif req.graph == "search":
            # SearchGraph consumes the user_prompt; optional explicit search_query for clarity
            pass

        request_id = str(uuid.uuid4())
        job = {
            "request_id": request_id,
            "status": "queued",
            "graph": req.graph,
            "user_prompt": req.user_prompt,
            "website_url": req.website_url,
            "sources": req.sources,
            "result": None,
            "error": "",
        }

        span.set_attribute("job.request_id", request_id)
        
        async with JOBS_LOCK:
            JOBS[request_id] = job
            # Update queue size metric
            if queue_size_gauge:
                queue_size_gauge.add(1)

        # Record request metrics
        if request_counter:
            request_counter.add(1, {"graph": req.graph, "status": "queued"})
        
        # Run in background
        asyncio.create_task(_run_job(request_id, req))

        return StartResponse(**job)


@app.get("/v1/scrape/{request_id}", response_model=PollResponse)
async def get_scrape(request_id: str):
    job = JOBS.get(request_id)
    if not job:
        raise HTTPException(404, detail="request_id not found")
    return PollResponse(**job)


# Back-compat aliases (optional)
@app.post("/v1/smartscraper", response_model=StartResponse)
async def smartscraper_alias(req: ScrapeRequest):
    # Force smart if not set
    if req.graph != "smart":
        req.graph = "smart"
    return await start_scrape(req)


@app.get("/v1/smartscraper/{request_id}", response_model=PollResponse)
async def smartscraper_poll_alias(request_id: str):
    return await get_scrape(request_id)


# ----------------------------
# Internals
# ----------------------------
async def _run_job(request_id: str, req: ScrapeRequest):
    tracer = get_tracer()
    job_start_time = time.time()
    
    with tracer.start_as_current_span("scrape_job_execution") as job_span:
        job_span.set_attribute("job.request_id", request_id)
        job_span.set_attribute("job.graph", req.graph)
        job_span.set_attribute("job.has_schema", req.output_schema is not None)
        
        async with JOBS_LOCK:
            JOBS[request_id]["status"] = "running"
            # Update queue metrics
            if queue_size_gauge:
                queue_size_gauge.add(-1)  # Remove from queue
        
        if request_counter:
            request_counter.add(1, {"graph": req.graph, "status": "running"})

        try:
            # Build graph_config from request with sensible defaults
            graph_config: Dict[str, Any] = {
                "llm": {
                    "model": "openai/gpt-4o-mini",
                    "temperature": 0.0
                },
                "headless": True,
                "verbose": True,
                "loader_kwargs": {
                    "timeout": 30000
                }
            }
            
            # Override with user-provided values
            if req.llm:
                graph_config["llm"].update(req.llm)
            if req.headless is not None:
                graph_config["headless"] = req.headless
            if req.loader_kwargs:
                graph_config["loader_kwargs"].update(req.loader_kwargs)
            if req.verbose is not None:
                graph_config["verbose"] = req.verbose
            if req.max_results is not None:
                graph_config["max_results"] = req.max_results
            if req.additional_config:
                graph_config.update(req.additional_config)

            # Build the appropriate graph
            with tracer.start_as_current_span("graph_construction") as graph_span:
                graph_span.set_attribute("graph.type", req.graph)
                graph = _build_graph(req, graph_config)

            # Run with simple timeout
            with tracer.start_as_current_span("scrapegraph_execution") as exec_span:
                exec_span.set_attribute("execution.timeout_sec", req.timeout_sec or 180)
                if req.website_url:
                    exec_span.set_attribute("execution.target_url", req.website_url)
                
                print(f"🚀 Running graph...")
                execution_start = time.time()
                result = await _run_with_timeout(graph, req.timeout_sec)
                execution_duration = time.time() - execution_start
                
                exec_span.set_attribute("execution.duration_seconds", execution_duration)
                exec_span.set_attribute("execution.result_type", str(type(result)))
                
                print(f"✅ Graph completed with result type: {type(result)}")
                print(f"📄 Result: {result}")
                
                # Record execution metrics
                if scraping_duration:
                    scraping_duration.record(execution_duration, {"graph": req.graph, "status": "completed"})

            # If user provided a JSON Schema (dict with type/$schema), validate the result
            validation_errors: Optional[str] = None
            if (
                isinstance(req.output_schema, dict)
                and ("type" in req.output_schema or "$schema" in req.output_schema)
            ):
                with tracer.start_as_current_span("result_validation") as val_span:
                    try:
                        jsonschema.validate(result, req.output_schema)  # type: ignore
                        val_span.set_attribute("validation.success", True)
                        if schema_validation_counter:
                            schema_validation_counter.add(1, {"status": "result_valid", "graph": req.graph})
                    except Exception as ve:
                        validation_errors = str(ve)
                        val_span.set_attribute("validation.success", False)
                        val_span.set_attribute("validation.error", str(ve))
                        val_span.record_exception(ve)
                        if schema_validation_counter:
                            schema_validation_counter.add(1, {"status": "result_invalid", "graph": req.graph})

            # Calculate total job duration
            job_duration = time.time() - job_start_time
            job_span.set_attribute("job.duration_seconds", job_duration)
            job_span.set_attribute("job.status", "completed")

            # Save outcome
            async with JOBS_LOCK:
                JOBS[request_id]["status"] = "completed"
                JOBS[request_id]["result"] = {
                    "data": result,
                    "schema_validation": (
                        {"ok": True}
                        if not validation_errors
                        else {"ok": False, "error": validation_errors}
                    ),
                }

            # Record success metrics
            if scraping_success_counter:
                scraping_success_counter.add(1, {"graph": req.graph, "status": "completed"})

        except Exception as e:
            import traceback

            error_details = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            print(
                f"Job {request_id} failed with error: {error_details}"
            )  # Log to container output
            
            # Record exception in span
            job_span.record_exception(e)
            job_span.set_attribute("job.status", "failed")
            job_span.set_attribute("job.error", str(e))
            
            async with JOBS_LOCK:
                JOBS[request_id]["status"] = "failed"
                JOBS[request_id]["error"] = str(e)

            # Record failure metrics
            if scraping_success_counter:
                scraping_success_counter.add(1, {"graph": req.graph, "status": "failed"})
            if scraping_duration:
                job_duration = time.time() - job_start_time
                scraping_duration.record(job_duration, {"graph": req.graph, "status": "failed"})


def _build_graph(req: ScrapeRequest, graph_config: Dict[str, Any]):
    tracer = get_tracer()
    
    with tracer.start_as_current_span("pydantic_model_conversion") as conv_span:
        print(f"🏗️ Building {req.graph} graph with schema: {req.output_schema}")
        print(f"🏗️ Schema will be passed to scrapegraph-ai: {req.output_schema is not None}")
        
        # Convert JSON Schema to Pydantic model if needed
        schema_for_scrapegraph = req.output_schema
        if (
            isinstance(req.output_schema, dict) 
            and ("type" in req.output_schema or "$schema" in req.output_schema)
        ):
            conv_span.set_attribute("conversion.needed", True)
            conv_span.set_attribute("schema.type", req.output_schema.get("type", "unknown"))
            
            print(f"🔄 Converting JSON Schema to Pydantic model...")
            conversion_start = time.time()
            schema_for_scrapegraph = create_model(req.output_schema)
            conversion_duration = time.time() - conversion_start
            
            conv_span.set_attribute("conversion.duration_seconds", conversion_duration)
            conv_span.set_attribute("conversion.success", True)
            print(f"✅ Converted to Pydantic model: {schema_for_scrapegraph}")
        else:
            conv_span.set_attribute("conversion.needed", False)
    
    if req.graph == "smart":
        source: Optional[str] = req.website_url
        # Allow raw HTML by writing to a temp file if provided
        if req.website_html and not source:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
            tmp.write(req.website_html.encode("utf-8"))
            tmp.flush()
            tmp.close()
            source = tmp.name
        if not source and req.sources:
            source = req.sources[0]
        if not source:
            raise HTTPException(400, detail="smart graph requires a single source")
        print(f"🎯 Creating SmartScraperGraph with:")
        print(f"   prompt: {req.user_prompt}")
        print(f"   source: {source}")
        print(f"   schema: {schema_for_scrapegraph}")
        return SmartScraperGraph(
            prompt=req.user_prompt,
            source=source,
            config=graph_config,
            schema=schema_for_scrapegraph,
        )

    if req.graph == "multi":
        sources = req.sources or []
        if not sources:
            raise HTTPException(400, detail="multi graph requires sources list")
        return SmartScraperMultiGraph(
            prompt=req.user_prompt,
            source=sources,
            config=graph_config,
            schema=schema_for_scrapegraph,
        )

    if req.graph == "search":
        # SearchGraph expects a prompt; pass optional schema to structure results
        prompt = req.user_prompt
        return SearchGraph(prompt=prompt, config=graph_config, schema=schema_for_scrapegraph)

    raise HTTPException(400, detail=f"Unsupported graph: {req.graph}")


async def _run_with_timeout(graph_obj, timeout_sec: Optional[int]):
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, graph_obj.run), timeout=timeout_sec or 180
    )
