$ErrorActionPreference = "Stop"

$repo = "C:\Users\garre\cloud-trader"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "$repo\backups"
$backupFile = "$backupDir\aegis_checkpoint_$timestamp.zip"

cd $repo

Write-Host "`n[Aegis] Session stop started..." -ForegroundColor Cyan

if (!(Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

Write-Host "`n[Aegis] Git status:" -ForegroundColor Yellow
git status

Write-Host "`n[Aegis] Adding files..." -ForegroundColor Yellow
git add .

$commitMsg = "Aegis checkpoint $timestamp"

Write-Host "`n[Aegis] Committing: $commitMsg" -ForegroundColor Yellow
git commit -m "$commitMsg"

Write-Host "`n[Aegis] Pushing to GitHub..." -ForegroundColor Yellow
git push

Write-Host "`n[Aegis] Creating local backup..." -ForegroundColor Yellow
Compress-Archive `
    -Path "$repo\aegis", "$repo\docs", "$repo\memory", "$repo\scripts", "$repo\README.md", "$repo\.gitignore" `
    -DestinationPath $backupFile `
    -Force

Write-Host "`n[Aegis] Session checkpoint complete." -ForegroundColor Green
Write-Host "Backup created: $backupFile"