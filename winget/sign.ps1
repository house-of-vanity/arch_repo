param([Parameter(Mandatory)][string] $Work)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$subject = 'CN=Hexor WinGet'
if (!$env:WINGET_PFX_BASE64 -or !$env:WINGET_PFX_PASSWORD) {
    throw 'Set WINGET_PFX_BASE64 and WINGET_PFX_PASSWORD in arch_repo Actions secrets, then rerun this workflow.'
}
$pfx = Join-Path $Work 'signer.pfx'
try {
    [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINGET_PFX_BASE64))
    $password = ConvertTo-SecureString $env:WINGET_PFX_PASSWORD -AsPlainText -Force
    $cert = Import-PfxCertificate -FilePath $pfx -Password $password -CertStoreLocation Cert:\CurrentUser\My |
        Where-Object HasPrivateKey | Select-Object -First 1
} finally {
    if (Test-Path $pfx) { Remove-Item $pfx }
}
if ($cert.Subject -cne $subject) { throw "The source signing certificate must have subject $subject" }
$public = Join-Path $Work 'hexor-winget.cer'
Export-Certificate -Cert $cert -FilePath $public | Out-Null
Import-Certificate -FilePath $public -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
$sdk = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Directory |
    Where-Object { $_.Name -match '^10\.[\d.]+$' -and (Test-Path "$($_.FullName)\x64\signtool.exe") } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
$signTool = Join-Path $sdk.FullName 'x64/signtool.exe'
foreach ($name in 'source.msix','source2.msix') {
    $path = Join-Path $Work "cache/$name"
    & $signTool sign /fd SHA256 /sha1 $cert.Thumbprint $path
    & $signTool verify /pa $path
}
