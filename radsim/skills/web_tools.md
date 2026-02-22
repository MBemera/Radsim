# Web Tools Skills

Tools for fetching web content in RadSim.

## Available Tools

### web_fetch
Fetch content from a URL.

```python
# Basic fetch
web_fetch(url="https://api.example.com/data")

# With custom headers
web_fetch(
    url="https://api.example.com/data",
    headers={"Authorization": "Bearer token123"}
)

# Extract specific content
web_fetch(
    url="https://example.com/docs",
    extract="text"  # or "html", "json"
)
```

**Parameters:**
- `url` (required): URL to fetch
- `headers` (optional): Custom request headers
- `extract` (optional): Content extraction mode ("text", "html", "json")
- `timeout` (optional): Request timeout in seconds (default: 30)

**Returns:**
```json
{
  "success": true,
  "url": "https://api.example.com/data",
  "status_code": 200,
  "content": "response content...",
  "content_type": "application/json"
}
```

## Security Notes

- **Requires confirmation** - All web requests prompt for approval
- **HTTPS preferred** - HTTP URLs work but HTTPS is recommended
- **No authentication stored** - API keys must be passed each time
- **Rate limiting** - Be mindful of API rate limits

## Common Use Cases

### Fetch API Documentation
```python
web_fetch(url="https://api.example.com/docs")
```

### Download JSON Data
```python
result = web_fetch(
    url="https://api.github.com/repos/owner/repo",
    extract="json"
)
if result["success"]:
    repo_data = result["content"]
```

### Check Service Status
```python
result = web_fetch(url="https://status.example.com/api/status")
```

### Fetch Package Info
```python
# PyPI
web_fetch(url="https://pypi.org/pypi/requests/json", extract="json")

# npm
web_fetch(url="https://registry.npmjs.org/express")
```

## Best Practices

1. **Check status codes** - 200 means success, handle errors appropriately.

2. **Use extract mode** - Let the tool parse JSON/HTML for you.

3. **Handle timeouts** - Set appropriate timeout for slow APIs.

4. **Respect rate limits** - Don't make too many requests too quickly.

5. **Validate URLs** - Ensure URLs are properly formatted.

## Common Patterns

### Fetch and parse JSON
```python
result = web_fetch(
    url="https://api.example.com/users",
    extract="json"
)
if result["success"] and result["status_code"] == 200:
    users = result["content"]
    for user in users:
        print(user["name"])
```

### Check if URL is accessible
```python
result = web_fetch(url="https://example.com")
if result["success"] and result["status_code"] == 200:
    print("Site is up")
else:
    print(f"Site returned: {result.get('status_code', 'error')}")
```

### Fetch with authentication
```python
result = web_fetch(
    url="https://api.example.com/private",
    headers={
        "Authorization": "Bearer YOUR_TOKEN",
        "Accept": "application/json"
    }
)
```

## Limitations

- **No persistent sessions** - Each request is independent
- **No cookies** - Cookie handling is not supported
- **No JavaScript** - Cannot fetch content rendered by JS
- **Size limits** - Large responses may be truncated

For JavaScript-rendered content, use browser automation tools instead.
