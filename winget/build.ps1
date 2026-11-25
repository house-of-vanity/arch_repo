param([Parameter(Mandatory)][string] $Work)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

# Microsoft's IndexCreationTool, built from winget-cli v1.29.240.
$archive = Join-Path $Work 'tools.zip'
Invoke-WebRequest 'https://github.com/pl4nty/winget-pkgs-selfhost/releases/download/v1.29.240/AppInstallerCLIE2ETests.zip' -OutFile $archive
if ((Get-FileHash $archive).Hash -ne '839F48771E92B2BA48798DDC92B2C4EA443806760062F3F413043CB2040945D4') {
    throw 'IndexCreationTool archive checksum mismatch'
}
Expand-Archive $archive (Join-Path $Work 'tools')
$tools = Join-Path $Work 'tools/AppInstallerCLIE2ETests'
[xml] $identity = Get-Content (Join-Path $tools 'TestData/Package/AppxManifest.xml') -Raw
$now = [datetime]::UtcNow
$identity.Package.Identity.Name = 'Hexor.WinGet.Source'
$identity.Package.Identity.Publisher = 'CN=Hexor WinGet'
$identity.Package.Identity.Version = '{0}.{1}.{2}.{3}' -f $now.Year, $now.Month, $now.Day, [math]::Floor($now.TimeOfDay.TotalSeconds / 2)
$identity.Package.Properties.DisplayName = 'Hexor WinGet'
$identity.Package.Properties.PublisherDisplayName = 'Hexor'
$identity.Package.Applications.Application.VisualElements.DisplayName = 'Hexor WinGet'
$identity.Package.Applications.Application.VisualElements.Description = 'Hexor WinGet package catalog'
$manifest = Join-Path $Work 'AppxManifest.xml'
$identity.Save($manifest)

$config = Join-Path $Work 'source.json'
@{
    AppxManifest = $manifest.Replace('\', '/')
    LocalManifests = @( (Join-Path $Work 'manifests').Replace('\', '/') )
    WorkingDirectory = (Join-Path $Work 'cache').Replace('\', '/')
} | ConvertTo-Json | Set-Content $config -Encoding utf8NoBOM
& (Join-Path $tools 'IndexCreationTool.exe') -f $config
