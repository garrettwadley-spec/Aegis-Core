Write-Host "Starting Aegis run..."

cd C:\Users\garre\cloud-trader

Write-Host "Running strategy..."
python -m aegis.discovery.strategy_runner

Write-Host "Committing changes..."
git add .
git commit -m "auto run update"
git push

Write-Host "DONE"