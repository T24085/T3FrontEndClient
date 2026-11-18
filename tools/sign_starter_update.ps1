param(
    [Parameter(Mandatory)][string]$Thumbprint,
    [Parameter(Mandatory)][string]$Payload,
    [Parameter(Mandatory)][string]$Signature
)
$ErrorActionPreference = 'Stop'
if ($Thumbprint -notmatch '^[A-Fa-f0-9]{40}$') { throw 'Invalid signing certificate thumbprint' }
$cert = Get-Item -LiteralPath "Cert:\CurrentUser\My\$Thumbprint"
if (!$cert.HasPrivateKey) { throw 'The signing certificate has no private key' }
$rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
try {
    $data = [IO.File]::ReadAllBytes($Payload)
    $signed = $rsa.SignData($data, [System.Security.Cryptography.HashAlgorithmName]::SHA256,
                            [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
    [IO.File]::WriteAllBytes($Signature, $signed)
} finally {
    $rsa.Dispose()
}
