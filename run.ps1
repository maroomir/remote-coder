# PowerShell 실행 정책 때문에 막히면 다음 명령으로 현재 프로세스에서만 허용할 수 있습니다.
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# Windows PowerShell 5.x 콘솔의 인코딩 설정에 따라 한글/이모지가 깨질 수 있어
# 실행 중 출력 메시지는 ASCII 위주로 유지합니다.

$ErrorActionPreference = "Stop"

Write-Host "[INFO] Preparing to run Remote AI Coder..."

$ngrokProcess = $null


function Stop-NgrokProcesses {
    $processes = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
    if ($processes) {
        $processes | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}


function Get-NgrokExecutablePath {
    $ngrokCommand = Get-Command "ngrok" -ErrorAction SilentlyContinue
    if (-not $ngrokCommand) {
        $ngrokCommand = Get-Command "ngrok.exe" -ErrorAction SilentlyContinue
    }

    if (-not $ngrokCommand) {
        throw "[ERROR] ngrok executable was not found. Install ngrok and make sure ngrok.exe is available in PATH, then open a new PowerShell window."
    }

    return $ngrokCommand.Source
}


function Activate-CondaEnvironment {
    $condaCommand = Get-Command "conda" -ErrorAction SilentlyContinue
    if (-not $condaCommand) {
        throw "[ERROR] conda command was not found. Install Conda and make sure it is available in PATH."
    }

    $condaBase = (& conda info --base 2>$null)
    if (-not $condaBase) {
        throw "[ERROR] Could not detect Conda base path. Check your Conda installation."
    }

    $condaHook = Join-Path $condaBase "shell\condabin\conda-hook.ps1"
    if (-not (Test-Path $condaHook)) {
        throw "[ERROR] Conda PowerShell hook was not found: $condaHook"
    }

    . $condaHook
    conda activate remote-coder

    if ($LASTEXITCODE -ne 0) {
        throw "[ERROR] Conda environment 'remote-coder' was not found."
    }
}


function Get-NgrokHttpsUrl {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -Method Get -TimeoutSec 5
        $httpsTunnel = $response.tunnels | Where-Object { $_.public_url -like "https*" } | Select-Object -First 1

        if ($httpsTunnel) {
            return $httpsTunnel.public_url
        }

        return $null
    }
    catch {
        return $null
    }
}


try {
    # 1. Conda 환경 활성화
    Activate-CondaEnvironment
    Write-Host "[OK] Conda environment activated: remote-coder"

    # ngrok 실행 파일 확인
    $ngrokPath = Get-NgrokExecutablePath
    Write-Host "[OK] ngrok found: $ngrokPath"

    # 2. AuthToken 확인 (ngrok config)
    # 최근 ngrok은 로그인(AuthToken) 없이 터널을 열 수 없습니다.
    $ngrokConfigOut = & $ngrokPath config check 2>&1
    if ([string]::IsNullOrWhiteSpace($ngrokConfigOut) -or $ngrokConfigOut -match "no authtoken configured") {
        throw "[ERROR] ngrok AuthToken is missing. Run 'ngrok config add-authtoken <token>' first. (Sign up at https://dashboard.ngrok.com)"
    }

    # 3. 기존 ngrok 종료 (충돌 방지)
    Stop-NgrokProcesses

    # 4. ngrok 백그라운드 실행 (포트 8000)
    # 디버깅을 위해 자체 log 옵션을 이용해 파일에 로그를 씁니다 (표준출력 리다이렉션 충돌 회피)
    Write-Host "[INFO] Starting ngrok tunnel on port 8000..."
    $ngrokLogPath = Join-Path (Get-Location) "ngrok.log"
    $ngrokProcess = Start-Process -FilePath $ngrokPath -ArgumentList @("http", "8000", "--log=$ngrokLogPath") -WindowStyle Hidden -PassThru

    # 5. ngrok URL 추출 (재시도 로직 포함)
    $publicUrl = $null
    $maxRetries = 10
    $retryCount = 0

    while ([string]::IsNullOrWhiteSpace($publicUrl) -and $retryCount -lt $maxRetries) {
        Start-Sleep -Seconds 1
        $publicUrl = Get-NgrokHttpsUrl
        $retryCount++
    }

    if ([string]::IsNullOrWhiteSpace($publicUrl)) {
        $errorMessage = "[ERROR] Could not read ngrok public URL after $maxRetries seconds. Check your ngrok AuthToken, configuration, or internet connection."
        
        # 로그 파일 분석을 통해 너무 오래된 버전 문제인지 확인
        if (Test-Path $ngrokLogPath) {
            $logContent = Get-Content $ngrokLogPath -Raw
            if ($logContent -match "version .* is too old") {
                $errorMessage = "[ERROR] Your ngrok version is too old and was rejected by the server. Please run 'ngrok update' to upgrade it, then try again."
            } elseif ($logContent -match "ERR_NGROK_108") {
                $errorMessage = "[ERROR] ngrok tunnel session failed. You might have another ngrok session running elsewhere on this free account."
            }
        }
        
        throw $errorMessage
    }

    Write-Host "[OK] ngrok HTTPS URL: $publicUrl"

    # 5. 웹훅 등록 스크립트 실행
    python scripts/set_webhook.py $publicUrl
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] Failed to register webhook. Continuing to start the server in case an existing webhook is still valid."
    }

    # 6. FastAPI 서버 실행
    Write-Host "[INFO] Starting FastAPI server..."
    uvicorn app.main:app --reload
}
finally {
    Write-Host ""
    Write-Host "[INFO] Stopping server and ngrok tunnel..."

    if ($ngrokProcess -and -not $ngrokProcess.HasExited) {
        Stop-Process -Id $ngrokProcess.Id -Force -ErrorAction SilentlyContinue
    }
}