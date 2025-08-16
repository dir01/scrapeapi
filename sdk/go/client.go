package scrapeapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// Client represents a ScrapeAPI client
type Client struct {
	BaseURL    string
	HTTPClient *http.Client
}

// NewClient creates a new ScrapeAPI client
func NewClient(baseURL string) *Client {
	return &Client{
		BaseURL:    baseURL,
		HTTPClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// ScrapeRequest represents a scraping request
type ScrapeRequest struct {
	Graph        string      `json:"graph"`
	UserPrompt   string      `json:"user_prompt"`
	WebsiteURL   *string     `json:"website_url,omitempty"`
	WebsiteHTML  *string     `json:"website_html,omitempty"`
	Sources      []string    `json:"sources,omitempty"`
	SearchQuery  *string     `json:"search_query,omitempty"`
	MaxResults   *int        `json:"max_results,omitempty"`
	OutputSchema interface{} `json:"output_schema,omitempty"`
	LLM          *LLMConfig  `json:"llm,omitempty"`
	Headless     bool        `json:"headless,omitempty"`
	LoaderKwargs interface{} `json:"loader_kwargs,omitempty"`
	Verbose      bool        `json:"verbose,omitempty"`
	Additional   interface{} `json:"additional_config,omitempty"`
	TimeoutSec   int         `json:"timeout_sec,omitempty"`
}

// LLMConfig represents LLM configuration
type LLMConfig struct {
	Model       string  `json:"model,omitempty"`
	APIKey      string  `json:"api_key,omitempty"`
	APIBase     string  `json:"api_base,omitempty"`
	Temperature float64 `json:"temperature,omitempty"`
	Provider    string  `json:"provider,omitempty"`
}

// ScrapeResponse represents the API response
type ScrapeResponse struct {
	RequestID  string      `json:"request_id"`
	Status     string      `json:"status"`
	Graph      string      `json:"graph"`
	UserPrompt string      `json:"user_prompt"`
	WebsiteURL *string     `json:"website_url,omitempty"`
	Sources    []string    `json:"sources,omitempty"`
	Result     interface{} `json:"result,omitempty"`
	Error      string      `json:"error,omitempty"`
}

// StartScrape initiates a scraping job
func (c *Client) StartScrape(ctx context.Context, req *ScrapeRequest) (*ScrapeResponse, error) {
	jsonData, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/v1/scrape", bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.HTTPClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: %s", resp.Status)
	}

	var scrapeResp ScrapeResponse
	if err := json.NewDecoder(resp.Body).Decode(&scrapeResp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	return &scrapeResp, nil
}

// GetScrape polls for the status of a scraping job
func (c *Client) GetScrape(ctx context.Context, requestID string) (*ScrapeResponse, error) {
	httpReq, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/v1/scrape/"+requestID, nil)
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}

	resp, err := c.HTTPClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: %s", resp.Status)
	}

	var scrapeResp ScrapeResponse
	if err := json.NewDecoder(resp.Body).Decode(&scrapeResp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	return &scrapeResp, nil
}

// WaitForCompletion waits for a scraping job to complete with polling
func (c *Client) WaitForCompletion(ctx context.Context, requestID string, pollInterval time.Duration) (*ScrapeResponse, error) {
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-ticker.C:
			resp, err := c.GetScrape(ctx, requestID)
			if err != nil {
				return nil, err
			}

			switch resp.Status {
			case "completed":
				return resp, nil
			case "failed":
				return resp, fmt.Errorf("scraping failed: %s", resp.Error)
			case "queued", "running":
				// Continue polling
				continue
			default:
				return resp, fmt.Errorf("unknown status: %s", resp.Status)
			}
		}
	}
}

// WaitOption is a functional option for configuring wait behavior
type WaitOption func(*waitConfig)

type waitConfig struct {
	pollInterval time.Duration
}

// WithPollInterval sets the polling interval for waiting operations
func WithPollInterval(interval time.Duration) WaitOption {
	return func(cfg *waitConfig) {
		cfg.pollInterval = interval
	}
}

// ScrapeAndWait is a convenience method that starts a scrape job and waits for completion
func (c *Client) ScrapeAndWait(ctx context.Context, req *ScrapeRequest, opts ...WaitOption) (*ScrapeResponse, error) {
	cfg := &waitConfig{
		pollInterval: 2 * time.Second, // default
	}

	for _, opt := range opts {
		opt(cfg)
	}

	startResp, err := c.StartScrape(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("start scrape: %w", err)
	}

	return c.WaitForCompletion(ctx, startResp.RequestID, cfg.pollInterval)
}

// Helper functions for pointer types
func String(s string) *string {
	return &s
}

func Bool(b bool) *bool {
	return &b
}

func Int(i int) *int {
	return &i
}
