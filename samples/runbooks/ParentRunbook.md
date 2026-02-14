# ParentRunbook
This is an example parent runbook that demonstrates calling a sub-runbook (SimpleRunbook.md) via the API. It shows how to use the system-provided environment variables for authentication, correlation tracking, and recursion protection.

# Environment Requirements
```yaml
TEST_VAR: A test environment variable to pass to the child runbook
```

# File System Requirements
```yaml
Input:
```

# Required Claims
```yaml
roles: sre
```

# Script
```sh
#! /bin/zsh
echo "Parent runbook starting"
echo "Correlation ID: $RUNBOOK_CORRELATION_ID"
echo "Recursion stack: $RUNBOOK_RECURSION_STACK"
echo "Runbook URL: $RUNBOOK_URL"

# Call child runbook via API (response is Server-Sent Events; last event is "done" with JSON result)
# The recursion stack already includes this runbook's filename
# Use pre-formatted header variables for easy, correct API calls
echo "Calling SimpleRunbook.md as sub-runbook..."
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$RUNBOOK_URL/SimpleRunbook.md/execute" \
  -H "$RUNBOOK_H_AUTH" -H "$RUNBOOK_H_CORR" -H "$RUNBOOK_H_RECUR" -H "$RUNBOOK_H_CTYPE" \
  -d "{\"env_vars\":{\"TEST_VAR\":\"${TEST_VAR:-parent_value}\"}}")

# Extract HTTP status code and response body
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_CODE:/d')

if [ "$HTTP_CODE" = "200" ]; then
    # Parse the last "data:" line from SSE stream (the "done" event with full result)
    RESULT=$(echo "$BODY" | grep '^data:' | tail -1 | sed 's/^data: //')
    echo "Child runbook executed successfully"
    echo "Response: $RESULT"
else
    echo "Child runbook execution failed with HTTP $HTTP_CODE"
    echo "Response: $BODY"
    exit 1
fi

echo "Parent runbook completed successfully"
```

# History

### 2026-02-14T21:23:06.325Z | Exit Code: 0

**Stdout:**
```
Parent runbook starting
Correlation ID: 42ee524a-b60a-4363-accb-ac339370d97f
Recursion stack: ["ParentRunbook.md"]
Runbook URL: http://localhost:8083/api/runbooks
Calling SimpleRunbook.md as sub-runbook...
Child runbook executed successfully
Response: {"success": true, "runbook": "SimpleRunbook.md", "return_code": 0, "stdout": "Running SimpleRunbook
Parent runbook completed successfully

```

