package main

import (
	"context"
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

func main() {
	// Create client
	client := scrapeapi.NewClient("http://localhost:8080")

	// Example 1: Smart scraper with JSON Schema
	schema := jsonschema.Reflect(&ParsedJobsResponse{})

	fmt.Printf("schema: %v", schema)

	req := &scrapeapi.ScrapeRequest{
		Graph:        "smart",
		UserPrompt:   "This page contains a list of job offering ads. It is CRUCIAL that we get accurate information on all the jobs in the list. Please include ad title, company name, salary expectations, commitment, and geo restrictions",
		WebsiteURL:   scrapeapi.String("https://weworkremotely.com/categories/remote-back-end-programming-jobs"),
		OutputSchema: schema,
		LLM: &scrapeapi.LLMConfig{
			Model:       "openai/gpt-4o-mini",
			Temperature: 0,
		},
		Headless:   true,
		Verbose:    true,
		TimeoutSec: 120,
		MaxResults: scrapeapi.Int(20),
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
