Write-Host "Starting Aegis run..."

cd C:\Users\garre\cloud-trader

Write-Host "Running strategy..."
python -m aegis.discovery.strategy_runner

Write-Host "Checking git status..."
git status

Write-Host "Done. Review changes manually before committing."