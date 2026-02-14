"""
Script executor for running runbook scripts with resource limits and isolation.

Handles script execution with timeouts, output size limits, and environment variable management.
Supports streaming execution for real-time stdout/stderr delivery.
"""
import os
import re
import json
import subprocess
import threading
import time
import uuid
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Generator
import logging

from ..flask_utils.exceptions import HTTPInternalServerError
from ..config.config import Config

logger = logging.getLogger(__name__)

# Regex pattern for valid environment variable names
# Must start with letter or underscore, followed by alphanumeric or underscore
ENV_VAR_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class ScriptExecutor:
    """
    Executor for running runbook scripts with resource limits and isolation.
    
    Handles:
    - Script execution with timeouts
    - Output size limits
    - Environment variable validation and sanitization
    - Temporary directory isolation
    - Resource cleanup
    """
    
    @staticmethod
    def execute_script(
        script: str, 
        env_vars: Optional[Dict[str, str]] = None,
        token_string: Optional[str] = None,
        correlation_id: Optional[str] = None,
        recursion_stack: Optional[List[str]] = None,
        input_paths: Optional[List[str]] = None,
        runbook_dir: Optional[Path] = None
    ) -> Tuple[int, str, str]:
        """
        Execute a script with resource limits (timeout, output size).
        
        Args:
            script: The script content to execute
            env_vars: Optional dictionary of environment variables to set
            token_string: Optional JWT token string for API authentication
            correlation_id: Optional correlation ID for request tracking
            recursion_stack: Optional list of runbook filenames in execution chain
            input_paths: Optional list of input file/folder paths (relative to runbook_dir)
            runbook_dir: Optional path to runbook directory (for resolving input_paths)
            
        Returns:
            tuple: (return_code, stdout, stderr)
        """
        config = Config.get_instance()
        timeout_seconds = config.SCRIPT_TIMEOUT_SECONDS
        max_output_bytes = config.MAX_OUTPUT_SIZE_BYTES
        
        # Validate resource limits - use Config defaults if invalid
        if timeout_seconds <= 0:
            default_timeout = config.get_default("SCRIPT_TIMEOUT_SECONDS")
            logger.warning(f"Invalid timeout value {timeout_seconds}, using Config default: {default_timeout}")
            timeout_seconds = default_timeout
        
        if max_output_bytes <= 0:
            default_max_output = config.get_default("MAX_OUTPUT_SIZE_BYTES")
            logger.warning(f"Invalid max_output_bytes value {max_output_bytes}, using Config default: {default_max_output}")
            max_output_bytes = default_max_output
        
        # System-managed environment variables (protected from user override)
        SYSTEM_ENV_VARS = {
            'RUNBOOK_API_TOKEN',
            'RUNBOOK_CORRELATION_ID',
            'RUNBOOK_URL',
            'RUNBOOK_RECURSION_STACK',
            'RUNBOOK_H_AUTH',
            'RUNBOOK_H_CORR',
            'RUNBOOK_H_RECUR',
            'RUNBOOK_H_CTYPE',
            'RUNBOOK_HEADERS',
            'RUNBOOK_EXEC_DIR_HOST',
        }
        
        # Validate and sanitize environment variables
        original_env = {}
        sanitized_env_vars = {}
        
        if env_vars:
            for key, value in env_vars.items():
                # Warn if user tries to override system-managed variables (but don't fail)
                if key in SYSTEM_ENV_VARS:
                    logger.warning(f"User attempted to override system-managed environment variable: {key}. User value will be ignored.")
                    continue
                
                # Validate environment variable name
                if not ENV_VAR_NAME_PATTERN.match(key):
                    logger.warning(f"Invalid environment variable name rejected: {key} (only alphanumeric and underscore allowed)")
                    return 1, "", f"ERROR: Invalid environment variable name: {key}. Variable names must start with a letter or underscore and contain only alphanumeric characters and underscores."
                
                # Validate value is string (convert if needed, but log it)
                if value is None:
                    logger.warning(f"Environment variable {key} has None value, converting to empty string")
                    value = ""
                elif not isinstance(value, str):
                    logger.warning(f"Environment variable {key} has non-string value type {type(value)}, converting to string")
                    value = str(value)
                
                # Sanitize value: remove control characters but preserve newlines and tabs for scripts
                # Control characters (0x00-0x1F) except newline (0x0A), tab (0x09), carriage return (0x0D)
                sanitized_value = ''.join(
                    char for char in value 
                    if ord(char) >= 32 or char in ['\n', '\t', '\r']
                )
                
                # Log if value was modified during sanitization
                if sanitized_value != value:
                    logger.warning(
                        f"Environment variable {key} value was sanitized: "
                        f"removed {len(value) - len(sanitized_value)} control characters"
                    )
                
                # Store original value for restoration
                original_env[key] = os.environ.get(key)
                sanitized_env_vars[key] = sanitized_value
                
                # Set the sanitized value in environment
                os.environ[key] = sanitized_value
                logger.debug(f"Set environment variable: {key} (value length: {len(sanitized_value)} bytes)")
        
        # Set system-managed environment variables (after user vars to ensure they take precedence)
        if token_string:
            original_env['RUNBOOK_API_TOKEN'] = os.environ.get('RUNBOOK_API_TOKEN')
            os.environ['RUNBOOK_API_TOKEN'] = token_string
            logger.debug("Set system environment variable: RUNBOOK_API_TOKEN (value masked)")
        
        if correlation_id:
            original_env['RUNBOOK_CORRELATION_ID'] = os.environ.get('RUNBOOK_CORRELATION_ID')
            os.environ['RUNBOOK_CORRELATION_ID'] = correlation_id
            logger.debug(f"Set system environment variable: RUNBOOK_CORRELATION_ID = {correlation_id}")
        
        # Construct API URL with /api/runbooks path from config
        runbook_url = f"{config.API_PROTOCOL}://{config.API_HOST}:{config.API_PORT}/api/runbooks"
        original_env['RUNBOOK_URL'] = os.environ.get('RUNBOOK_URL')
        os.environ['RUNBOOK_URL'] = runbook_url
        logger.debug(f"Set system environment variable: RUNBOOK_URL = {runbook_url}")
        
        # Set recursion stack as JSON string
        recursion_stack_json = None
        if recursion_stack is not None:
            recursion_stack_json = json.dumps(recursion_stack)
            original_env['RUNBOOK_RECURSION_STACK'] = os.environ.get('RUNBOOK_RECURSION_STACK')
            os.environ['RUNBOOK_RECURSION_STACK'] = recursion_stack_json
            logger.debug(f"Set system environment variable: RUNBOOK_RECURSION_STACK = {recursion_stack_json}")
        
        # Set pre-formatted header variables for easy use in curl commands (short names for convenience)
        if token_string:
            header_auth = f"Authorization: Bearer {token_string}"
            original_env['RUNBOOK_H_AUTH'] = os.environ.get('RUNBOOK_H_AUTH')
            os.environ['RUNBOOK_H_AUTH'] = header_auth
            logger.debug("Set system environment variable: RUNBOOK_H_AUTH (value masked)")
        
        if correlation_id:
            header_correlation = f"X-Correlation-Id: {correlation_id}"
            original_env['RUNBOOK_H_CORR'] = os.environ.get('RUNBOOK_H_CORR')
            os.environ['RUNBOOK_H_CORR'] = header_correlation
            logger.debug(f"Set system environment variable: RUNBOOK_H_CORR = {header_correlation}")
        
        if recursion_stack_json:
            header_recursion = f"X-Recursion-Stack: {recursion_stack_json}"
            original_env['RUNBOOK_H_RECUR'] = os.environ.get('RUNBOOK_H_RECUR')
            os.environ['RUNBOOK_H_RECUR'] = header_recursion
            logger.debug(f"Set system environment variable: RUNBOOK_H_RECUR = {header_recursion}")
        
        # Always set Content-Type header
        header_content_type = "Content-Type: application/json"
        original_env['RUNBOOK_H_CTYPE'] = os.environ.get('RUNBOOK_H_CTYPE')
        os.environ['RUNBOOK_H_CTYPE'] = header_content_type
        logger.debug(f"Set system environment variable: RUNBOOK_H_CTYPE = {header_content_type}")
        
        # Set combined headers variable for convenience (space-separated -H flags)
        # This can be used with eval: eval "curl ... $RUNBOOK_HEADERS ..."
        # Or individual headers can be used: -H "$RUNBOOK_HEADER_AUTH" -H "$RUNBOOK_HEADER_CORRELATION" etc.
        headers_list = []
        if token_string:
            headers_list.append(f'-H "{header_auth}"')
        if correlation_id:
            headers_list.append(f'-H "{header_correlation}"')
        if recursion_stack_json:
            headers_list.append(f'-H "{header_recursion}"')
        headers_list.append(f'-H "{header_content_type}"')
        
        runbook_headers = ' '.join(headers_list)
        original_env['RUNBOOK_HEADERS'] = os.environ.get('RUNBOOK_HEADERS')
        os.environ['RUNBOOK_HEADERS'] = runbook_headers
        logger.debug("Set system environment variable: RUNBOOK_HEADERS (value masked)")
        
        try:
            # Create isolated temporary directory for this execution (prevents path traversal)
            # Per-run dirs are created under config.EXECUTION_DIR; fallback to system temp if not present (e.g. local dev)
            temp_exec_dir = None
            start_time = time.time()
            try:
                parent_dir = Path(config.EXECUTION_DIR) if Path(config.EXECUTION_DIR).is_dir() else None
                temp_exec_dir = Path(tempfile.mkdtemp(prefix=f'runbook-exec-{uuid.uuid4().hex[:8]}-', dir=str(parent_dir) if parent_dir else None))
                temp_script = temp_exec_dir / 'temp.zsh'
                
                # Validate that the temp directory is actually a directory (security check)
                if not temp_exec_dir.exists() or not temp_exec_dir.is_dir():
                    raise HTTPInternalServerError(f"Failed to create temporary execution directory")
                
                # Copy input files/folders to temp execution directory
                if input_paths and runbook_dir:
                    copy_errors = ScriptExecutor._copy_input_files(input_paths, runbook_dir, temp_exec_dir)
                    if copy_errors:
                        # Fail-fast: return error if input files cannot be copied
                        error_msg = "Failed to copy input files:\n" + "\n".join(copy_errors)
                        logger.error(error_msg)
                        return 1, "", error_msg
                
                # Per-execution env: host path to this run's dir (for docker run -v). From config.MOUNT_DIR when set.
                exec_env = dict(os.environ)
                exec_env['RUNBOOK_EXEC_DIR_HOST'] = (
                    f"{config.MOUNT_DIR.rstrip('/')}/{temp_exec_dir.name}"
                    if (parent_dir and config.MOUNT_DIR) else str(temp_exec_dir)
                )
                
                # Create and write the script file
                with open(temp_script, 'w', encoding='utf-8') as f:
                    f.write(script)
                os.chmod(temp_script, 0o700)  # More restrictive: owner-only permissions
                
                # Execute the script with timeout and resource limits
                # Use temp_exec_dir as working directory for isolation
                logger.info(
                    f"Executing script with timeout={timeout_seconds}s, max_output={max_output_bytes} bytes, "
                    f"temp_dir={temp_exec_dir}"
                )
                
                try:
                    result = subprocess.run(
                        ['/bin/zsh', str(temp_script)],
                        capture_output=True,
                        text=True,
                        cwd=str(temp_exec_dir),  # Execute in isolated temp directory (prevents access to /, ../, etc.)
                        timeout=timeout_seconds,
                        env=exec_env,
                    )
                    
                    execution_time = time.time() - start_time
                    
                    # Apply output size limits
                    stdout = result.stdout or ""
                    stderr = result.stderr or ""
                    stdout_truncated = False
                    stderr_truncated = False
                    
                    # Check and truncate stdout if necessary
                    stdout_bytes = len(stdout.encode('utf-8'))
                    if stdout_bytes > max_output_bytes:
                        stdout, stdout_truncated = ScriptExecutor._truncate_output(stdout, max_output_bytes)
                        logger.warning(
                            f"Script stdout truncated from {stdout_bytes} bytes to {max_output_bytes} bytes "
                            f"(execution_time={execution_time:.2f}s)"
                        )
                    
                    # Check and truncate stderr if necessary
                    stderr_bytes = len(stderr.encode('utf-8'))
                    if stderr_bytes > max_output_bytes:
                        stderr, stderr_truncated = ScriptExecutor._truncate_output(stderr, max_output_bytes)
                        logger.warning(
                            f"Script stderr truncated from {stderr_bytes} bytes to {max_output_bytes} bytes "
                            f"(execution_time={execution_time:.2f}s)"
                        )
                    
                    # Add truncation warnings to stderr if output was truncated
                    if stdout_truncated or stderr_truncated:
                        truncation_warning = (
                            f"\n[WARNING: Output truncated due to size limit ({max_output_bytes} bytes)]\n"
                        )
                        stderr = stderr + truncation_warning
                    
                    # Log resource usage
                    logger.info(
                        f"Script execution completed: return_code={result.returncode}, "
                        f"execution_time={execution_time:.2f}s, "
                        f"stdout_size={len(stdout.encode('utf-8'))} bytes, "
                        f"stderr_size={len(stderr.encode('utf-8'))} bytes"
                    )
                    
                    return result.returncode, stdout, stderr
                    
                except subprocess.TimeoutExpired:
                    execution_time = time.time() - start_time
                    error_msg = (
                        f"Script execution timed out after {timeout_seconds} seconds "
                        f"(actual execution time: {execution_time:.2f}s). "
                        f"The script was terminated to prevent resource exhaustion."
                    )
                    logger.warning(f"Script timeout: {error_msg}")
                    return 1, "", error_msg
                
            except Exception as e:
                execution_time = time.time() - start_time
                error_msg = f"ERROR: Failed to execute script: {e} (execution_time: {execution_time:.2f}s)"
                logger.error(error_msg, exc_info=True)
                return 1, "", error_msg
            finally:
                # Clean up temporary execution directory and all contents
                # shutil.rmtree() recursively removes directory tree (including all sub-directories and files)
                # Cleanup happens even if execution fails (finally block ensures execution)
                if temp_exec_dir and temp_exec_dir.exists():
                    try:
                        shutil.rmtree(temp_exec_dir)
                        logger.debug(f"Cleaned up temporary execution directory: {temp_exec_dir}")
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to clean up temp directory {temp_exec_dir}: {cleanup_error}")
        finally:
            # Restore original environment variables (including system-managed vars)
            for key, original_value in original_env.items():
                if original_value is None:
                    # Variable didn't exist before, remove it
                    os.environ.pop(key, None)
                    logger.debug(f"Restored environment: removed {key}")
                else:
                    # Restore original value
                    # Mask token value in logs for security
                    if key == 'RUNBOOK_API_TOKEN':
                        logger.debug(f"Restored environment: {key} = (masked)")
                    else:
                        display_value = original_value[:50] if len(str(original_value)) > 50 else original_value
                        logger.debug(f"Restored environment: {key} = {display_value}")
                    os.environ[key] = original_value
    
    @staticmethod
    def execute_script_streaming(
        script: str,
        env_vars: Optional[Dict[str, str]] = None,
        token_string: Optional[str] = None,
        correlation_id: Optional[str] = None,
        recursion_stack: Optional[List[str]] = None,
        input_paths: Optional[List[str]] = None,
        runbook_dir: Optional[Path] = None,
    ) -> Generator[Tuple[str, str], None, None]:
        """
        Execute a script and stream stdout/stderr as they are produced.
        
        Yields:
            ("stdout", chunk) or ("stderr", chunk) for each output chunk.
            Final yield is ("done", json_str) with return_code, stdout, stderr for history.
        """
        import queue as queue_module
        
        config = Config.get_instance()
        timeout_seconds = config.SCRIPT_TIMEOUT_SECONDS
        max_output_bytes = config.MAX_OUTPUT_SIZE_BYTES
        
        if timeout_seconds <= 0:
            timeout_seconds = config.get_default("SCRIPT_TIMEOUT_SECONDS")
        if max_output_bytes <= 0:
            max_output_bytes = config.get_default("MAX_OUTPUT_SIZE_BYTES")
        
        SYSTEM_ENV_VARS = {
            'RUNBOOK_API_TOKEN', 'RUNBOOK_CORRELATION_ID', 'RUNBOOK_URL',
            'RUNBOOK_RECURSION_STACK', 'RUNBOOK_H_AUTH', 'RUNBOOK_H_CORR',
            'RUNBOOK_H_RECUR', 'RUNBOOK_H_CTYPE', 'RUNBOOK_HEADERS', 'RUNBOOK_EXEC_DIR_HOST',
        }
        
        original_env = {}
        if env_vars:
            for key, value in env_vars.items():
                if key in SYSTEM_ENV_VARS:
                    continue
                if not ENV_VAR_NAME_PATTERN.match(key):
                    yield ("stderr", f"ERROR: Invalid environment variable name: {key}\n")
                    yield ("done", json.dumps({
                        "return_code": 1, "stdout": "", "stderr": f"ERROR: Invalid environment variable name: {key}"
                    }))
                    return
                value = "" if value is None else str(value)
                sanitized = ''.join(c for c in value if ord(c) >= 32 or c in ['\n', '\t', '\r'])
                original_env[key] = os.environ.get(key)
                os.environ[key] = sanitized
        
        if token_string:
            original_env['RUNBOOK_API_TOKEN'] = os.environ.get('RUNBOOK_API_TOKEN')
            os.environ['RUNBOOK_API_TOKEN'] = token_string
        if correlation_id:
            original_env['RUNBOOK_CORRELATION_ID'] = os.environ.get('RUNBOOK_CORRELATION_ID')
            os.environ['RUNBOOK_CORRELATION_ID'] = correlation_id
        
        runbook_url = f"{config.API_PROTOCOL}://{config.API_HOST}:{config.API_PORT}/api/runbooks"
        original_env['RUNBOOK_URL'] = os.environ.get('RUNBOOK_URL')
        os.environ['RUNBOOK_URL'] = runbook_url
        
        recursion_stack_json = json.dumps(recursion_stack) if recursion_stack else None
        if recursion_stack_json:
            original_env['RUNBOOK_RECURSION_STACK'] = os.environ.get('RUNBOOK_RECURSION_STACK')
            os.environ['RUNBOOK_RECURSION_STACK'] = recursion_stack_json
        
        if token_string:
            header_auth = f"Authorization: Bearer {token_string}"
            original_env['RUNBOOK_H_AUTH'] = os.environ.get('RUNBOOK_H_AUTH')
            os.environ['RUNBOOK_H_AUTH'] = header_auth
        if correlation_id:
            header_corr = f"X-Correlation-Id: {correlation_id}"
            original_env['RUNBOOK_H_CORR'] = os.environ.get('RUNBOOK_H_CORR')
            os.environ['RUNBOOK_H_CORR'] = header_corr
        if recursion_stack_json:
            header_recur = f"X-Recursion-Stack: {recursion_stack_json}"
            original_env['RUNBOOK_H_RECUR'] = os.environ.get('RUNBOOK_H_RECUR')
            os.environ['RUNBOOK_H_RECUR'] = header_recur
        header_ctype = "Content-Type: application/json"
        original_env['RUNBOOK_H_CTYPE'] = os.environ.get('RUNBOOK_H_CTYPE')
        os.environ['RUNBOOK_H_CTYPE'] = header_ctype
        
        headers_list = [f'-H "{header_ctype}"']
        if token_string:
            headers_list.insert(0, f'-H "{header_auth}"')
        if correlation_id:
            headers_list.insert(0, f'-H "{header_corr}"')
        if recursion_stack_json:
            headers_list.insert(0, f'-H "{header_recur}"')
        original_env['RUNBOOK_HEADERS'] = os.environ.get('RUNBOOK_HEADERS')
        os.environ['RUNBOOK_HEADERS'] = ' '.join(headers_list)
        
        temp_exec_dir = None
        proc = None
        stdout_acc: List[str] = []
        stderr_acc: List[str] = []
        stdout_bytes_acc = 0
        stderr_bytes_acc = 0
        stdout_truncated = False
        stderr_truncated = False
        return_code = 1
        
        try:
            parent_dir = Path(config.EXECUTION_DIR) if Path(config.EXECUTION_DIR).is_dir() else None
            temp_exec_dir = Path(tempfile.mkdtemp(
                prefix=f'runbook-exec-{uuid.uuid4().hex[:8]}-',
                dir=str(parent_dir) if parent_dir else None
            ))
            temp_script = temp_exec_dir / 'temp.zsh'
            
            if not temp_exec_dir.exists() or not temp_exec_dir.is_dir():
                raise HTTPInternalServerError("Failed to create temporary execution directory")
            
            if input_paths and runbook_dir:
                copy_errors = ScriptExecutor._copy_input_files(input_paths, runbook_dir, temp_exec_dir)
                if copy_errors:
                    error_msg = "Failed to copy input files:\n" + "\n".join(copy_errors)
                    yield ("stderr", error_msg)
                    yield ("done", json.dumps({"return_code": 1, "stdout": "", "stderr": error_msg}))
                    return
            
            exec_env = dict(os.environ)
            exec_env['RUNBOOK_EXEC_DIR_HOST'] = (
                f"{config.MOUNT_DIR.rstrip('/')}/{temp_exec_dir.name}"
                if (parent_dir and config.MOUNT_DIR) else str(temp_exec_dir)
            )
            
            with open(temp_script, 'w', encoding='utf-8') as f:
                f.write(script)
            os.chmod(temp_script, 0o700)
            
            chunk_queue: queue_module.Queue = queue_module.Queue()
            start_time = time.time()
            
            def stdout_thread():
                try:
                    for line in iter(proc.stdout.readline, ''):
                        chunk_queue.put(("stdout", line))
                except Exception:
                    pass
                finally:
                    if proc.stdout:
                        proc.stdout.close()
            
            def stderr_thread():
                try:
                    for line in iter(proc.stderr.readline, ''):
                        chunk_queue.put(("stderr", line))
                except Exception:
                    pass
                finally:
                    if proc.stderr:
                        proc.stderr.close()
            
            proc = subprocess.Popen(
                ['/bin/zsh', str(temp_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(temp_exec_dir),
                env=exec_env,
            )
            
            t_stdout = threading.Thread(target=stdout_thread)
            t_stderr = threading.Thread(target=stderr_thread)
            t_stdout.daemon = True
            t_stderr.daemon = True
            t_stdout.start()
            t_stderr.start()
            
            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    proc.kill()
                    proc.wait()
                    err_msg = (
                        f"\nScript execution timed out after {timeout_seconds} seconds. "
                        "The script was terminated.\n"
                    )
                    stderr_acc.append(err_msg)
                    yield ("stderr", err_msg)
                    break
                
                try:
                    item = chunk_queue.get(timeout=0.1)
                except queue_module.Empty:
                    if proc.poll() is not None:
                        t_stdout.join(timeout=1)
                        t_stderr.join(timeout=1)
                        while True:
                            try:
                                item = chunk_queue.get_nowait()
                            except queue_module.Empty:
                                break
                            stream_type, chunk = item
                            chunk_bytes = len(chunk.encode('utf-8'))
                            if stream_type == "stdout":
                                if stdout_bytes_acc + chunk_bytes <= max_output_bytes:
                                    stdout_acc.append(chunk)
                                    stdout_bytes_acc += chunk_bytes
                                    yield ("stdout", chunk)
                                else:
                                    stdout_truncated = True
                            else:
                                if stderr_bytes_acc + chunk_bytes <= max_output_bytes:
                                    stderr_acc.append(chunk)
                                    stderr_bytes_acc += chunk_bytes
                                    yield ("stderr", chunk)
                                else:
                                    stderr_truncated = True
                        break
                    continue
                
                stream_type, chunk = item
                chunk_bytes = len(chunk.encode('utf-8'))
                if stream_type == "stdout":
                    if stdout_bytes_acc + chunk_bytes <= max_output_bytes:
                        stdout_acc.append(chunk)
                        stdout_bytes_acc += chunk_bytes
                        yield ("stdout", chunk)
                    else:
                        stdout_truncated = True
                else:
                    if stderr_bytes_acc + chunk_bytes <= max_output_bytes:
                        stderr_acc.append(chunk)
                        stderr_bytes_acc += chunk_bytes
                        yield ("stderr", chunk)
                    else:
                        stderr_truncated = True
            
            return_code = proc.returncode if proc.returncode is not None else 0
            
        except Exception as e:
            err_msg = f"ERROR: Failed to execute script: {e}\n"
            stderr_acc.append(err_msg)
            yield ("stderr", err_msg)
            return_code = 1
        finally:
            if temp_exec_dir and temp_exec_dir.exists():
                try:
                    shutil.rmtree(temp_exec_dir)
                except Exception:
                    pass
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value
        
        stdout_str = "".join(stdout_acc)
        stderr_str = "".join(stderr_acc)
        if stdout_truncated or stderr_truncated:
            stderr_str += f"\n[WARNING: Output truncated due to size limit ({max_output_bytes} bytes)]\n"
        
        yield ("done", json.dumps({
            "return_code": return_code,
            "stdout": stdout_str,
            "stderr": stderr_str,
        }))
    
    @staticmethod
    def _copy_input_files(
        input_paths: List[str],
        runbook_dir: Path,
        temp_exec_dir: Path
    ) -> List[str]:
        """
        Copy input files/folders to temporary execution directory.
        
        Args:
            input_paths: List of input file/folder paths (relative to runbook directory)
            runbook_dir: Path to the directory containing the runbook
            temp_exec_dir: Temporary execution directory where files should be copied
            
        Returns:
            List of error messages (empty if successful)
        """
        errors = []
        runbook_dir_resolved = runbook_dir.resolve()
        
        if not input_paths:
            return errors
        
        for input_path_str in input_paths:
            try:
                # Resolve path relative to runbook directory
                source_path = (runbook_dir / input_path_str).resolve()
                
                # Security: Validate that resolved path is within runbook_dir
                # This prevents directory traversal attacks (e.g., ../../../etc/passwd)
                try:
                    if not source_path.is_relative_to(runbook_dir_resolved):
                        errors.append(f"Input path escapes runbook directory: {input_path_str}")
                        logger.warning(f"Rejected input path that escapes runbook directory: {input_path_str}")
                        continue
                except AttributeError:
                    # Python < 3.9: use alternative check
                    try:
                        source_path.relative_to(runbook_dir_resolved)
                    except ValueError:
                        errors.append(f"Input path escapes runbook directory: {input_path_str}")
                        logger.warning(f"Rejected input path that escapes runbook directory: {input_path_str}")
                        continue
                
                # Verify source exists
                if not source_path.exists():
                    errors.append(f"Input file/folder does not exist: {input_path_str}")
                    logger.warning(f"Input file/folder does not exist: {input_path_str}")
                    continue
                
                # Determine destination path (flatten to temp_exec_dir root)
                dest_path = temp_exec_dir / source_path.name
                
                # Copy file or directory
                if source_path.is_file():
                    shutil.copy2(source_path, dest_path)
                    logger.debug(f"Copied input file: {input_path_str} -> {dest_path}")
                elif source_path.is_dir():
                    shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                    logger.debug(f"Copied input directory: {input_path_str} -> {dest_path}")
                else:
                    errors.append(f"Input path is neither file nor directory: {input_path_str}")
                    logger.warning(f"Input path is neither file nor directory: {input_path_str}")
                    
            except Exception as e:
                error_msg = f"Failed to copy input {input_path_str}: {e}"
                errors.append(error_msg)
                logger.error(error_msg, exc_info=True)
        
        return errors
    
    @staticmethod
    def _truncate_output(output: str, max_bytes: int) -> Tuple[str, bool]:
        """
        Truncate output to max_bytes while preserving UTF-8 boundaries.
        
        Args:
            output: Output string to truncate
            max_bytes: Maximum size in bytes
            
        Returns:
            tuple: (truncated_output, was_truncated)
        """
        output_bytes = len(output.encode('utf-8'))
        if output_bytes <= max_bytes:
            return output, False
        
        # Truncate to max size, preserving UTF-8 boundaries
        output_encoded = output.encode('utf-8')
        truncated_bytes = output_encoded[:max_bytes]
        # Try to decode, if it fails remove last byte until valid
        while True:
            try:
                truncated_output = truncated_bytes.decode('utf-8')
                break
            except UnicodeDecodeError:
                truncated_bytes = truncated_bytes[:-1]
        
        return truncated_output, True

