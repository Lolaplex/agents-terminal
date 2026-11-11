# CLI

Installed command: `agents-terminal`. Machine-readable catalog: `python -m agents_terminal --help-json`. Side-effect fields are specified in [`METADATA.md`](METADATA.md).

No subcommand prints help. This package does not start a server.

Read-only commands observe the workspace root and do not spawn a process. They do not create the root, and they skip the PyPI update check so the process does not write the update cache. `write`, `edit`, and `run` are mutating; they may trigger the PyPI update check like `run` does.

## Root

The root is the same directory `run` would use as its working directory (`Policy.work_root()`):

1. Policy `cwd`, when set.
2. Otherwise `openshell_workspace`, `AGENTS_WORKDIR`, or the workspace workdir default (`<ws>/work`; `AGENTS_WORKSPACE_DIR`/`AGENTS_HOME/workspace` remain readable as deprecated aliases for one release).

Read-only commands and `write` / `edit` always stay inside that root. `run` is confined to it only when `AGENTS_WORKSPACE_LOCK` is on.

Paths may be relative to that root or absolute. After symlink resolution the real path must stay inside the root. `..`, a sibling prefix such as `<root>-evil`, and a symlink that resolves outside are rejected with `path escapes workspace root`. NUL, CR, and LF in a path are `invalid path` (exit 2).

Confinement is by resolved path. A hard link that already lives inside the root is readable. `stat` does not follow the final symlink, so a link that lives in the root is described even when its target is outside. `read` and `grep` follow a symlink path only when the target stays inside the root. Directory walks do not descend into symlinks.

The open starts from a file descriptor for the root and uses `O_NOFOLLOW` on every component, so the open cannot follow a symlink. Files are opened read-only. `stat` uses that same confinement: the parent directory is opened from the root fd, and the final name is `lstat`ed there. A final symlink is described and not opened.

If `O_NOFOLLOW` or `dir_fd` is unavailable, `list`, `read`, `grep`, and `stat` do not pass `dir_fd`. The real path must stay inside the root, and any symlink, junction, or other reparse point on that path is rejected before an open. An escape returns `path escapes workspace root` and no file contents. A confinement call that raises `TypeError` becomes `confinement unavailable`.

## Commands

### `list [PATH] [--json]`

List one directory. Text lines are `type`, `size`, `name`, and for a symlink the raw target, separated by tabs. `type` is `file`, `dir`, `symlink`, or `other`. JSON: `{"path", "entries": [{"name", "type", "size", "mtime", "target"?}]}`.

### `read PATH [--offset N] [--limit N] [--json]`

Read a UTF-8 text file. `--offset` is the 1-based starting line (default 1). `--limit` is the maximum number of lines (default 2000, maximum 20000). Text stdout is the selected text with no extra newline. An offset past EOF is empty and exit 0.

A NUL byte is `binary file`. The scan stops at 8 MiB and the returned text stops at 1 MiB; `truncated` is then true. JSON: `{"path", "offset", "limit", "line_count", "truncated", "content"}`.

### `grep PATTERN [PATH] [--glob GLOB] [--literal] [--ignore-case] [--max N] [--json]`

Search UTF-8 text. `search` is an alias. `PATTERN` is a Python regular expression unless `--literal`. `--glob` is a case-sensitive `fnmatch` against the workspace-relative path or the file name. `--max` defaults to 200 and cannot exceed 5000.

Text lines are `path:line:text`. No matches is exit 0. A directory walk skips binary files and symlink entries. Naming a binary file directly is `binary file`. JSON: `{"path", "matches": [{"path", "line", "text"}], "truncated"}`.

`truncated` means the output hit `--max`, a file byte cap (1 MiB), or a match line shortened at 2000 characters.

### `stat PATH [--json]`

`lstat` one path. Text is `path`, `type`, `size`, `mtime`, `mode`, and `target` when the path is a symlink. `mtime` is UTC `YYYY-MM-DDTHH:MM:SSZ`. `mode` is four octal digits. JSON includes `"target": null` for anything that is not a symlink.

### `write PATH [--stdin | --content TEXT] [--create-only] [--json]`

Write UTF-8 text to `PATH`. Exactly one of `--content` or `--stdin` is required; neither or both is exit 2. Missing parent directories are created inside the root. The write is atomic: a temp file in the same directory is replaced with `os.replace`.

An existing file keeps its line endings (CRLF stays CRLF, LF stays LF). A new file uses LF. `--create-only` fails with `exists` when the file already exists. A symlink, a directory, or a binary file (NUL byte) is refused and not overwritten.

Text stdout is `wrote <relpath> (<n> lines, <bytes> bytes)`. JSON: `{"path", "created", "lines", "bytes"}`.

### `edit PATH --old TEXT --new TEXT [--replace-all] [--stdin-json] [--json]`

Exact string replacement, no regular expressions. `--old` must match exactly once. Zero matches is `old text not found` (exit 1). More than one match without `--replace-all` is `old text matches N times; add context or pass --replace-all` (exit 1). The file is unchanged on either error. An empty `--old` is exit 2.

An exact match on the file's own bytes wins, so a file with mixed line endings keeps every byte it had and the diff stays local. Only when that finds nothing does matching fall back to line-ending tolerance: CRLF in the file then matches LF in `--old`, and the file is rewritten with its dominant line ending. `--stdin-json` reads `{"old": "...", "new": "..."}` from stdin, which is the path for multi-line edits without shell quoting. Passing `--stdin-json` together with `--old`/`--new` is exit 2. The write is atomic like `write`.

Text stdout is a unified diff (`difflib`, 3 lines of context) followed by `edited <relpath>: <k> replacement(s), lines <start>-<end>`. JSON: `{"path", "replacements", "first_line", "last_line", "diff"}`.

### `run -- <argv…>`

Execute that argv under the policy. The `--` is stripped. Missing argv exits 2. The process exit code is the child's exit code. Stdout is the driver's formatted result. This command is `mutating`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including no grep matches and a read past EOF |
| 1 | Not found, path escape, binary file, permission, wrong file type |
| 2 | Usage: bad offset, limit, max, pattern, content source, or edit arguments |

On failure the message is one stderr line and stdout is empty. In text mode a successful truncated read or search also prints `truncated` on stderr. `--json` keeps that flag in the object and leaves stderr empty on success.

## Errors

| Message | When |
| --- | --- |
| `path escapes workspace root` | Resolved path leaves the root, or the final open hits a symlink |
| `invalid path` | NUL, CR, LF, or a path that cannot be resolved |
| `not found` | Root or path does not exist. Nothing is created |
| `not a file` / `not a directory` | Wrong type, including fifos and device nodes |
| `binary file` | NUL byte in a direct read or direct grep |
| `empty pattern` / `invalid pattern` | Grep pattern (exit 2) |
| `exists` | `write --create-only` against an existing file |
| `old text not found` | `edit --old` matched nothing |
| `old text matches N times; add context or pass --replace-all` | `edit --old` matched more than once without `--replace-all` |
