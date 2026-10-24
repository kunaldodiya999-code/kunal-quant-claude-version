<#
.SYNOPSIS
  Apply a Claude patch on a NEW branch, run the tests, and push only if they pass.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\apply_claude_patch.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\apply_claude_patch.ps1 -Patch "C:\Users\USER\Downloads\0001-xyz.patch" -NoPush

Never touches the original KunalQuant repo. Never force-pushes or resets.
Run it while the branch the patch builds on is checked out (Claude tells you which).
#>
param(
    [string]$Patch = "",
    [string]$PatchDir = "$env:USERPROFILE\Downloads",
    [switch]$NoPush
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Fail($msg) { Write-Host "STOP: $msg" -ForegroundColor Red; exit 1 }

if (git status --porcelain --untracked-files=no) { Fail "You have uncommitted changes. Commit or stash them first." }

if (-not $Patch) {
    $latest = Get-ChildItem $PatchDir -Filter "*.patch" -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { Fail "No .patch file found in $PatchDir." }
    $Patch = $latest.FullName
}
if (-not (Test-Path $Patch)) { Fail "Patch not found: $Patch" }

$base = (git rev-parse --abbrev-ref HEAD).Trim()
$slug = ([IO.Path]::GetFileNameWithoutExtension($Patch) -replace '^\d+-', '' -replace '[^A-Za-z0-9]+', '-').Trim('-').ToLower()
$branch = "claude/$slug"
if (git branch --list $branch) { $branch = "$branch-" + (Get-Date -Format "MMdd-HHmm") }

Write-Host "Base branch : $base"
Write-Host "Patch       : $Patch"
Write-Host "New branch  : $branch"

git fetch origin
git switch -c $branch
if ($LASTEXITCODE -ne 0) { Fail "Could not create branch $branch." }

git am --3way $Patch
if ($LASTEXITCODE -ne 0) {
    git am --abort
    git switch $base
    git branch -D $branch | Out-Null
    Fail "The patch did not apply cleanly on '$base'. Nothing was changed. Tell Claude which branch you were on."
}

& .\.venv\Scripts\python.exe -m pytest tests --ignore=tests/expiry_isolation_test.py -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests FAILED. The branch '$branch' exists locally but was NOT pushed." -ForegroundColor Red
    exit 1
}

if ($NoPush) { Write-Host "Tests passed. Not pushed (-NoPush)." -ForegroundColor Green; exit 0 }
git push -u origin $branch
if ($LASTEXITCODE -ne 0) { Fail "Push failed." }
Write-Host "Done. Tests passed and '$branch' is on GitHub." -ForegroundColor Green
