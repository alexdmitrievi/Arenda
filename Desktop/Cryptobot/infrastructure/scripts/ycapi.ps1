# Yandex Cloud REST API client (PowerShell).
#
# Workaround for a skewed local clock: the yc CLI's JWT is rejected by YC
# because the machine time is ahead of real time. This module signs its own
# JWTs with iat/exp computed from an independent time source, then drives the
# IAM / VPC / Compute REST APIs directly.

$script:YcSaKeyFile = "C:\Users\HP\Desktop\Cryptobot\infrastructure\secrets\yc-sa-key.json"
$script:YcTokenFile = "C:\Users\HP\AppData\Local\Temp\opencode\yc-iam-token.json"
$script:YcFolderId = "b1goj7fnq9pid3n9q257"

function ConvertTo-Base64Url([byte[]]$bytes) {
    $s = [Convert]::ToBase64String($bytes)
    return $s.Replace('+', '-').Replace('/', '_').TrimEnd('=')
}

function Get-YcRealUnixTime {
    # independent source of real UTC time (the local clock cannot be trusted)
    foreach ($url in @(
        'https://timeapi.io/api/time/current/zone?timeZone=UTC',
        'https://worldtimeapi.org/api/timezone/Etc/UTC'
    )) {
        try {
            $resp = Invoke-RestMethod -Uri $url -TimeoutSec 15
            if ($url -like '*timeapi*') {
                $dt = [DateTime]$resp.dateTime
                if ($dt.Kind -eq [DateTimeKind]::Unspecified) { $dt = [DateTime]::SpecifyKind($dt, [DateTimeKind]::Utc) }
                return [int64]([DateTimeOffset]$dt.ToUniversalTime()).ToUnixTimeSeconds()
            } else {
                $dt = [DateTime]::Parse($resp.utc_datetime, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)
                return [int64]([DateTimeOffset]$dt.ToUniversalTime()).ToUnixTimeSeconds()
            }
        } catch { }
    }
    throw "Cannot obtain real UTC time from any source"
}

function Get-YcIamToken {
    # reuse cached token while it is valid (exp - 5 min margin)
    if (Test-Path $script:YcTokenFile) {
        try {
            $cached = Get-Content $script:YcTokenFile -Raw | ConvertFrom-Json
            $realNow = Get-YcRealUnixTime
            if ($cached.exp -gt ($realNow + 300)) {
                return $cached.token
            }
        } catch { }
    }

    $key = Get-Content $script:YcSaKeyFile -Raw | ConvertFrom-Json
    $saId = $key.service_account_id
    $keyId = $key.id
    $pem = $key.private_key

    $header = @{ alg = "PS256"; typ = "JWT"; kid = $keyId } | ConvertTo-Json -Compress
    $realNow = Get-YcRealUnixTime
    $payload = @{
        aud = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
        iss = $saId
        iat = $realNow
        exp = $realNow + 3590
    } | ConvertTo-Json -Compress

    $b64h = ConvertTo-Base64Url ([Text.Encoding]::UTF8.GetBytes($header))
    $b64p = ConvertTo-Base64Url ([Text.Encoding]::UTF8.GetBytes($payload))
    $signingInput = "$b64h.$b64p"

    $rsa = [System.Security.Cryptography.RSA]::Create()
    $rsa.ImportFromPem($pem)
    $sig = $rsa.SignData(
        [Text.Encoding]::UTF8.GetBytes($signingInput),
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pss
    )
    $b64s = ConvertTo-Base64Url $sig
    $jwt = "$signingInput.$b64s"

    $body = @{ jwt = $jwt } | ConvertTo-Json -Compress
    $resp = Invoke-RestMethod -Method Post `
        -Uri "https://iam.api.cloud.yandex.net/iam/v1/tokens" `
        -ContentType "application/json" -Body $body -TimeoutSec 30

    @{ token = $resp.iamToken; exp = $resp.expiresAt } |
        ConvertTo-Json | Set-Content $script:YcTokenFile
    return $resp.iamToken
}

function Invoke-YcGet([string]$uri) {
    $token = Get-YcIamToken
    $headers = @{ Authorization = "Bearer $token" }
    Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 60
}

function Invoke-YcPost([string]$uri, $bodyObj) {
    $token = Get-YcIamToken
    $headers = @{ Authorization = "Bearer $token" }
    $body = ($bodyObj | ConvertTo-Json -Compress -Depth 20)
    Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 60
}

function Invoke-YcPatch([string]$uri, $bodyObj) {
    $token = Get-YcIamToken
    $headers = @{ Authorization = "Bearer $token" }
    $body = ($bodyObj | ConvertTo-Json -Compress -Depth 20)
    Invoke-RestMethod -Method Patch -Uri $uri -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 60
}

function Invoke-YcDelete([string]$uri) {
    $token = Get-YcIamToken
    $headers = @{ Authorization = "Bearer $token" }
    Invoke-RestMethod -Method Delete -Uri $uri -Headers $headers -TimeoutSec 60
}

function Wait-YcOperation([string]$opId, [int]$timeoutSec = 300) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        $op = Invoke-YcGet "https://operation.api.cloud.yandex.net/operations/$opId"
        if ($op.done) {
            if ($op.error) {
                throw "YC operation $opId failed: $($op.error.message) $($op.error.code)"
            }
            return $op
        }
        Start-Sleep -Seconds 5
    }
    throw "YC operation $opId timed out"
}
