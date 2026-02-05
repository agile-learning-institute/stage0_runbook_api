# Security

## Security Features

The API implements several security measures to protect against common vulnerabilities:

### Authentication and Authorization
- **JWT-based authentication** - All API endpoints (except `/dev-login`, `/metrics`, and `/docs`) require valid JWT tokens
- **Role-Based Access Control (RBAC)** - Runbooks can specify required claims that users must have to execute or validate
- **Token validation** - JWT tokens are validated for signature, expiration, issuer, and audience
- **Dev-login protection** - The `/dev-login` endpoint is disabled by default and must be explicitly enabled

### Input Validation and Sanitization
- **Environment variable validation** - Environment variable names are validated (alphanumeric + underscore only)
- **Environment variable sanitization** - Control characters are removed from environment variable values (newlines/tabs preserved for scripts)
- **Path traversal protection** - Runbook filenames are sanitized to prevent directory traversal attacks
- **YAML parsing** - Uses PyYAML's `safe_load()` to prevent code execution vulnerabilities

### Resource Limits
- **Script timeout** - Scripts are terminated after a configurable timeout (default: 10 minutes)
- **Output size limits** - Script output is truncated to prevent memory exhaustion (default: 10MB)

### Execution Isolation
- **Temporary directory isolation** - Scripts are executed in isolated temporary directories per execution
- **Automatic cleanup** - Temporary directories and files are cleaned up after execution, even on errors

## Production Security Requirements

**CRITICAL: The following must be configured before deploying to production:**

1. **JWT Configuration**
   - **MUST** change `JWT_SECRET` from default `dev-secret-change-me` to a strong, randomly generated secret
   - **MUST** configure `JWT_ISSUER` and `JWT_AUDIENCE` to match your identity provider
   - **MUST** use a secure token TTL appropriate for your security policy

2. **Disable Development Features**
   - **MUST** set `ENABLE_LOGIN=false` (or omit it, as false is default) to disable `/dev-login` endpoint
   - **NEVER** enable dev-login in production - it allows anyone to generate tokens with arbitrary roles

3. **Network Security**
   - **MUST** use HTTPS/TLS in production (configure via reverse proxy or load balancer)
   - **SHOULD** restrict network access to the API server
   - **SHOULD** use a reverse proxy (nginx, Traefik, etc.) for additional security layers

4. **Container Security**
   - **SHOULD** run containers as non-root user
   - **SHOULD** use read-only file systems where possible
   - **SHOULD** limit container capabilities
   - **SHOULD** scan container images for vulnerabilities

5. **Monitoring and Logging**
   - **SHOULD** monitor for failed authentication attempts
   - **SHOULD** log all runbook executions and RBAC failures
   - **SHOULD** set up alerts for suspicious activity
   - **SHOULD** monitor resource usage (CPU, memory, disk)

## Known Limitations and Security Considerations

### Script Execution Security

**IMPORTANT:** Scripts executed by runbooks run with the same privileges as the API server process. This means:

- Scripts have **full access to the file system** within the container/host
- Scripts can **access the network** if network access is available
- Scripts can **modify system state** (files, environment variables, etc.)
- Scripts can **access other processes** running on the same system

**Recommendations:**
- **Only execute trusted runbooks** - Review runbook scripts before execution
- **Use container isolation** - Consider executing runbooks in isolated Docker containers (see SRE.md)
- **Run as non-root** - Ensure the API server runs with minimal privileges
- **Network isolation** - Consider network policies to restrict script network access
- **File system restrictions** - Use read-only mounts where possible

### Concurrent Execution

- **File race conditions** - Concurrent executions of the same runbook may result in history entries being interleaved or lost. This is a known limitation when using file-based history storage.
- **Resource contention** - Multiple concurrent script executions may compete for system resources (CPU, memory, disk I/O)

**Recommendations:**
- **Monitor resource usage** - Set up alerts for high resource consumption
- **Consider database storage** - For high-concurrency scenarios, consider moving history to a database

### Development Mode Security

When `ENABLE_LOGIN=true`:
- The `/dev-login` endpoint allows **anyone** to generate tokens with **arbitrary roles**
- JWT signature verification may be bypassed if using default `JWT_SECRET`

**NEVER enable development mode in production!**

### Threat Model

The API is designed to protect against:
- ✅ Unauthorized access (via JWT authentication)
- ✅ Path traversal attacks (via filename sanitization)
- ✅ Resource exhaustion (via timeouts and output limits)
- ✅ Command injection via environment variables (via validation/sanitization)

The API does **NOT** protect against:
- ❌ Malicious scripts in trusted runbooks (scripts run with full privileges)
- ❌ Insider threats (users with valid tokens can execute any runbook they have access to)
- ❌ Network-based attacks on script execution (scripts can make network calls)
- ❌ File system attacks from within scripts (scripts have file system access)

## Security Best Practices

1. **Principle of Least Privilege**
   - Grant users only the minimum roles/claims needed
   - Use RBAC to restrict access to sensitive runbooks
   - Run the API server with minimal system privileges

2. **Defense in Depth**
   - Use multiple security layers (network, application, container)
   - Implement monitoring and alerting
   - Regular security audits and updates

3. **Secure Configuration**
   - Use strong, randomly generated secrets
   - Store secrets in secure secret management systems
   - Rotate secrets regularly

4. **Runbook Review**
   - Review all runbook scripts before execution
   - Use version control for runbooks
   - Implement runbook approval workflows for sensitive operations

5. **Monitoring and Incident Response**
   - Monitor authentication failures
   - Log all runbook executions
   - Set up alerts for suspicious activity
   - Have an incident response plan

## Reporting Security Issues

If you discover a security vulnerability, please report it responsibly:
- **DO NOT** open a public GitHub issue
- Contact the maintainers directly
- Provide detailed information about the vulnerability
- Allow time for the issue to be addressed before public disclosure

