[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $MicrobotRoot,

    [string] $UpstreamRoot,

    [switch] $SkipTests,

    [switch] $SkipMicrobotValidation
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($UpstreamRoot)) {
    $UpstreamRoot = Join-Path $PSScriptRoot ".upstream\shortest-path-tooling"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

$manifestPath = Join-Path $PSScriptRoot "transport_sync\sync_manifest.json"
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$baselineRoot = Join-Path $MicrobotRoot "runelite-client\src\main\resources\net\runelite\client\plugins\microbot\shortestpath"
$outputRoot = Join-Path $PSScriptRoot "build\transport-sync\generated"
$reportRoot = Join-Path $PSScriptRoot "build\transport-sync\report"

if (-not (Test-Path -LiteralPath $baselineRoot -PathType Container)) {
    throw "Microbot shortest-path resources not found: $baselineRoot"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required but was not found on PATH."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ is required but was not found on PATH."
}

if (-not (Test-Path -LiteralPath (Join-Path $UpstreamRoot ".git"))) {
    $parent = Split-Path -Parent $UpstreamRoot
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Invoke-Checked git clone --filter=blob:none $manifest.tooling_repository $UpstreamRoot
}

Invoke-Checked git -C $UpstreamRoot fetch origin --prune
Invoke-Checked git -C $UpstreamRoot checkout --detach $manifest.tooling_commit
Invoke-Checked git -C $UpstreamRoot submodule sync --recursive
Invoke-Checked git -C $UpstreamRoot submodule update --init --recursive

$dataRoot = Join-Path $UpstreamRoot "shortest-path"
Invoke-Checked git -C $dataRoot fetch origin --prune
Invoke-Checked git -C $dataRoot checkout --detach $manifest.data_commit

if (-not $SkipTests) {
    Invoke-Checked python -m unittest discover -s (Join-Path $PSScriptRoot "tests") -p "test_*.py"
}

Invoke-Checked python -m transport_sync.sync `
    --upstream-root $UpstreamRoot `
    --baseline-root $baselineRoot `
    --output-root $outputRoot `
    --report-root $reportRoot

if (-not $SkipMicrobotValidation) {
    $gradle = Join-Path $MicrobotRoot "gradlew.bat"
    if (-not (Test-Path -LiteralPath $gradle -PathType Leaf)) {
        throw "Microbot Gradle wrapper not found: $gradle"
    }
    Push-Location $MicrobotRoot
    try {
        Invoke-Checked $gradle :client:validateTransportSync `
            "-PtransportSyncGeneratedDir=$outputRoot" `
            --console=plain
        Invoke-Checked $gradle :client:runUnitTests `
            --tests net.runelite.client.plugins.microbot.shortestpath.ShortestPathGoldenRouteBaselineTest `
            --tests net.runelite.client.plugins.microbot.shortestpath.TransportResourceLoadTest `
            --console=plain
    }
    finally {
        Pop-Location
    }
}

$summary = Join-Path $reportRoot "summary.md"
Write-Host ""
Write-Host "Transport sync completed."
Write-Host "Generated resources: $outputRoot"
Write-Host "Semantic report:    $summary"
if ($SkipMicrobotValidation) {
    Write-Warning "Microbot parser and golden-route validation was skipped."
}
