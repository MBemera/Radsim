# Browser Automation Skills

Tools for web browser automation in RadSim (requires Playwright).

## Available Tools

### browser_open
Open a URL in the browser.

```python
browser_open(url="https://example.com")
```

**Parameters:**
- `url` (required): URL to navigate to

**Returns:**
```json
{
  "success": true,
  "url": "https://example.com",
  "title": "Example Domain"
}
```

---

### browser_click
Click an element on the page.

```python
# Click by CSS selector
browser_click(selector="button.submit")

# Click by text
browser_click(selector="text=Sign In")

# Click by ID
browser_click(selector="#login-button")
```

**Parameters:**
- `selector` (required): CSS selector, text selector, or element identifier

**Selector Types:**
- CSS: `button.primary`, `#submit`, `[data-testid="login"]`
- Text: `text=Click me`, `text=Submit`
- Role: `role=button[name="Submit"]`

---

### browser_type
Type text into an input field.

```python
# Type into input
browser_type(selector="input[name='email']", text="user@example.com")

# Type with delay (for autocomplete)
browser_type(selector="#search", text="query", delay=100)
```

**Parameters:**
- `selector` (required): Element selector
- `text` (required): Text to type
- `delay` (optional): Delay between keystrokes in ms

---

### browser_screenshot
Capture a screenshot.

```python
# Full page screenshot
browser_screenshot()

# Named screenshot
browser_screenshot(filename="login_page.png")

# Element screenshot
browser_screenshot(selector="#main-content")
```

**Parameters:**
- `filename` (optional): Save screenshot with specific name
- `selector` (optional): Screenshot specific element

**Returns:**
```json
{
  "success": true,
  "path": "/path/to/screenshot.png"
}
```

## Setup Requirements

Browser automation requires Playwright to be installed:

```bash
pip install playwright
playwright install chromium
```

## Common Use Cases

### Login Flow
```python
# 1. Navigate to login page
browser_open(url="https://app.example.com/login")

# 2. Fill credentials
browser_type(selector="input[name='email']", text="user@example.com")
browser_type(selector="input[name='password']", text="password123")

# 3. Click login
browser_click(selector="button[type='submit']")

# 4. Capture result
browser_screenshot(filename="after_login.png")
```

### Form Filling
```python
browser_open(url="https://example.com/form")

browser_type(selector="#name", text="John Doe")
browser_type(selector="#email", text="john@example.com")
browser_click(selector="input[value='Option A']")  # Radio button
browser_click(selector="#terms")  # Checkbox
browser_click(selector="button.submit")
```

### Web Scraping
```python
# Navigate and capture
browser_open(url="https://example.com/data")
browser_screenshot(filename="data_page.png")

# Note: For actual scraping, use web_fetch for static content
# Browser automation is for JavaScript-rendered content
```

## Best Practices

1. **Wait for elements** - Pages may take time to load. The tools automatically wait.

2. **Use specific selectors** - Prefer IDs and data-testid over generic classes.

3. **Take screenshots** - Capture state at key points for debugging.

4. **Handle navigation** - After clicks that navigate, wait for the new page.

5. **Clean up** - Close browser sessions when done.

## Common Patterns

### Wait and retry
```python
# If element might not be immediately available
import time
for attempt in range(3):
    result = browser_click(selector="#dynamic-button")
    if result["success"]:
        break
    time.sleep(1)
```

### Debug with screenshots
```python
browser_open(url="https://example.com")
browser_screenshot(filename="step1_initial.png")

browser_type(selector="#search", text="query")
browser_screenshot(filename="step2_typed.png")

browser_click(selector="button.search")
browser_screenshot(filename="step3_results.png")
```

## Limitations

- **Requires Playwright** - Must be installed separately
- **Headless by default** - No visible browser window
- **Resource intensive** - Uses more memory than simple HTTP requests
- **Single page** - Each session manages one browser tab

For simple HTTP requests, prefer `web_fetch`. Use browser automation only when:
- Content requires JavaScript rendering
- You need to interact with forms/buttons
- You're testing user flows
