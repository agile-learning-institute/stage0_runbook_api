# SimpleRunbook
This is a simple test runbook that demonstrates the basic functionality of the stage0_runner utility. It performs a simple echo operation and lists the current directory.

# Environment Requirements
```yaml
TEST_VAR: A test environment variable for demonstration purposes
```

# File System Requirements
```yaml
Input:
```

# Required Claims
```yaml
roles: sre, api
```
This section is optional. If present, the token must include the specified claims to execute or validate the runbook.
- `roles`: List of roles (comma-separated) that are allowed to execute/validate this runbook
- Other claims can be specified as key-value pairs where the value is a comma-separated list of allowed values

# Script
```sh
#! /bin/zsh
echo "Running SimpleRunbook"
echo "Test variable value: ${TEST_VAR:-not set}"
echo "Current directory: $(pwd)"
echo "Listing files:"
ls -la
echo "SimpleRunbook completed successfully"
```

# History

### 2026-02-14T21:23:06.208Z | Exit Code: 0

**Stdout:**
```
Running SimpleRunbook
Test variable value: asdf
Current directory: /execution/runbook-exec-fa8641d7-tkdkw60f
Listing files:
total 4
drwx------ 3 root root  96 Feb 14 21:23 .
drwxr-xr-x 4 root root 128 Feb 14 21:23 ..
-rwx------ 1 root root 195 Feb 14 21:23 temp.zsh
SimpleRunbook completed successfully

```


### 2026-02-14T21:25:55.433Z | Exit Code: 0

**Stdout:**
```
Running SimpleRunbook
Test variable value: asdf
Current directory: /execution/runbook-exec-d08b72a6-7bfgvmlr
Listing files:
total 4
drwx------ 3 root root  96 Feb 14 21:25 .
drwxr-xr-x 3 root root  96 Feb 14 21:25 ..
-rwx------ 1 root root 195 Feb 14 21:25 temp.zsh
SimpleRunbook completed successfully

```

