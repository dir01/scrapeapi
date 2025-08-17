package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log"
	"time"

	scrapeapi "github.com/dir01/scrapeapi/sdk/go"
	jsonschema "github.com/invopop/jsonschema"
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

// generateTraceID creates a random 32-character hex trace ID following W3C trace context format
func generateTraceID() string {
	bytes := make([]byte, 16) // 16 bytes = 32 hex characters
	if _, err := rand.Read(bytes); err != nil {
		log.Printf("Warning: failed to generate random trace ID: %v", err)
		// Fallback to timestamp-based ID
		return fmt.Sprintf("%032d", time.Now().UnixNano())
	}
	return hex.EncodeToString(bytes)
}

func main() {
	// Generate a stable trace ID for this session - randomized only once at startup
	traceID := generateTraceID()
	fmt.Printf("🔍 Session trace ID: %s\n", traceID)

	// Create client
	client := scrapeapi.NewClient("http://scrapeapi.cluster-int.dir01.org")
	// client := scrapeapi.NewClient("http://127.0.0.1:8080")
	
	// Set trace ID header for all requests in this session
	client.SetHeader("X-Trace-ID", traceID)

	// Example 1: Smart scraper with JSON Schema
	schema := jsonschema.Reflect(&ParsedJobsResponse{})

	fmt.Printf("schema: %v", schema)

	req := &scrapeapi.ScrapeRequest{
		Graph:      "smart",
		UserPrompt: "This page contains a list of job offering ads. It is CRUCIAL that we get accurate information on all the jobs in the list. Please include ad title, company name, salary expectations, commitment, and geo restrictions",
		WebsiteURL: scrapeapi.String("https://remotive.com/remote-jobs/software-dev"),
		// WebsiteURL:   scrapeapi.String("https://weworkremotely.com/categories/remote-back-end-programming-jobs"),
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

	// Method 1: Start and wait
	result, err := client.ScrapeAndWait(context.Background(), req, scrapeapi.WithPollInterval(2*time.Second))
	if err != nil {
		log.Fatalf("Scrape failed: %v", err)
	}

	fmt.Printf("✅ Scrape completed!\n")
	fmt.Printf("Status: %s\n", result.Status)
	fmt.Printf("Result: %v\n", result.Result)

	// Method 2: Manual polling (alternative approach)
	fmt.Println("\n🔄 Alternative: Manual polling example...")

	startResp, err := client.StartScrape(context.Background(), req)
	if err != nil {
		log.Fatalf("Failed to start scrape: %v", err)
	}

	fmt.Printf("Started job: %s\n", startResp.RequestID)

	// Poll until completion
	for {
		pollResp, err := client.GetScrape(context.Background(), startResp.RequestID)
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
