param(
    [Parameter(Mandatory = $true)] [string]$QgisPython,
    [Parameter(Mandatory = $true)] [string]$OutputRoot,
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RunId,
    [string]$QaSupport
)

$ErrorActionPreference = "Stop"
$smoke = Join-Path $PSScriptRoot "qgis_fixed_root_workflow_smoke.py"
$arguments = @("-s", "-B", $smoke, "--source-root", $SourceRoot, "--output-root", $OutputRoot)
if ($RunId) { $arguments += @("--run-id", $RunId) }
if ($QaSupport) { $arguments += @("--qa-support", $QaSupport) }

& $QgisPython @arguments
exit $LASTEXITCODE
