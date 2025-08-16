# ScrapeAPI Go SDK

A Go client library for the ScrapeAPI service that provides AI-powered web scraping with structured output.

## Installation

```bash
go get github.com/dir01/scrapeapi/sdk/go
go get github.com/invopop/jsonschema  # For automatic schema generation
```

## Quick Start

### Type-Safe Scraping with Go Structs

```go
package main

import (
    "context"
    "fmt"
    "log"
    "time"

    scrapeapi "github.com/dir01/scrapeapi/sdk/go"
    "github.com/invopop/jsonschema"
)

// Define your expected output structure
type JobListing struct {
    Title          string `json:"title" jsonschema:"description=Job title"`
    Company        string `json:"company" jsonschema:"description=Company name"`
    Salary         string `json:"salary" jsonschema:"description=Salary information"`
    Location       string `json:"location" jsonschema:"description=Job location"`
    CommitmentType string `json:"commitment_type" jsonschema:"enum=full_time,enum=part_time,enum=contract"`
}

type JobListings struct {
    Jobs []JobListing `json:"jobs" jsonschema:"description=List of job postings"`
}

func main() {
    client := scrapeapi.NewClient("http://localhost:8080")

    // Generate JSON Schema from Go struct
    schema := jsonschema.Reflect(&JobListings{})

    req := &scrapeapi.ScrapeRequest{
        Graph:        "smart",
        UserPrompt:   "Extract all job listings with title, company, salary, location and commitment type",
        WebsiteURL:   scrapeapi.String("https://example.com/jobs"),
        OutputSchema: schema,
        Headless:     true,
        Verbose:      true,
        TimeoutSec:   120,
    }

    // Scrape and wait for completion
    result, err := client.ScrapeAndWait(context.Background(), req, 
        scrapeapi.WithPollInterval(2*time.Second))
    if err != nil {
        log.Fatal(err)
    }

    fmt.Printf("✅ Scraped %d jobs\n", len(result.Result.(*JobListings).Jobs))
}
```

### Manual JSON Schema

```go
req := &scrapeapi.ScrapeRequest{
    Graph:      "smart",
    UserPrompt: "Extract product information",
    WebsiteURL: scrapeapi.String("https://example.com/products"),
    OutputSchema: map[string]interface{}{
        "type": "object",
        "properties": map[string]interface{}{
            "products": map[string]interface{}{
                "type": "array",
                "items": map[string]interface{}{
                    "type": "object",
                    "properties": map[string]interface{}{
                        "name":  map[string]interface{}{"type": "string"},
                        "price": map[string]interface{}{"type": "number"},
                    },
                },
            },
        },
    },
}
```

### Polling Example

```go
// Start scraping job
startResp, err := client.StartScrape(ctx, req)
if err != nil {
    log.Fatal(err)
}

fmt.Printf("Started job: %s\n", startResp.RequestID)

// Poll for completion
for {
    resp, err := client.GetScrape(ctx, startResp.RequestID)
    if err != nil {
        log.Fatal(err)
    }

    switch resp.Status {
    case "completed":
        fmt.Printf("✅ Success! Result: %v\n", resp.Result)
        return
    case "failed":
        log.Fatalf("❌ Failed: %s", resp.Error)
    case "queued", "running":
        fmt.Printf("⏳ Status: %s\n", resp.Status)
        time.Sleep(2 * time.Second)
    }
}
```

## API Reference

### Client

```go
type Client struct {
    BaseURL    string
    HTTPClient *http.Client
}

func NewClient(baseURL string) *Client
```

### Methods

- `StartScrape(ctx context.Context, req *ScrapeRequest) (*ScrapeResponse, error)` - Start a scraping job
- `GetScrape(ctx context.Context, requestID string) (*ScrapeResponse, error)` - Get job status  
- `WaitForCompletion(ctx context.Context, requestID string, pollInterval time.Duration) (*ScrapeResponse, error)` - Wait for completion
- `ScrapeAndWait(ctx context.Context, req *ScrapeRequest, opts ...WaitOption) (*ScrapeResponse, error)` - Start and wait

### Wait Options

- `WithPollInterval(interval time.Duration)` - Set polling interval (default: 2s)

### Request Types

```go
type ScrapeRequest struct {
    Graph        string      `json:"graph"`                    // "smart", "multi", "search"
    UserPrompt   string      `json:"user_prompt"`             // What to extract
    WebsiteURL   *string     `json:"website_url,omitempty"`   // URL to scrape  
    WebsiteHTML  *string     `json:"website_html,omitempty"`  // Raw HTML
    Sources      []string    `json:"sources,omitempty"`       // Multiple URLs
    SearchQuery  *string     `json:"search_query,omitempty"`  // Search query
    MaxResults   *int        `json:"max_results,omitempty"`   // Max search results
    OutputSchema interface{} `json:"output_schema,omitempty"` // JSON Schema
    LLM          *LLMConfig  `json:"llm,omitempty"`          // LLM config
    Headless     bool        `json:"headless,omitempty"`      // Browser headless mode
    LoaderKwargs interface{} `json:"loader_kwargs,omitempty"` // Browser config
    Verbose      bool        `json:"verbose,omitempty"`       // Debug logging
    Additional   interface{} `json:"additional_config,omitempty"` // Extra config
    TimeoutSec   int         `json:"timeout_sec,omitempty"`   // Timeout in seconds
}

type LLMConfig struct {
    Model       string  `json:"model,omitempty"`       // e.g. "openai/gpt-4o-mini"
    APIKey      string  `json:"api_key,omitempty"`     // API key
    APIBase     string  `json:"api_base,omitempty"`    // Custom API base URL
    Temperature float64 `json:"temperature,omitempty"` // 0.0 to 1.0
    Provider    string  `json:"provider,omitempty"`    // Provider name
}
```

### Response Types

```go
type ScrapeResponse struct {
    RequestID  string      `json:"request_id"`
    Status     string      `json:"status"`     // "queued", "running", "completed", "failed"
    Result     interface{} `json:"result,omitempty"`
    Error      string      `json:"error,omitempty"`
    // ... other fields
}
```

## Graph Types

- **smart**: Single URL scraping with AI extraction
- **multi**: Multiple URL scraping  
- **search**: Search-based scraping

## Helper Functions

```go
// Convert Go values to pointers for optional fields
scrapeapi.String("https://example.com")  // *string
scrapeapi.Bool(true)                     // *bool  
scrapeapi.Int(10)                        // *int
```

## JSON Schema Support

### Automatic Generation from Go Structs (Recommended)

```go
import "github.com/invopop/jsonschema"

type Product struct {
    Name  string  `json:"name" jsonschema:"description=Product name"`
    Price float64 `json:"price" jsonschema:"description=Price in USD"`
    Tags  []string `json:"tags" jsonschema:"description=Product tags"`
}

type ProductList struct {
    Products []Product `json:"products"`
}

// Generate schema automatically
schema := jsonschema.Reflect(&ProductList{})

req := &scrapeapi.ScrapeRequest{
    OutputSchema: schema,
    // ...
}
```

### Manual JSON Schema

```go
schema := map[string]interface{}{
    "type": "object",
    "properties": map[string]interface{}{
        "products": map[string]interface{}{
            "type": "array",
            "items": map[string]interface{}{
                "type": "object",
                "properties": map[string]interface{}{
                    "name":  map[string]interface{}{"type": "string"},
                    "price": map[string]interface{}{"type": "number"},
                },
                "required": []string{"name", "price"},
            },
        },
    },
    "required": []string{"products"},
}
```

### Schema Validation

The API validates your JSON Schema and returns a 400 error with details if:
- The schema is malformed
- The schema cannot be converted to a Pydantic model
- Required fields are missing