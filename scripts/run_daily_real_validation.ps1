param(
    [ValidateSet("daily-full", "coffee-only", "daily-task-only", "gift-only")]
    [string]$Mode = "daily-full",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$ScriptPath = Join-Path $PSScriptRoot "run_daily_real_validation.py"
$PythonArgs = @($ScriptPath, "--mode", $Mode)
if ($Json) {
    $PythonArgs += "--json"
}

uv run python @PythonArgs
exit $LASTEXITCODE
