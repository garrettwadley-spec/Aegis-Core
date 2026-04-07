param(
    [int]$Count = 20
)

# Where the backtest CSVs live
$BacktestsDir = "C:\Users\garre\cloud-trader\aegis_start_work_pack\data\backtests"

# Orchestrator chat endpoint
$Orchestrator = "http://127.0.0.1:8002/chat"

# Where we will save PNGs locally
$OutDir = Join-Path $BacktestsDir "plots"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$headers = @{ "Content-Type" = "application/json" }

function Find-Base64Image {
    param(
        [Parameter(Mandatory = $true)]
        $Obj
    )

    if ($null -eq $Obj) { return $null }

    # Direct string candidate
    if ($Obj -is [string]) {
        if ($Obj.Length -gt 1000 -and $Obj -match '^[A-Za-z0-9+/]+=*$') {
            return $Obj
        }
        return $null
    }

    # Enumerables (arrays, lists)
    if ($Obj -is [System.Collections.IEnumerable] -and -not ($Obj -is [string])) {
        foreach ($item in $Obj) {
            $r = Find-Base64Image -Obj $item
            if ($r) { return $r }
        }
        return $null
    }

    # Objects with properties
    foreach ($prop in $Obj.PSObject.Properties) {
        $r = Find-Base64Image -Obj $prop.Value
        if ($r) { return $r }
    }

    return $null
}

# Take newest CSVs
$csvs = Get-ChildItem $BacktestsDir -Filter *.csv |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First $Count

foreach ($f in $csvs) {
    $title = ($f.BaseName) -replace "_", " "
    Write-Host ("Plotting: {0}" -f $f.Name)

    $msgObj = @{
        tool = "plot.equity"
        args = @{
            csv_path = $f.FullName
            title    = $title
        }
    }

    $bodyObj = @{
        message = ($msgObj | ConvertTo-Json -Compress)
    }

    try {
        $resp = Invoke-RestMethod -Method Post -Uri $Orchestrator -Headers $headers -Body ($bodyObj | ConvertTo-Json -Compress)

        # First, try the old-style png_path if it ever appears
        if ($resp.result -and $resp.result.png_path) {
            $pngPath = $resp.result.png_path
            Write-Host ("    -> Server saved at: {0}" -f $pngPath) -ForegroundColor Green
            continue
        }

        # Otherwise, hunt for a base64 image string anywhere in result
        $b64 = Find-Base64Image -Obj $resp.result

        if ($b64) {
            $bytes   = [Convert]::FromBase64String($b64)
            $localPng = Join-Path $OutDir ($f.BaseName + ".png")
            [IO.File]::WriteAllBytes($localPng, $bytes)
            Write-Host ("    -> Saved PNG: {0}" -f $localPng) -ForegroundColor Green
        }
        else {
            Write-Host "    -> No png_path or image data in response" -ForegroundColor Yellow
            $rawPath = Join-Path $OutDir "last_response.json"
            $resp | ConvertTo-Json -Depth 10 | Out-File -FilePath $rawPath -Encoding utf8
            Write-Host ("    -> Raw response logged to {0}" -f $rawPath) -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host (" !! Error: {0}" -f $_.Exception.Message) -ForegroundColor Red
    }

    Start-Sleep -Milliseconds 200
}
