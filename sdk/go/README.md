# ScrapeAPI Go SDK

A Go client library for the ScrapeAPI service.

## Installation

```bash
go get github.com/dir01/scrapeapi/sdk/go
```

## Usage

### Basic Example

```go
package main

import (
    "context"
    "fmt"
    "log"
    "time"

    scrapeapi "github.com/dir01/scrapeapi/sdk/go"
)

func main() {
    // Create client
    client := scrapeapi.NewClient("http://localhost:8080")

    // Create request with JSON Schema
    req := &scrapeapi.ScrapeRequest{
        Graph:      "smart",
        UserPrompt: "Extract job information",
        WebsiteURL: stringPtr("https://example.com/jobs"),
        OutputSchema: map[string]interface{}{
            "type": "object",
            "properties": map[string]interface{}{
                "title":   map[string]interface{}{"type": "string"},
                "company": map[string]interface{}{"type": "string"},
            },
        },
    }

    // Scrape and wait for completion
    result, err := client.ScrapeAndWait(context.Background(), req, 2*time.Second)
    if err != nil {
        log.Fatal(err)
    }

    fmt.Printf("Result: %v\n", result.Result)
}

func stringPtr(s string) *string { return &s }
```

### Manual Polling

```go
// Start scraping job
startResp, err := client.StartScrape(ctx, req)
if err != nil {
    log.Fatal(err)
}

// Poll for completion
for {
    resp, err := client.GetScrape(ctx, startResp.RequestID)
    if err != nil {
        log.Fatal(err)
    }

    if resp.Status == "completed" {
        fmt.Printf("Result: %v\n", resp.Result)
        break
    } else if resp.Status == "failed" {
        log.Fatalf("Failed: %s", resp.Error)
    }

    time.Sleep(2 * time.Second)
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
- `ScrapeAndWait(ctx context.Context, req *ScrapeRequest, pollInterval time.Duration) (*ScrapeResponse, error)` - Start and wait

### Request Types

```go
type ScrapeRequest struct {
    Graph        string      `json:"graph"`                    // "smart", "multi", "search"
    UserPrompt   string      `json:"user_prompt"`             // What to extract
    WebsiteURL   *string     `json:"website_url,omitempty"`   // URL to scrape
    WebsiteHTML  *string     `json:"website_html,omitempty"`  // Raw HTML
    Sources      []string    `json:"sources,omitempty"`       // Multiple URLs
    OutputSchema interface{} `json:"output_schema,omitempty"` // JSON Schema
    LLM          *LLMConfig  `json:"llm,omitempty"`          // LLM config
    // ... other fields
}

type LLMConfig struct {
    Model       string  `json:"model,omitempty"`
    APIKey      string  `json:"api_key,omitempty"`
    Temperature float64 `json:"temperature,omitempty"`
    // ... other fields
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

## JSON Schema Support

The SDK supports JSON Schema for structured output:

```go
schema := map[string]interface{}{
    "type": "object",
    "properties": map[string]interface{}{
        "title": map[string]interface{}{
            "type": "string",
        },
        "price": map[string]interface{}{
            "type": "number",
        },
    },
}

req := &scrapeapi.ScrapeRequest{
    // ... other fields
    OutputSchema: schema,
}
```