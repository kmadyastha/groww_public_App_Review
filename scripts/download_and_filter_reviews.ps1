$ErrorActionPreference = "Stop"
$rawDir = "c:\Users\Admin\Documents\AI Agents\App Reviews\data\raw"
New-Item -ItemType Directory -Force -Path $rawDir | Out-Null

$minWords = 8
$cutoff = (Get-Date).Date.AddDays(-56)
$nonEnglish = [System.Collections.Generic.HashSet[string]]::new([string[]]@(
  "aafat","abhi","accha","acha","achha","ahe","apna","apni","aur","bahut","bakwaas","bakwas","bekar","bhai","bhi","bilkul","bohot","chahiye","chala","dhanyavad","dikkat","faltu","galat","gaya","gaye","ghatiya","gya","gye","hai","hain","hoga","hogi","hua","hui","huye","illai","inko","isko","isliye","jaata","jaate","jaise","jaldi","jyada","karna","karne","karo","kaunsa","kaunsi","kiya","kiye","kripya","krdo","kro","krna","krne","kuch","kya","kyun","kyunki","leke","lekin","liye","magar","matlab","mera","meri","mujhe","nahi","nahin","namaste","nandri","nhi","pagal","paise","pata","pehle","phir","raha","rahe","rahi","romba","rupay","rupaye","sahi","shukriya","tarah","theek","thik","thoda","toh","tumhe","undi","unko","usko","wala","wale","yaar","yeh","zabardast","zaroor","zyada"
))
$latinWord = [regex]"[A-Za-z]+(?:'[A-Za-z]+)?"
$nonLatin = [regex]"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F\u0E00-\u0E7F\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]"

function Get-WordCount([string]$text) {
  if ([string]::IsNullOrWhiteSpace($text)) { return 0 }
  return $latinWord.Matches($text).Count
}

function Test-IsEnglish([string]$text) {
  if ([string]::IsNullOrWhiteSpace($text)) { return $false }
  if ($nonLatin.IsMatch($text)) { return $false }
  $tokens = @($latinWord.Matches($text) | ForEach-Object { $_.Value.ToLowerInvariant() })
  if ($tokens.Count -eq 0) { return $false }
  foreach ($t in $tokens) { if ($nonEnglish.Contains($t)) { return $false } }
  return $true
}

function Test-KeepReview([string]$text) {
  return ((Get-WordCount $text) -ge $minWords) -and (Test-IsEnglish $text)
}

function Write-JsonArray($path, $items) {
  $utf8 = New-Object System.Text.UTF8Encoding $false
  $sb = New-Object System.Text.StringBuilder
  [void]$sb.AppendLine("[")
  for ($i = 0; $i -lt $items.Count; $i++) {
    $json = ($items[$i] | ConvertTo-Json -Compress -Depth 8)
    if ($i -lt $items.Count - 1) { [void]$sb.AppendLine($json + ",") }
    else { [void]$sb.AppendLine($json) }
  }
  [void]$sb.AppendLine("]")
  [System.IO.File]::WriteAllText($path, $sb.ToString(), $utf8)
}

function Build-PlayBody([int]$count, [string]$paginationToken) {
  if ([string]::IsNullOrEmpty($paginationToken)) {
    return 'f.req=%5B%5B%5B%22oCPfdb%22%2C%22%5Bnull%2C%5B2%2C2%2C%5B' + $count + '%5D%2Cnull%2C%5Bnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%5D%5D%2C%5B%5C%22com.nextbillion.groww%5C%22%2C7%5D%5D%22%2Cnull%2C%22generic%22%5D%5D%5D%0A'
  }
  return 'f.req=%5B%5B%5B%22oCPfdb%22%2C%22%5Bnull%2C%5B2%2C2%2C%5B' + $count + '%2Cnull%2C%5C%22' + $paginationToken + '%5C%22%5D%2Cnull%2C%5Bnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%5D%5D%2C%5B%5C%22com.nextbillion.groww%5C%22%2C7%5D%5D%22%2Cnull%2C%22generic%22%5D%5D%5D%0A'
}

$playKept = New-Object System.Collections.Generic.List[object]
$token = $null
$page = 0
$pastCutoff = $false
$dropShort = 0
$dropLang = 0
$url = "https://play.google.com/_/PlayStoreUi/data/batchexecute?hl=en&gl=in"
$headers = @{
  "Content-Type" = "application/x-www-form-urlencoded;charset=UTF-8"
  "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

while (-not $pastCutoff -and $page -lt 80) {
  $page++
  $body = Build-PlayBody -count 150 -paginationToken $token
  $tmp = Join-Path $rawDir ("play_page_{0}.txt" -f $page)
  Invoke-WebRequest -Uri $url -Method POST -Headers $headers -Body $body -OutFile $tmp -UseBasicParsing -TimeoutSec 60 | Out-Null
  $text = [System.IO.File]::ReadAllText($tmp)
  Remove-Item $tmp -ErrorAction SilentlyContinue
  $start = $text.IndexOf("[")
  if ($start -lt 0) { Write-Output ("play page {0} no json" -f $page); break }
  $outer = $text.Substring($start) | ConvertFrom-Json
  $payloadStr = $null
  foreach ($frame in @($outer)) {
    $row = @($frame)
    if ($row.Count -ge 3 -and ("$($row[1])" -eq "oCPfdb") -and ($row[2] -is [string])) {
      $payloadStr = $row[2]
      break
    }
  }
  if (-not $payloadStr) { Write-Output ("play page {0} missing payload" -f $page); break }
  $inner = $payloadStr | ConvertFrom-Json
  $items = @()
  if ($inner -and $inner[0]) { $items = @($inner[0]) }
  $next = $null
  try {
    $next = $inner[-2][-1]
    if ($next -is [System.Array]) { $next = $null }
  } catch { $next = $null }

  $keptHere = 0
  foreach ($r in $items) {
    $rr = @($r)
    $id = $rr[0]
    $rating = $rr[2]
    $content = [string]$rr[4]
    $ts = $null
    try { $ts = $rr[5][0] } catch {}
    if ($null -eq $ts) { continue }
    $dt = [DateTimeOffset]::FromUnixTimeSeconds([int64]$ts).UtcDateTime
    if ($dt.Date -lt $cutoff) { $pastCutoff = $true; continue }
    $wc = Get-WordCount $content
    if ($wc -lt $minWords) { $dropShort++; continue }
    if (-not (Test-IsEnglish $content)) { $dropLang++; continue }
    $playKept.Add([pscustomobject]@{
      store = "play"
      review_id_source = "$id"
      rating = $rating
      title = $null
      text = $content
      date = $dt.ToString("yyyy-MM-dd")
      locale = "en_IN"
      package = "com.nextbillion.groww"
    }) | Out-Null
    $keptHere++
  }
  Write-Output ("play page {0} raw={1} kept={2} total={3} next={4}" -f $page, $items.Count, $keptHere, $playKept.Count, [bool]$next)
  if (-not $next -or $items.Count -eq 0) { break }
  $token = "$next"
  Start-Sleep -Milliseconds 350
}

Write-JsonArray (Join-Path $rawDir "play_reviews.json") $playKept
Write-Output ("PLAY kept={0} drop_short={1} drop_lang={2} cutoff={3:yyyy-MM-dd}" -f $playKept.Count, $dropShort, $dropLang, $cutoff)

$iosKept = New-Object System.Collections.Generic.List[object]
$iosShort = 0
$iosLang = 0
for ($p = 1; $p -le 10; $p++) {
  $rssPath = Join-Path $rawDir ("ios_page_{0}.json" -f $p)
  curl.exe -L --max-time 30 -A "GrowwWeeklyPulse/0.1 (public iTunes RSS)" -o $rssPath "https://itunes.apple.com/in/rss/customerreviews/page=$p/id=1404871703/sortBy=mostRecent/json" | Out-Null
  $doc = Get-Content -Raw $rssPath | ConvertFrom-Json
  Remove-Item $rssPath -ErrorAction SilentlyContinue
  foreach ($e in @($doc.feed.entry)) {
    if ($null -eq $e.'im:rating') { continue }
    $content = [string]$e.content.label
    $day = ([datetime]$e.updated.label).ToString("yyyy-MM-dd")
    $dt = [datetime]$e.updated.label
    if ($dt.Date -lt $cutoff) { continue }
    if ((Get-WordCount $content) -lt $minWords) { $iosShort++; continue }
    if (-not (Test-IsEnglish $content)) { $iosLang++; continue }
    $iosKept.Add([pscustomobject]@{
      store = "app_store"
      review_id_source = [string]$e.id.label
      rating = [int]$e.'im:rating'.label
      title = [string]$e.title.label
      text = $content
      date = $day
      locale = "en_IN"
    }) | Out-Null
  }
  Write-Output ("ios page {0} kept_total={1}" -f $p, $iosKept.Count)
}

Write-JsonArray (Join-Path $rawDir "app_store_reviews.json") $iosKept
Write-Output ("IOS kept={0} drop_short={1} drop_lang={2}" -f $iosKept.Count, $iosShort, $iosLang)
