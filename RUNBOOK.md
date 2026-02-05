# Runbooks

A runbook is a markdown file, with some specific layout requirements. The document will have five required H1 headers, plus one optional header, with the following content:

# RunbookName
The first H1 should be the runbook name. This should match the file name, without the .md extension. Runbook file names should not contain spaces. By convention, runbooks use Pascal case names. The content immediately following this header (before the next H1 section) is where you will find a description of what the runbook does, when to use it, and how to use it.

# Environment Requirements
This section must contain a yaml code block that defines the environment variables that the script expects to find, with a description of what that variable should contain. 
```yaml
REPO: The name of the repo in the form org/repo
GITHUB_TOKEN: A github classic token with xyz permissions
```

# File System Requirements
This section must contain information about what files and folders should be in place for the script to run. The file naming convention RunbookName.someType if there is only one or two files. If there are many files, you can create a folder with the RunbookName and store the files there.
```yaml
Input:
- ./Runbook.dockerfile
- ./Runbook/one_of_many_files.csv
```

# Required Claims
This section is optional. If present, it specifies the JWT claims required to execute or validate the runbook. This enables Role-Based Access Control (RBAC).

```yaml
# Required Claims
roles: developer, admin, devops
```

When executing or validating a runbook:
1. The API extracts required claims from the runbook
2. Validates that the user's token contains the required claims
3. If validation fails, returns 403 Forbidden and logs the attempt to runbook history
4. If validation succeeds, proceeds with operation

You can specify multiple claim types:
```yaml
# Required Claims
roles: developer, admin
environment: production
team: platform-engineering
```

The token must have at least one matching value for each required claim.

# Script
This section must contain a sh code block with the runbook script
```sh
#! /bin/zsh
some zsh script code
```

# History
At the bottom of the document will be a history section where recent executions are recorded. This has to be at the bottom of the document, as executions will append their run data to the file.

**Design Intent:** History in the markdown file is for human verification only and shows recent executions with core information (timestamp, exit code, stdout, stderr). Full detailed history (including breadcrumbs, config, etc.) is logged to application logs for persistence and analysis. Markdown history is ephemeral and not persisted across container restarts—users requiring persistent history should collect it from application logs.

## History Format

Execution history is stored as human-readable markdown in the runbook's History section. Each execution or validation operation appends a history entry to the runbook file. **Full detailed history (including breadcrumbs, config items, operation type, etc.) is logged to application logs as JSON**—see [history schema](./docs/history-schema.json) for the complete logged format.

The markdown history entry contains only core verification information:
- **Timestamp** - ISO 8601 timestamp when execution finished
- **Exit Code** - Exit code from script execution (0 = success, non-zero = failure, 403 = RBAC failure)
- **Stdout** - Standard output from script execution (if present)
- **Stderr** - Standard error from script execution (if present) or error message for RBAC failures

Example history entry (markdown):
```markdown
### 2026-01-23T14:33:02.123Z | Exit Code: 0

**Stdout:**
```
Script output here
```

**Stderr:**
```
```

### 2026-01-23T14:35:15.456Z | Exit Code: 403

**Error:**
```
RBAC Failure: Access denied for user viewer123. Missing required role: developer
```
```

## Execution Processing

When a runbook is executed, the API follows this process:

1. **Validate runbook structure and requirements** (fail-fast)
   - Check all required sections are present
   - Verify required environment variables are set
   - Verify required input files exist
   - Validate script section contains executable code

2. **Check RBAC permissions** based on required claims
   - Extract required claims from runbook (if present)
   - Validate user's token contains required claims
   - Log RBAC failures to runbook history

3. **Create isolated temporary directory** for script execution
   - Creates unique temp directory per execution
   - Prevents path traversal attacks

4. **Create temp.zsh** with the contents of the script
   - Sets executable permissions (0o700 - owner-only)

5. **Invoke temp.zsh** and capture stdout and stderr
   - Executes with configurable timeout
   - Applies output size limits
   - Captures return code

6. **Append execution history** as minified JSON to runbook
   - Appends to History section
   - Includes all execution metadata

7. **Log execution history** to application logs
   - Same JSON format as file history

8. **Remove temp.zsh** and cleanup temporary directory
   - Automatic cleanup even on errors

## Sub-Runbook Execution

Runbooks can call other runbooks (sub-runbooks) via API calls. This enables composition of complex workflows from simpler, reusable runbooks.

### Available Environment Variables

When a runbook script executes, the following system-managed environment variables are automatically available:

- **`RUNBOOK_API_TOKEN`** - The JWT token string for authenticating API requests
  - Use in `Authorization: Bearer $RUNBOOK_API_TOKEN` header
  - System-managed, cannot be overridden by user env_vars

- **`RUNBOOK_CORRELATION_ID`** - The correlation ID for request tracking across nested executions
  - Use in `X-Correlation-Id: $RUNBOOK_CORRELATION_ID` header
  - Enables tracing request chains across nested runbook executions
  - System-managed, cannot be overridden by user env_vars

- **`RUNBOOK_URL`** - The API URL with `/api/runbooks` path included (e.g., `http://localhost:8083/api/runbooks`)
  - Constructed from `API_PROTOCOL`, `API_HOST`, and `API_PORT` configuration
  - Default: `http://localhost:8083/api/runbooks` (scripts run in same container)
  - Use directly in API calls: `"$RUNBOOK_URL/SimpleRunbook.md/execute"`
  - System-managed, cannot be overridden by user env_vars

- **`RUNBOOK_RECURSION_STACK`** - JSON array of runbook filenames in the execution chain
  - Format: `["ParentRunbook.md", "ChildRunbook.md"]` (includes current runbook)
  - Use in `X-Recursion-Stack: $RUNBOOK_RECURSION_STACK` header
  - Used for recursion detection and prevention
  - System-managed, cannot be overridden by user env_vars
  - **Note**: The stack passed to scripts already includes the current runbook's filename

- **Pre-formatted Header Variables** - Ready-to-use header strings for curl commands (short names for convenience):
  - **`RUNBOOK_H_AUTH`** - Pre-formatted: `"Authorization: Bearer $RUNBOOK_API_TOKEN"`
  - **`RUNBOOK_H_CORR`** - Pre-formatted: `"X-Correlation-Id: $RUNBOOK_CORRELATION_ID"`
  - **`RUNBOOK_H_RECUR`** - Pre-formatted: `"X-Recursion-Stack: $RUNBOOK_RECURSION_STACK"`
  - **`RUNBOOK_H_CTYPE`** - Pre-formatted: `"Content-Type: application/json"`
  - All system-managed, cannot be overridden by user env_vars
  - Use directly: `-H "$RUNBOOK_H_AUTH" -H "$RUNBOOK_H_CORR" -H "$RUNBOOK_H_RECUR" -H "$RUNBOOK_H_CTYPE"`

- **`RUNBOOK_EXEC_DIR_HOST`** - Always set. Path to the current execution directory. When the API is started with `RUNBOOK_WORKSPACE` and `RUNBOOK_WORKSPACE_HOST`, this is the **host** path (use it in **`docker run -v`**; the daemon resolves `-v` on the host). When no workspace is configured, it is the container path (do not use for `docker run -v`). Example with workspace: `docker run --rm -v "$RUNBOOK_EXEC_DIR_HOST/data:/repo" ...`

### Scripts that run `docker run -v`

Paths in `docker run -v <host_path>:<container_path>` are resolved by the Docker daemon on the **host**. When the runbook API runs inside a container, the script’s current directory is inside that container, so a `-v` using that path would not exist on the host. To run any Docker CLI that needs volume mounts:

1. Start the API with a workspace: set `RUNBOOK_WORKSPACE` (container path) and `RUNBOOK_WORKSPACE_HOST` (matching host path) and mount that host path into the API container. Then **`RUNBOOK_EXEC_DIR_HOST`** is the host path to the execution directory.
2. In your script, use **`RUNBOOK_EXEC_DIR_HOST`** in `-v` arguments (e.g. `-v "$RUNBOOK_EXEC_DIR_HOST:/repo"`). If your script invokes a Makefile or other tool that runs `docker run -v`, pass the path via an env var (e.g. `MERGE_REPO_HOST="$RUNBOOK_EXEC_DIR_HOST/repo"`) and have the Makefile use it when set. Without a workspace, `RUNBOOK_EXEC_DIR_HOST` is the container path and must not be used for `-v`.

### Calling a Sub-Runbook

To call a sub-runbook from your script, make an HTTP POST request to the API:

```sh
#! /bin/zsh
echo "Parent runbook starting"

# Call child runbook via API using pre-formatted header variables
# This makes it easy to do right and hard to do wrong
# All headers on one line for easy copy/paste
RESPONSE=$(curl -s -X POST "$RUNBOOK_URL/ChildRunbook.md/execute" \
  -H "$RUNBOOK_H_AUTH" -H "$RUNBOOK_H_CORR" -H "$RUNBOOK_H_RECUR" -H "$RUNBOOK_H_CTYPE" \
  -d '{"env_vars":{"CHILD_VAR":"value"}}')

echo "Child runbook response: $RESPONSE"
echo "Parent runbook completed"
```

**Important Notes:**
- **Use pre-formatted header variables** (`RUNBOOK_H_*`) for easy, correct API calls
- Always pass `X-Recursion-Stack` header to maintain recursion protection
- The recursion stack passed to scripts already includes the current runbook
- Pass the stack as-is (no manipulation needed)
- Always pass `X-Correlation-Id` for request tracing
- Use `RUNBOOK_URL` for the API endpoint (already includes `/api/runbooks` path)

**Alternative: Manual Header Construction**

If you need to construct headers manually, you can still use the individual values:
```sh
curl -X POST "$RUNBOOK_URL/ChildRunbook.md/execute" \
  -H "Authorization: Bearer $RUNBOOK_API_TOKEN" \
  -H "X-Correlation-Id: $RUNBOOK_CORRELATION_ID" \
  -H "X-Recursion-Stack: $RUNBOOK_RECURSION_STACK" \
  -H "Content-Type: application/json" \
  -d '{"env_vars":{}}'
```

However, using the pre-formatted header variables is recommended as it reduces errors and makes the code cleaner.

### Recursion Protection

The system automatically prevents infinite loops and circular dependencies:

1. **Recursion Detection**: Before executing a runbook, the API checks if its filename appears in the recursion stack. If found, execution is rejected with an error written to stderr.

2. **Recursion Depth Limit**: The system enforces a maximum recursion depth (default: 50) to prevent resource exhaustion from very deep legitimate nesting.

3. **Error Handling**: Recursion violations are written to stderr, which persists in execution history for debugging and monitoring.

**Example Recursion Error:**
```
Recursion detected: Runbook ParentRunbook.md already in execution chain: ["ParentRunbook.md", "ChildRunbook.md", "ParentRunbook.md"]
```

**Example Depth Limit Error:**
```
Recursion depth limit exceeded: 50 (max: 50)
```

### Best Practices

1. **Always pass recursion stack**: Include `X-Recursion-Stack` header in all sub-runbook calls to maintain protection
2. **Use correlation IDs**: Pass `X-Correlation-Id` for request tracing across nested executions
3. **Handle errors**: Check sub-runbook response status and handle errors appropriately
4. **Keep runbooks focused**: Design runbooks to do one thing well, compose them for complex workflows
5. **Test recursion scenarios**: Verify your runbook composition doesn't create circular dependencies

### Example: Parent Runbook

See `samples/runbooks/ParentRunbook.md` for a complete example of a parent runbook calling a child runbook.
