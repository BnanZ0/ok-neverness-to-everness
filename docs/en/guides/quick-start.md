# Quick start

1. Review [Before you start](../getting-started/configuration.md).
2. Launch ok-nte.
3. Enter the level or scene you want to automate.
4. Select a task and click **Start** in the application.

If screen recognition fails, stop the task first. Check the resolution, graphics settings, keybindings, and game-window state before starting again.

## Command-line arguments

```bash
# Run the second task after startup, then exit when it completes
ok-nte.exe -t 2 -e
```

- `-t` or `--task`: Run the N-th task in the task list after startup; `1` is the first task.
- `-e` or `--exit`: Exit after the task completes.

!!! warning
    Task numbers depend on the current application task list. Confirm the target task in the UI before automating startup.
