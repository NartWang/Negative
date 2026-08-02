# zhiji deploy script
Write-Host "===== zhiji deploy =====" -ForegroundColor Cyan
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

# 1. install python deps
Write-Host "[1/3] Installing Python dependencies..." -ForegroundColor Yellow
pip install -r src\engine\requirements.txt -q
Write-Host "      Done" -ForegroundColor Green

# 2. start backend
Write-Host "[2/3] Starting backend on port 8000..." -ForegroundColor Yellow
$backendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    python -m uvicorn main:app --host 0.0.0.0 --port 8000
} -ArgumentList "$projectDir\src\engine"
Write-Host "      Backend: http://localhost:8000" -ForegroundColor Green

# 3. start frontend
Write-Host "[3/3] Starting frontend on port 80..." -ForegroundColor Yellow
$frontendDir = "$projectDir\src\app\frontend\dist"
$frontendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    python -m http.server 80
} -ArgumentList $frontendDir
Write-Host "      Frontend: http://localhost:80" -ForegroundColor Green

Write-Host ""
Write-Host "===== All done! =====" -ForegroundColor Cyan
Write-Host "Frontend: http://47.110.85.59" -ForegroundColor Green
Write-Host "Backend:  http://47.110.85.59:8000" -ForegroundColor Green
Write-Host "Health:   http://47.110.85.59:8000/api/health" -ForegroundColor Green
Write-Host ""
Write-Host "Press any key to check status, or close this window (services keep running)" -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
Get-Job | Receive-Job -Keep