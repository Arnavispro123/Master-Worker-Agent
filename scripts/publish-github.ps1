param([string]$RepoUrl = "")
# Publish Jarvis to GitHub. Usage: .\scripts\publish-github.ps1 -RepoUrl "https://github.com/YOU/jarvis.git"
$ErrorActionPreference = "Stop"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "git not found. Install it with:" -ForegroundColor Yellow
  Write-Host "  winget install --id Git.Git -e --source winget" -ForegroundColor Cyan
  Write-Host "Then re-run this script." -ForegroundColor Yellow
  exit 1
}
if (-not $RepoUrl) {
  Write-Host "No -RepoUrl given. I initialized git + committed locally." -ForegroundColor Yellow
  Write-Host 'Run: .\scripts\publish-github.ps1 -RepoUrl "https://github.com/YOU/jarvis.git"' -ForegroundColor Cyan
}
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".git")) { git init; git branch -M main }
git add .
git commit -m "feat: JARVIS v1 — voice, vision, control, multi-provider AI" 2>$null
if ($RepoUrl) {
  git remote remove origin 2>$null
  git remote add origin $RepoUrl
  git push -u origin main
  Write-Host "Published to $RepoUrl" -ForegroundColor Green
} else {
  Write-Host "Committed locally. Create a repo on github.com/new then push:" -ForegroundColor Green
  Write-Host '  git remote add origin https://github.com/YOU/jarvis.git; git push -u origin main' -ForegroundColor Cyan
}
