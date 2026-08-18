"""System & File domain tools — OS interaction, file ops, shell commands."""

# ── Shell & Process ──
from .shell import (
    run_shell_command_validate, run_shell_command_execute, RUN_SHELL_COMMAND_SCHEMA,
    start_bg_process_validate, start_bg_process_execute, START_BG_PROCESS_SCHEMA,
    get_process_logs_validate, get_process_logs_execute, GET_PROCESS_LOGS_SCHEMA,
    kill_process_validate, kill_process_execute, KILL_PROCESS_SCHEMA,
)

# ── File Read ──
from .fs_read import (
    list_files_validate, list_files_execute, LIST_FILES_SCHEMA,
    read_file_validate, read_file_execute, READ_FILE_SCHEMA,
    search_files_validate, search_files_execute, SEARCH_FILES_SCHEMA,
)

# ── File Write ──
from .fs_write import (
    create_validate, create_execute, CREATE_SCHEMA,
    write_validate, write_execute, WRITE_SCHEMA,
    edit_by_lines_validate, edit_by_lines_execute, EDIT_BY_LINES_SCHEMA,
)

# ── File Manage ──
from .fs_manage import (
    delete_path_validate, delete_path_execute, DELETE_PATH_SCHEMA,
    rename_move_validate, rename_move_execute, RENAME_MOVE_SCHEMA,
    download_file_validate, download_file_execute, DOWNLOAD_FILE_SCHEMA,
)

# ── State ──
from .state import (
    change_dir_validate, change_dir_execute, CHANGE_DIR_SCHEMA,
    get_cwd_validate, get_cwd_execute, GET_CWD_SCHEMA,
)

# ── Info ──
from .info import (
    get_system_info_validate, get_system_info_execute, GET_SYSTEM_INFO_SCHEMA,
)


def register_system_tools(executor) -> None:
    """Register all system/file-domain tools with the executor."""

    # ═══════════════════════════════════════════════════
    # Shell & Process
    # ═══════════════════════════════════════════════════

    executor.register(
        name="run_shell_command",
        impl=run_shell_command_execute,
        domain="system",
        schema=RUN_SHELL_COMMAND_SCHEMA,
        validate_fn=run_shell_command_validate,
        # TODO: Add verify_fn — check return_code, parse stderr for known
        # error patterns, verify expected output files exist, etc.
        supports_verification=False,
        cost=4,
        description="Run a shell command and return stdout/stderr",
    )

    executor.register(
        name="start_background_process",
        impl=start_bg_process_execute,
        domain="system",
        schema=START_BG_PROCESS_SCHEMA,
        validate_fn=start_bg_process_validate,
        supports_verification=False,
        cost=4,
        description="Start a long-running background process (e.g. dev server). "
                    "Max 3 concurrent. Returns early output for crash detection.",
    )

    executor.register(
        name="get_process_logs",
        impl=get_process_logs_execute,
        domain="system",
        schema=GET_PROCESS_LOGS_SCHEMA,
        validate_fn=get_process_logs_validate,
        supports_verification=False,
        cost=1,
        description="Read recent stdout/stderr from a managed background process",
    )

    executor.register(
        name="kill_process",
        impl=kill_process_execute,
        domain="system",
        schema=KILL_PROCESS_SCHEMA,
        validate_fn=kill_process_validate,
        supports_verification=False,
        cost=2,
        description="Terminate a managed background process by PID",
    )

    # ═══════════════════════════════════════════════════
    # File Read
    # ═══════════════════════════════════════════════════

    executor.register(
        name="list_files",
        impl=list_files_execute,
        domain="system",
        schema=LIST_FILES_SCHEMA,
        validate_fn=list_files_validate,
        supports_verification=False,
        cost=1,
        description="List files and folders in a directory",
    )

    executor.register(
        name="read_file",
        impl=read_file_execute,
        domain="system",
        schema=READ_FILE_SCHEMA,
        validate_fn=read_file_validate,
        supports_verification=False,
        cost=1,
        description="Read file contents by line range, with optional tail mode",
    )

    executor.register(
        name="search_files",
        impl=search_files_execute,
        domain="system",
        schema=SEARCH_FILES_SCHEMA,
        validate_fn=search_files_validate,
        supports_verification=False,
        cost=3,
        description="Search for text or regex pattern in files under a directory. "
                    "Skips binary files, node_modules, .git, etc.",
    )

    # ═══════════════════════════════════════════════════
    # File Write
    # ═══════════════════════════════════════════════════

    executor.register(
        name="create_file_or_folder",
        impl=create_execute,
        domain="system",
        schema=CREATE_SCHEMA,
        validate_fn=create_validate,
        supports_verification=False,
        cost=2,
        description="Create a new file or directory",
    )

    executor.register(
        name="write_to_file",
        impl=write_execute,
        domain="system",
        schema=WRITE_SCHEMA,
        validate_fn=write_validate,
        supports_verification=False,
        cost=2,
        description="Write or append content to a file (atomic for write/overwrite)",
    )

    executor.register(
        name="edit_file_by_lines",
        impl=edit_by_lines_execute,
        domain="system",
        schema=EDIT_BY_LINES_SCHEMA,
        validate_fn=edit_by_lines_validate,    # singular — matches source as-is
        supports_verification=False,
        cost=3,
        description="Replace a range of lines in a file. Use read_file first to see "
                    "line numbers, then specify start_line/end_line with new content.",
    )

    # ═══════════════════════════════════════════════════
    # File Manage
    # ═══════════════════════════════════════════════════

    executor.register(
        name="delete_path",
        impl=delete_path_execute,
        domain="system",
        schema=DELETE_PATH_SCHEMA,
        validate_fn=delete_path_validate,
        # TODO: Add verify_fn — check path no longer exists after deletion.
        # Simple: return VerifyResult(verified=not Path(path).exists(), ...)
        supports_verification=False,
        cost=4,
        description="Delete a file or folder (sends to Recycle Bin via send2trash). "
                    "Requires confirm=true.",
    )

    executor.register(
        name="rename_or_move",
        impl=rename_move_execute,
        domain="system",
        schema=RENAME_MOVE_SCHEMA,
        validate_fn=rename_move_validate,
        supports_verification=False,
        cost=2,
        description="Rename or move a file or folder",
    )

    executor.register(
        name="download_file",
        impl=download_file_execute,
        domain="system",
        schema=DOWNLOAD_FILE_SCHEMA,
        validate_fn=download_file_validate,
        supports_verification=False,
        cost=3,
        description="Download a file from a URL (native HTTP, bypasses browser). "
                    "Enforces size limit.",
    )

    # ═══════════════════════════════════════════════════
    # State
    # ═══════════════════════════════════════════════════

    executor.register(
        name="cd",
        impl=change_dir_execute,
        domain="system",
        schema=CHANGE_DIR_SCHEMA,
        validate_fn=change_dir_validate,
        supports_verification=False,
        cost=1,
        description="Change the working directory for subsequent shell commands",
    )

    executor.register(
        name="get_cwd",
        impl=get_cwd_execute,
        domain="system",
        schema=GET_CWD_SCHEMA,
        validate_fn=get_cwd_validate,
        supports_verification=False,
        cost=1,
        description="Get the current working directory",
    )

    # ═══════════════════════════════════════════════════
    # Info
    # ═══════════════════════════════════════════════════

    executor.register(
        name="get_system_info",
        impl=get_system_info_execute,
        domain="system",
        schema=GET_SYSTEM_INFO_SCHEMA,
        validate_fn=get_system_info_validate,
        supports_verification=False,
        cost=1,
        description="Get OS, CPU, memory, disk usage info",
    )

    print("[SystemTools] 16 system tools registered")
