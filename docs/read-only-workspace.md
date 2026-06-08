# Worktree Read-Only Troubleshooting

*English: this document · 한국어: [read-only-workspace.ko.md](read-only-workspace.ko.md)*

Remote AI Coder runs AI work inside a **detached Git worktree**. A read-only failure usually comes from either the filesystem being unwritable or an AI CLI refusing edits through its own sandbox or policy. Use this checklist to narrow it down.

## 1. Understand The App Checks

1. **Worktree write check**  
   The app creates and removes a temporary file inside the Job worktree path, such as `~/.remote-coder/worktrees/<project>/<job_id>`, to verify OS-level write access. If this fails, the Job fails in the `git_worktree` stage.

2. **Runner output plus Git changes**  
   Even if Claude or Codex exits with code 0, the Job is treated as failed when stdout/stderr contains terms such as `read-only`, `readonly`, `읽기 전용`, or `수정 불가` and Git has no changed files.

Start with the Telegram failure stage and the raw log at `~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`.

## 2. Filesystem Issues

### 2.1 Directory Permissions And Ownership

- The OS user running the server, for example through `uvicorn`, must be able to create directories and write files under `~/.remote-coder/worktrees/`.
- Test this as the same user by creating a temporary file under the worktree base path.
- If needed, move `REMOTE_CODER_HOME` to a path owned by that user and writable by that user. Prefer correct ownership over broad `777` permissions.

### 2.2 Read-Only Mounts

- External disks, network volumes, or security/sync tools can mount or lock directories as read-only.
- Move `REMOTE_CODER_HOME` to a writable local disk path if the worktree base lives under a restricted mount.

### 2.3 Other Process Conflicts

- Backup or cloud-sync tools can lock the worktree directory. Exclude the worktree base path from those tools or move it outside synced directories.

## 3. AI CLI Issues

- If disk permissions look fine but the CLI still says read-only, run a direct smoke test as the same user on the same machine.
- Follow the [AI runner guide](ai-runners.md).
- **Codex only**: if the terminal shows `sandbox: read-only`, the Codex CLI sandbox may be blocking edits. Remote AI Coder defaults to `workspace-write`, but check whether the admin UI `codex_sandbox` setting is `read-only`.
- Also check login state, `PATH`, CLI version, and provider policy changes.

## 4. Relevant Settings

- **Worktree base**: `~/.remote-coder/worktrees/<project>/` is the effective root. Change it by moving `REMOTE_CODER_HOME` to a writable path.
- **Conversation SQLite (`CONVERSATION_DB_PATH`)** stores context and is unrelated to worktree writability.

## 5. Quick Checklist

1. Check the Job failure stage (`git_worktree` vs `runner`, etc.).
2. Inspect stdout/stderr in `~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`.
3. Confirm that the server OS user can write under `~/.remote-coder/worktrees/`.
4. Check mount options and sync/backup tools.
5. Run the AI CLI directly in the same environment.

If all checks pass and the problem remains, check the CLI release notes or provider support channels next.
