param(
    [Parameter(Mandatory = $true)][string]$TemplatePath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$PrivateKeyPath,
    [string]$ApprovalPath,
    [switch]$PrepareOnly
)

<##
Prepara e assina um catálogo de produção em duas etapas.

1. Use -PrepareOnly para gerar catalog.candidate.json e seu SHA-256.
2. Um segundo responsável aprova exatamente esse hash em approval.json.
3. Execute novamente com -ApprovalPath e -PrivateKeyPath. Só o catálogo
   aprovado é promovido para catalog.json e assinado.

A chave privada deve vir de cofre/caminho corporativo fora do repositório.
##>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "A assinatura exige PowerShell 7 (pwsh), que oferece importação segura de chave PEM."
}

function Require-String($Value, [string]$Field, [int]$Maximum = 500) {
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        throw "Campo obrigatório ausente: $Field"
    }
    $text = ([string]$Value).Trim()
    if ($text.Length -gt $Maximum) { throw "Campo acima do limite: $Field" }
    return $text
}

function Require-Identifier($Value, [string]$Field) {
    $text = Require-String $Value $Field 100
    if ($text -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$') {
        throw "Identificador inválido: $Field"
    }
    return $text
}

function Require-HttpsUrl($Value) {
    $text = Require-String $Value "url"
    $uri = $null
    if (-not [Uri]::TryCreate($text, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne "https" -or [string]::IsNullOrWhiteSpace($uri.Host)) {
        throw "Cada pacote deve ter URL HTTPS absoluta."
    }
    return $text
}

function Require-DateTime($Value, [string]$Field) {
    $text = Require-String $Value $Field
    $parsed = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse($text, [ref]$parsed) -or $text -notmatch '(Z|[+-]\d\d:\d\d)$') {
        throw "$Field deve ser timestamp ISO-8601 com fuso horário."
    }
    return $text
}

function Require-Date($Value, [string]$Field) {
    $text = Require-String $Value $Field 10
    $parsed = [DateTime]::MinValue
    if (-not [DateTime]::TryParseExact($text, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$parsed)) {
        throw "$Field deve usar AAAA-MM-DD."
    }
    return $text
}

$template = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8 | ConvertFrom-Json -DateKind String
if ($template.schema_version -ne 2) { throw "O processo formal exige schema_version 2." }
$issuedAt = Require-DateTime $template.issued_at "issued_at"
$expiresAt = Require-DateTime $template.expires_at "expires_at"
if ([DateTimeOffset]::Parse($expiresAt) -le [DateTimeOffset]::Parse($issuedAt)) { throw "expires_at deve ser posterior a issued_at." }
if ($null -eq $template.publication) { throw "Bloco publication ausente." }
$channel = Require-String $template.publication.channel "publication.channel" 20
if ($channel -notin @("homologacao", "producao")) { throw "Canal de publicação inválido." }
$preparedBy = Require-String $template.publication.prepared_by "publication.prepared_by" 160
$changeReference = Require-String $template.publication.change_reference "publication.change_reference" 160
if ($null -eq $template.packages -or @($template.packages).Count -eq 0) { throw "O catálogo precisa ter ao menos um pacote." }

$packages = @()
$seen = @{}
foreach ($item in @($template.packages)) {
    $identifier = Require-Identifier $item.id "id"
    if ($seen.ContainsKey($identifier)) { throw "Id duplicado no catálogo: $identifier" }
    $seen[$identifier] = $true
    $strategy = Require-String $item.strategy "strategy" 40
    if ($strategy -notin @("replace_file", "import_mma_mcr", "import_mte", "import_sicor")) { throw "Estratégia inválida: $strategy" }
    $archivePath = [IO.Path]::GetFullPath((Require-String $item.archive_path "archive_path"))
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) { throw "Pacote não localizado: $archivePath" }
    $provides = @($item.provides | ForEach-Object { Require-Identifier $_ "provides" })
    if ($provides.Count -eq 0 -or $provides -notcontains $identifier -or @($provides | Select-Object -Unique).Count -ne $provides.Count) {
        throw "provides deve ser único e conter o id do pacote: $identifier"
    }
    $size = [int64](Get-Item -LiteralPath $archivePath).Length
    $url = Require-HttpsUrl $item.url
    if ($url -match '^https://api\.github\.com/.*/releases/assets/' -and $size -ge 2147483648) {
        throw "Ativo acima do limite de 2 GiB do GitHub Release: $archivePath"
    }
    $entry = [ordered]@{
        id = $identifier
        label = Require-String $item.label "label" 160
        version = Require-Identifier $item.version "version"
        strategy = $strategy
        provides = $provides
        source_date = Require-Date $item.source_date "source_date"
        source_reference = Require-String $item.source_reference "source_reference"
        url = $url
        sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        size_bytes = $size
    }
    if ($strategy -eq "replace_file") {
        $target = Require-String $item.target "target"
        if ($target.Replace("\", "/") -match '(^/|(^|/)\.\.(/|$))') { throw "Destino de pacote inválido: $target" }
        $entry.target = $target.Replace("\", "/")
        if ($item.PSObject.Properties.Name -contains "foreign_feature_count") {
            $foreignCount = [int64]$item.foreign_feature_count
            if ($foreignCount -lt 0 -or $foreignCount -gt 1000 -or ($foreignCount -gt 0 -and -not $identifier.StartsWith("sicar_imoveis_"))) {
                throw "Contagem de feições de outra UF inválida: $identifier"
            }
            if ($foreignCount -gt 0) { $entry.foreign_feature_count = $foreignCount }
        }
    }
    if ($strategy -in @("import_mma_mcr", "import_mte")) {
        $entry.validity_until = Require-Date $item.validity_until "validity_until"
    }
    if ($strategy -eq "import_sicor") {
        $entry.scope = Require-String $item.scope "scope" 100
    }
    $packages += [pscustomobject]$entry
}

$catalog = [ordered]@{
    schema_version = 2
    issued_at = $issuedAt
    expires_at = $expiresAt
    publication = [ordered]@{
        channel = $channel
        prepared_by = $preparedBy
        change_reference = $changeReference
    }
    packages = $packages
}
$output = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($output) | Out-Null
$candidatePath = Join-Path $output "catalog.candidate.json"
$json = $catalog | ConvertTo-Json -Depth 8 -Compress
[IO.File]::WriteAllText($candidatePath, $json, [Text.UTF8Encoding]::new($false))
$candidateHash = (Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $output "catalog.candidate.sha256.txt"), "$candidateHash  catalog.candidate.json`n", [Text.Encoding]::ASCII)

if ($PrepareOnly) {
    Write-Output ("Candidato preparado: {0}" -f $candidatePath)
    Write-Output ("SHA-256 para aprovação: {0}" -f $candidateHash)
    return
}
if ([string]::IsNullOrWhiteSpace($ApprovalPath) -or [string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
    throw "Para assinar, informe -ApprovalPath e -PrivateKeyPath."
}
$approval = Get-Content -LiteralPath $ApprovalPath -Raw -Encoding UTF8 | ConvertFrom-Json -DateKind String
if ($approval.schema_version -ne 1) { throw "Registro de aprovação incompatível." }
if ((Require-String $approval.catalog_sha256 "catalog_sha256" 64).ToLowerInvariant() -ne $candidateHash) {
    throw "A aprovação não corresponde ao catálogo candidato atual."
}
if ((Require-String $approval.prepared_by "prepared_by" 160) -ne $preparedBy) {
    throw "O preparador da aprovação diverge do catálogo."
}
$approvedBy = Require-String $approval.approved_by "approved_by" 160
if ($approvedBy -eq $preparedBy) { throw "Preparação e aprovação devem ser feitas por responsáveis distintos." }
[void](Require-DateTime $approval.approved_at "approved_at")
[void](Require-String $approval.approval_reference "approval_reference" 160)

$catalogPath = Join-Path $output "catalog.json"
$signaturePath = Join-Path $output "catalog.json.sig"
[IO.File]::Copy($candidatePath, $catalogPath, $true)
$rsa = [Security.Cryptography.RSA]::Create()
try {
    $rsa.ImportFromPem([IO.File]::ReadAllText([IO.Path]::GetFullPath($PrivateKeyPath)))
    $signature = $rsa.SignData([IO.File]::ReadAllBytes($catalogPath), [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    [IO.File]::WriteAllBytes($signaturePath, $signature)
} finally {
    $rsa.Dispose()
}
[IO.File]::Copy([IO.Path]::GetFullPath($ApprovalPath), (Join-Path $output "approval.record.json"), $true)
Write-Output ("Catálogo aprovado e assinado: {0}" -f $catalogPath)
Write-Output ("Assinatura: {0}" -f $signaturePath)
