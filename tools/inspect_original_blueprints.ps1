param(
 [Parameter(Mandatory=$true)][string]$InputRoot,
 [Parameter(Mandatory=$true)][string]$ParserDirectory,
 [Parameter(Mandatory=$true)][string]$Mapping,
 [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference='Stop'
$parser=Join-Path $ParserDirectory 'CUE4Parse.dll'
if ((Get-FileHash -LiteralPath $parser).Hash.ToLowerInvariant() -ne '7eac7e70eac22d91f2597f7823127c7d413f903a404527f6c18bcd930dd2755c') { throw 'Parser changed' }
if ((Get-FileHash -LiteralPath $Mapping).Hash.ToLowerInvariant() -ne '06771f55294699199cf42ce2ef1f24611efd0620b6cc45b7e6c088d9723ae981') { throw 'Mapping changed' }
if (Test-Path -LiteralPath $Output) { throw 'Fresh output required' }
$repo=[IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))+[IO.Path]::DirectorySeparatorChar
if ([IO.Path]::GetFullPath($Output).StartsWith($repo,[StringComparison]::OrdinalIgnoreCase)) { throw 'Private decoded assets must remain outside Git' }
$assets=@(Get-ChildItem -LiteralPath $InputRoot -Recurse -File -Filter '*.uasset')
if ($assets.Count -lt 1 -or $assets.Count -gt 16 -or @($assets|Where-Object Length -gt 2097152).Count) { throw 'One to sixteen bounded Blueprint assets required' }
$resolver=[Func[System.Runtime.Loader.AssemblyLoadContext,System.Reflection.AssemblyName,System.Reflection.Assembly]]{
 param($context,$name)
 $file=Join-Path $ParserDirectory ($name.Name+'.dll')
 if(Test-Path -LiteralPath $file){return $context.LoadFromAssemblyPath($file)}
 return $null
}
[System.Runtime.Loader.AssemblyLoadContext]::Default.add_Resolving($resolver)
$provider=$null
try {
 $null=[Reflection.Assembly]::LoadFrom($parser)
 $version=[CUE4Parse.UE4.Versions.VersionContainer]::new([CUE4Parse.UE4.Versions.EGame]::GAME_UE5_3,[CUE4Parse.UE4.Assets.Exports.Texture.ETexturePlatform]::DesktopMobile,[Activator]::CreateInstance([CUE4Parse.UE4.Versions.FPackageFileVersion]),$null,$null,$null)
 $provider=[CUE4Parse.FileProvider.DefaultFileProvider]::new($InputRoot,[IO.SearchOption]::AllDirectories,$true,$version)
 $provider.ReadScriptData=$true
 $provider.MappingsContainer=[CUE4Parse.MappingsProvider.Usmap.FileUsmapTypeMappingsProvider]::new($Mapping,[StringComparer]::Ordinal)
 $provider.Initialize();$packages=@()
 foreach($member in @($provider.Files.Keys|Where-Object{$_.EndsWith('.uasset',[StringComparison]::Ordinal)})) {
  $package=$provider.LoadPackage($member)
  if ($package.ExportMap.Length -gt 512) { throw 'Export bound' }
  $exports=@()
  for($i=0;$i -lt $package.ExportMap.Length;$i++) {
   $header=$package.ExportMap[$i];$object=$package.ExportsLazy[$i].Value
   $properties=@(foreach($p in $object.Properties){[ordered]@{name=$p.Name.ToString();type=$p.PropertyType.ToString();value=([Newtonsoft.Json.JsonConvert]::SerializeObject($p.Tag)|ConvertFrom-Json -Depth 40)}})
   $script=$null
   if($null -ne $object.GetType().GetField('ScriptBytecode',[Reflection.BindingFlags]'Public,Instance')) {
    $decoded=[Newtonsoft.Json.JsonConvert]::SerializeObject($object,[Newtonsoft.Json.JsonSerializerSettings]@{ReferenceLoopHandling='Ignore';MaxDepth=80})|ConvertFrom-Json -Depth 85
    $script=$decoded.ScriptBytecode
   }
   $exports+=,[ordered]@{index=$i;name=$header.ObjectName.ToString();class=$header.ClassName.ToString();properties=$properties;script=$script}
  }
  $packages+=,[ordered]@{member=$member;exports=$exports}
 }
 $json=[ordered]@{scope='Read-only original cooked Blueprint decode; no Blueprint or game execution';packages=$packages}|ConvertTo-Json -Depth 70 -Compress
 if([Text.Encoding]::UTF8.GetByteCount($json) -gt 16777216){throw 'Output bound'}
 [IO.File]::WriteAllText($Output,$json,[Text.UTF8Encoding]::new($false))
 Write-Output $Output
} finally {
 if($null -ne $provider){$provider.Dispose()}
 [System.Runtime.Loader.AssemblyLoadContext]::Default.remove_Resolving($resolver)
}
