param(
    [Parameter(Mandatory = $true)][string]$Image,
    [Parameter(Mandatory = $true)][string]$RuntimeClass,
    [string]$Output = "infra/k8s/agent-sandbox.rendered.yaml"
)

$ErrorActionPreference = "Stop"
if ($Image -notmatch '^[a-zA-Z0-9._:/-]+@sha256:[a-fA-F0-9]{64}$') {
    throw "Image must use an immutable sha256 digest"
}
if ($RuntimeClass -notmatch '^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$') {
    throw "RuntimeClass must be a Kubernetes name"
}
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$template = Join-Path $workspace "infra/k8s/agent-sandbox.yaml.template"
$target = [System.IO.Path]::GetFullPath((Join-Path $workspace $Output))
if (-not $target.StartsWith($workspace + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output must stay inside the workspace"
}
$rendered = [System.IO.File]::ReadAllText($template)
$rendered = $rendered.Replace('${AGENT_RUNTIME_IMAGE}', $Image)
$rendered = $rendered.Replace('${SANDBOX_RUNTIME_CLASS}', $RuntimeClass)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($target)) | Out-Null
[System.IO.File]::WriteAllText($target, $rendered,
        [System.Text.UTF8Encoding]::new($false))
Write-Output $target
