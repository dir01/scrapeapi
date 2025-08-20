package main

import (
	"context"
	"crypto/rand"
	"fmt"
	"log"
	"os"
	"time"

	scrapeapi "github.com/dir01/scrapeapi/sdk/go"
	jsonschema "github.com/invopop/jsonschema"
	"github.com/joho/godotenv"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/trace"
	oteltrace "go.opentelemetry.io/otel/trace"
)

type ParsedJob struct {
	Title           string `json:"title" jsonschema:"title"`
	CompanyName     string `json:"company_name" jsonschema:"company_name"`
	Location        string `json:"location" jsonschema:"location, description=Where to company is headquatered. This is not necessary where the potential employee must reside"`
	IsFeatured      bool   `json:"is_featured" jsonschema:"is_featured"`
	CommitmentType  string `json:"commitment_type" jsonschema:"commitment_type,enum=part_time,enum=full_type,enum=freelance,enum=contract,enum=intern"`
	Salary          string `json:"salary" jsonschema:"free-form description of salary expectations"`
	GeoRestrictions string `json:"geo_restrictions" jsonschema:"geo_restrictions,example=Anywhere in the world,example=USA,example=Argentina|Mexico|Colombia"`
	Age             string `json:"age" jsonschema:"age,description=How long ago was job posted,example=new,example=1d,example=8d`
}

type ParsedJobsResponse struct {
	Jobs []ParsedJob `json:"jobs" jsonschema:"jobs"`
}

func main() {
	// Load environment variables
	err := godotenv.Load()
	if err != nil {
		log.Printf("Warning: Error loading .env file: %v", err)
	}

	// Initialize OpenTelemetry with custom ID generator
	cleanup := initOpenTelemetry()
	defer cleanup()

	// Create a tracer
	tracer := otel.Tracer("scrapeapi-example")

	// Start a root span - the custom ID generator will create trace ID starting with "55555"
	ctx, rootSpan := tracer.Start(context.Background(), "scraping-session")
	defer rootSpan.End()

	fmt.Printf("🔍 EXAMPLE: Starting scraping session\n")
	fmt.Printf("🔍 EXAMPLE: Trace ID: %s (should start with 55555)\n", rootSpan.SpanContext().TraceID().String())
	fmt.Printf("🔍 EXAMPLE: Root span valid: %v\n", rootSpan.SpanContext().IsValid())
	fmt.Printf("🔍 EXAMPLE: Root span sampled: %v\n", rootSpan.SpanContext().IsSampled())

	// Create client (now with automatic OpenTelemetry instrumentation)
	baseURL := os.Getenv("SCRAPEAPI_BASE_URL")
	if baseURL == "" {
		baseURL = "http://127.0.0.1:8080" // fallback
	}

	targetURL := os.Getenv("SCRAPE_TARGET_URL")
	if targetURL == "" {
		targetURL = "https://remotive.com/remote-jobs/software-dev" // fallback
	}

	client := scrapeapi.NewClient(baseURL)

	// Example 1: Smart scraper with JSON Schema
	schema := jsonschema.Reflect(&ParsedJobsResponse{})

	fmt.Printf("schema: %v", schema)

	req := &scrapeapi.ScrapeRequest{
		Graph:        "smart",
		UserPrompt:   "This page contains a list of job offering ads. It is CRUCIAL that we get accurate information on all the jobs in the list. Please include ad title, company name, salary expectations, commitment, and geo restrictions",
		WebsiteURL:   scrapeapi.String(targetURL),
		OutputSchema: schema,
		LLM: &scrapeapi.LLMConfig{
			Model:       "openai/gpt-4o-mini",
			Temperature: scrapeapi.Float64(0), // Use helper to ensure 0.0 is serialized
		},
		Headless:   true,
		Verbose:    true,
		TimeoutSec: 60 * 6,
		MaxResults: scrapeapi.Int(20),
		LoaderKwargs: map[string]interface{}{
			"timeout": 1000 * 60 * 5,
		},
	}

	fmt.Println("🚀 Starting scrape job...")

	// Method 1: Start and wait (using traced context)
	result, err := client.ScrapeAndWait(ctx, req, scrapeapi.WithPollInterval(2*time.Second))
	if err != nil {
		log.Fatalf("Scrape failed: %v", err)
	}

	fmt.Printf("✅ Scrape completed!\n")
	fmt.Printf("Status: %s\n", result.Status)
	fmt.Printf("Result: %v\n", result.Result)

	// Method 2: Manual polling (alternative approach)
	fmt.Println("\n🔄 Alternative: Manual polling example...")

	startResp, err := client.StartScrape(ctx, req)
	if err != nil {
		log.Fatalf("Failed to start scrape: %v", err)
	}

	fmt.Printf("Started job: %s\n", startResp.RequestID)

	// Poll until completion
	for {
		pollResp, err := client.GetScrape(ctx, startResp.RequestID)
		if err != nil {
			log.Fatalf("Failed to poll: %v", err)
		}

		fmt.Printf("Status: %s\n", pollResp.Status)

		if pollResp.Status == "completed" {
			fmt.Printf("✅ Success! Result: %v\n", pollResp.Result)
			break
		} else if pollResp.Status == "failed" {
			log.Fatalf("❌ Scraping failed: %s", pollResp.Error)
		}

		time.Sleep(2 * time.Second)
	}
}

// generateCustomTraceID creates a trace ID with first 5 digits as "55555"
func generateCustomTraceID() oteltrace.TraceID {
	// Create 16 bytes for trace ID
	bytes := make([]byte, 16)

	// Fill with random data
	if _, err := rand.Read(bytes); err != nil {
		log.Fatalf("Failed to generate random bytes: %v", err)
	}

	// Set first 5 hex digits to "55555" (first 2.5 bytes)
	// 0x55, 0x55, 0x50 gives us "555550..." which starts with "55555"
	bytes[0] = 0x55
	bytes[1] = 0x55
	bytes[2] = 0x50 // This makes the 5th hex digit a "5"

	var traceID oteltrace.TraceID
	copy(traceID[:], bytes)
	return traceID
}

// customIDGenerator generates trace IDs starting with "55555"
type customIDGenerator struct{}

func (g customIDGenerator) NewIDs(ctx context.Context) (oteltrace.TraceID, oteltrace.SpanID) {
	return generateCustomTraceID(), g.NewSpanID(ctx, oteltrace.TraceID{})
}

func (g customIDGenerator) NewSpanID(ctx context.Context, traceID oteltrace.TraceID) oteltrace.SpanID {
	var spanID oteltrace.SpanID
	_, _ = rand.Read(spanID[:])
	return spanID
}

// initOpenTelemetry initializes OpenTelemetry without console output
func initOpenTelemetry() func() {
	// Create a trace provider with custom ID generator and sampling
	tp := trace.NewTracerProvider(
		trace.WithIDGenerator(customIDGenerator{}),
		trace.WithSampler(trace.AlwaysSample()), // Ensure all traces are sampled
	)

	// Set the global trace provider
	otel.SetTracerProvider(tp)

	// Set up propagation
	otel.SetTextMapPropagator(propagation.TraceContext{})

	// Return a cleanup function
	return func() {
		if err := tp.Shutdown(context.Background()); err != nil {
			log.Printf("Error shutting down tracer provider: %v", err)
		}
	}
}
