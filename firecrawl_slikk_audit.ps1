# LeadFlow Firecrawl smoke test + 16-signal homepage heuristic audit
# Run this from the LeadFlow repository root in PowerShell.
# Makes ONE Firecrawl scrape request for https://www.slikk.club/.
# Does not print API keys or save the raw HTML/page contents.

$ErrorActionPreference = 'Stop'
$targetUrl = 'https://www.slikk.club/'
$projectRoot = (Get-Location).Path

Write-Host "`n=== 1. Check whether Firecrawl is referenced by the LeadFlow source ===" -ForegroundColor Cyan
$extensions = @('.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json', '.toml', '.yaml', '.yml')
$excludedFragments = @('\node_modules\', '\.git\', '\.next\', '\dist\', '\build\', '\.venv\', '\venv\', '\__pycache__\', '\coverage\', '\.turbo\')
$sourceFiles = @(Get-ChildItem -Path $projectRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
    $ext = $_.Extension.ToLowerInvariant()
    $pathLower = $_.FullName.ToLowerInvariant()
    $keep = $extensions -contains $ext
    foreach ($fragment in $excludedFragments) {
        if ($pathLower.Contains($fragment)) { $keep = $false; break }
    }
    if ($_.Name -match '^(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$') { $keep = $false }
    $keep
})
$firecrawlSourceFiles = @()
foreach ($f in $sourceFiles) {
    try {
        if (Select-String -Path $f.FullName -Pattern '(?i)firecrawl|FIRECRAWL_API_KEY|api\.firecrawl\.dev|@mendable/firecrawl' -Quiet -ErrorAction SilentlyContinue) {
            $firecrawlSourceFiles += $f.FullName.Substring($projectRoot.Length).TrimStart('\', '/')
        }
    } catch { }
}
if ($firecrawlSourceFiles.Count -gt 0) {
    Write-Host "Firecrawl-related source references FOUND in:" -ForegroundColor Yellow
    $firecrawlSourceFiles | Sort-Object -Unique | ForEach-Object { Write-Host "  - $_" }
    Write-Host "Note: references do not prove the collector is wired into EnrichmentService or working end-to-end." -ForegroundColor Yellow
    $integrationScan = 'references_found_not_proof_of_runtime_integration'
} else {
    Write-Host "No Firecrawl integration references found in application source files." -ForegroundColor Red
    Write-Host "The direct API test below checks Firecrawl itself, not whether LeadFlow calls it." -ForegroundColor Yellow
    $integrationScan = 'no_source_references_found'
}

function Get-FirecrawlKeyFromEnvFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    foreach ($line in Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue) {
        if ($line -match '^\s*FIRECRAWL_API_KEY\s*=\s*(.*?)\s*$') {
            $value = $Matches[1].Trim()
            if ($value.Length -ge 2) {
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
        }
    }
    return $null
}

Write-Host "`n=== 2. Load Firecrawl API key without displaying it ===" -ForegroundColor Cyan
$apiKey = $env:FIRECRAWL_API_KEY
$keySource = 'process environment'
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $envPaths = @(
        (Join-Path $projectRoot '.env'),
        (Join-Path $projectRoot '.env.local'),
        (Join-Path $projectRoot 'apps/api/.env'),
        (Join-Path $projectRoot 'apps/api/.env.local'),
        (Join-Path $projectRoot 'apps/api/.env.development')
    )
    foreach ($candidate in $envPaths) {
        $found = Get-FirecrawlKeyFromEnvFile -Path $candidate
        if (-not [string]::IsNullOrWhiteSpace($found)) {
            $apiKey = $found
            $keySource = 'local env file (key value hidden)'
            break
        }
    }
}

$secureKey = $null
$ptr = [IntPtr]::Zero
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $secureKey = Read-Host 'FIRECRAWL_API_KEY was not found in process env or common .env paths. Enter the key (input hidden)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    $keySource = 'secure interactive input'
}
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    throw 'No Firecrawl API key was supplied. Set FIRECRAWL_API_KEY or add it to a supported .env file.'
}
Write-Host "API key source: $keySource (value hidden)"

try {
    Write-Host "`n=== 3. Request one Firecrawl scrape for $targetUrl ===" -ForegroundColor Cyan
    $headers = @{
        'Authorization' = "Bearer $apiKey"
        'Content-Type' = 'application/json'
        'Accept' = 'application/json'
    }
    $requestBody = @{
        url = $targetUrl
        formats = @('markdown', 'html', 'links')
        onlyMainContent = $false
        timeout = 60000
    } | ConvertTo-Json -Depth 8

    $startedAt = Get-Date
    try {
        $response = Invoke-RestMethod -Method Post -Uri 'https://api.firecrawl.dev/v2/scrape' -Headers $headers -Body $requestBody -TimeoutSec 90
    } catch {
        Write-Host "Firecrawl API request FAILED." -ForegroundColor Red
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            Write-Host "HTTP status: $([int]$_.Exception.Response.StatusCode)"
        }
        if ($_.ErrorDetails.Message) {
            # Error response is shown, but never print the Authorization header or key.
            Write-Host "Provider error: $($_.ErrorDetails.Message)"
        } else {
            Write-Host "Error: $($_.Exception.Message)"
        }
        Write-Host 'Check key validity, available credits, request limits, and the target URL.' -ForegroundColor Yellow
        return
    }
    $elapsedSeconds = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 2)
    if (-not $response.success -or -not $response.data) {
        Write-Host "Firecrawl responded but did not return a successful scrape." -ForegroundColor Red
        if ($response.error) { Write-Host "Provider error: $($response.error)" }
        if ($response.code) { Write-Host "Provider code: $($response.code)" }
        return
    }

    $data = $response.data
    $metadata = $data.metadata
    $html = [string]$data.html
    if ([string]::IsNullOrWhiteSpace($html)) { $html = [string]$data.rawHtml }
    $markdown = [string]$data.markdown
    $finalUrl = [string]$metadata.url
    if ([string]::IsNullOrWhiteSpace($finalUrl)) { $finalUrl = [string]$metadata.sourceURL }
    if ([string]::IsNullOrWhiteSpace($finalUrl)) { $finalUrl = $targetUrl }

    Write-Host "Firecrawl API: SUCCESS" -ForegroundColor Green
    Write-Host "HTTP request completed in: $elapsedSeconds seconds"
    Write-Host "Page title: $($metadata.title)"
    Write-Host "HTTP status reported by Firecrawl: $($metadata.statusCode)"
    Write-Host "Final URL: $finalUrl"
    if ($null -ne $metadata.provider -and $null -ne $metadata.provider.creditsCost) {
        Write-Host "Reported provider credit cost: $($metadata.provider.creditsCost)"
    } else {
        Write-Host 'Reported provider credit cost: not supplied in response; check Firecrawl usage dashboard.'
    }

    # Prepare text used for heuristic checks. This is not an authoritative audit.
    $htmlWithoutScripts = [regex]::Replace($html, '(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>', ' ')
    $visibleText = [regex]::Replace($htmlWithoutScripts, '(?is)<[^>]+>', ' ')
    $visibleText = [System.Net.WebUtility]::HtmlDecode($visibleText)
    $textForAnalysis = $markdown
    if ([string]::IsNullOrWhiteSpace($textForAnalysis)) { $textForAnalysis = $visibleText }
    $scanText = "$html`n$markdown"
    $wordCount = [regex]::Matches($textForAnalysis, '\b[\p{L}\p{N}]+\b').Count
    $hrefs = @()
    foreach ($m in [regex]::Matches($html, '(?is)href\s*=\s*["'']([^"'']+)["'']')) { $hrefs += $m.Groups[1].Value }

    $signals = @()
    # 1. legacy_platform
    $platformPatterns = [ordered]@{
        'WordPress' = '(?i)wp-content|wp-includes|wp-json|wordpress'
        'Shopify' = '(?i)cdn\.shopify\.com|shopify-section|Shopify\.theme'
        'Wix' = '(?i)wixstatic\.com|wix\.com'
        'Webflow' = '(?i)webflow\.com|w-webflow'
        'Magento' = '(?i)Magento|mage-cache|static/frontend'
        'Drupal' = '(?i)Drupal\.settings|/sites/default/files/'
        'Joomla' = '(?i)com_content|Joomla!'
        'WooCommerce' = '(?i)woocommerce'
        'BigCommerce' = '(?i)bigcommerce\.com|stencil-utils'
    }
    $platforms = @()
    foreach ($platform in $platformPatterns.Keys) { if ([regex]::IsMatch($scanText, $platformPatterns[$platform])) { $platforms += $platform } }
    if ($platforms.Count -gt 0) { $signals += [pscustomobject]@{ Signal='legacy_platform'; Result='PLATFORM MARKER FOUND'; Evidence=($platforms -join ', '); Confidence='Medium: fingerprints may identify platform, not whether it is legacy' } }
    else { $signals += [pscustomobject]@{ Signal='legacy_platform'; Result='NOT DETECTED'; Evidence='No common CMS/e-commerce platform marker found in returned homepage HTML'; Confidence='Low: platform may be hidden or use custom code' } }

    # 2. old_design
    $legacyFramework = [regex]::IsMatch($scanText, '(?i)(bootstrap[^"''<>]{0,60}3\.[0-9]|jquery[^"''<>]{0,60}1\.[0-9])')
    $copyrightYears = @()
    foreach ($ym in [regex]::Matches($scanText, '(?i)(?:©|copyright)[^0-9]{0,12}(20\d{2})')) { $copyrightYears += [int]$ym.Groups[1].Value }
    $latestCopyright = $null
    if ($copyrightYears.Count -gt 0) { $latestCopyright = ($copyrightYears | Measure-Object -Maximum).Maximum }
    if ($legacyFramework) { $signals += [pscustomobject]@{ Signal='old_design'; Result='POSSIBLE LEGACY MARKER'; Evidence='Older Bootstrap/jQuery asset pattern found; visual inspection required'; Confidence='Low' } }
    elseif ($null -ne $latestCopyright -and $latestCopyright -le ((Get-Date).Year - 3)) { $signals += [pscustomobject]@{ Signal='old_design'; Result='POSSIBLE STALE COPYRIGHT'; Evidence="Latest detected copyright year: $latestCopyright; this alone does not prove old design"; Confidence='Low' } }
    else { $signals += [pscustomobject]@{ Signal='old_design'; Result='NOT RELIABLY ASSESSABLE'; Evidence='A single scrape cannot judge visual design age reliably'; Confidence='Low' } }

    # 3. weak_ctas
    $ctaMatches = [regex]::Matches($textForAnalysis, '(?i)\b(shop now|buy now|add to cart|sign up|subscribe|contact us|book now|get started|learn more|download|apply now|explore|shop|discover|try now|enquire now)\b')
    if ($ctaMatches.Count -le 1) { $signals += [pscustomobject]@{ Signal='weak_ctas'; Result='POSSIBLE GAP'; Evidence="Found $($ctaMatches.Count) common CTA phrase(s) in extracted page text"; Confidence='Low: CTA visibility and prominence need visual/DOM review' } }
    else { $signals += [pscustomobject]@{ Signal='weak_ctas'; Result='CTA TEXT FOUND'; Evidence="Found $($ctaMatches.Count) common CTA phrase occurrence(s)"; Confidence='Low: count alone cannot judge CTA quality' } }

    # 4. not_mobile_friendly
    $hasViewport = [regex]::IsMatch($html, '(?i)<meta\b[^>]*\bname\s*=\s*["'']viewport["'']')
    if ($hasViewport) { $signals += [pscustomobject]@{ Signal='not_mobile_friendly'; Result='VIEWPORT META FOUND'; Evidence='Viewport metadata exists; responsive behavior still needs a mobile audit'; Confidence='Medium for metadata only' } }
    else { $signals += [pscustomobject]@{ Signal='not_mobile_friendly'; Result='POSSIBLE GAP'; Evidence='No viewport meta tag detected in returned HTML'; Confidence='Medium: returned HTML can be incomplete' } }

    # 5. no_ssl
    if ($finalUrl -match '^https://') { $signals += [pscustomobject]@{ Signal='no_ssl'; Result='NO ISSUE INDICATED'; Evidence="Firecrawl reports an HTTPS final URL: $finalUrl"; Confidence='Medium: verifies HTTPS access, not every TLS configuration detail' } }
    else { $signals += [pscustomobject]@{ Signal='no_ssl'; Result='POSSIBLE GAP'; Evidence="Reported final URL is not HTTPS: $finalUrl"; Confidence='Medium' } }

    # 6. thin_content
    if ($wordCount -lt 300) { $signals += [pscustomobject]@{ Signal='thin_content'; Result='POSSIBLE GAP'; Evidence="Extracted homepage text contains about $wordCount words (<300 heuristic threshold)"; Confidence='Low: homepages may intentionally be concise' } }
    else { $signals += [pscustomobject]@{ Signal='thin_content'; Result='NOT FLAGGED BY WORD-COUNT HEURISTIC'; Evidence="Extracted homepage text contains about $wordCount words"; Confidence='Low: quantity is not content quality' } }

    # 7. no_analytics
    $analyticsPatterns = '(?i)googletagmanager\.com|google-analytics\.com|gtag\s*\(|google_tag_manager|segment\.com/analytics|hotjar\.com|clarity\.ms|plausible\.io|posthog|mixpanel|heap\.io|rudderstack'
    if ([regex]::IsMatch($scanText, $analyticsPatterns)) { $signals += [pscustomobject]@{ Signal='no_analytics'; Result='ANALYTICS MARKER FOUND'; Evidence='One or more common analytics vendor markers were detected'; Confidence='Medium: marker presence does not prove analytics is functioning' } }
    else { $signals += [pscustomobject]@{ Signal='no_analytics'; Result='NO MARKER DETECTED'; Evidence='No common analytics markers were found in returned HTML/text'; Confidence='Low: tag managers or server-side analytics may hide usage' } }

    # 8. no_live_chat
    $chatPatterns = '(?i)intercom|drift\.com|crisp\.chat|tawk\.to|tidio|livechatinc|hubspot.*chat|zendesk.*chat|freshchat|gorgias|olark'
    if ([regex]::IsMatch($scanText, $chatPatterns)) { $signals += [pscustomobject]@{ Signal='no_live_chat'; Result='CHAT MARKER FOUND'; Evidence='Common live-chat vendor marker detected'; Confidence='Medium: marker does not prove widget is visible/working' } }
    else { $signals += [pscustomobject]@{ Signal='no_live_chat'; Result='NO MARKER DETECTED'; Evidence='No common live-chat widget marker found'; Confidence='Low: chat may load dynamically or use another vendor' } }

    # 9. poor_aeo_geo
    $schemaFound = [regex]::IsMatch($scanText, '(?i)"@type"\s*:\s*"(Organization|Corporation|LocalBusiness|FAQPage|HowTo|Product|WebSite)"')
    $descriptionFound = [regex]::IsMatch($html, '(?i)<meta\b[^>]*(name|property)\s*=\s*["''](description|og:description)["'']')
    $contactFound = [regex]::IsMatch($scanText, '(?i)tel:|mailto:|\b(address|contact us|customer support|phone number)\b')
    $aeoMarkers = @(); if ($schemaFound) { $aeoMarkers += 'structured data type' }; if ($descriptionFound) { $aeoMarkers += 'meta description' }; if ($contactFound) { $aeoMarkers += 'contact/entity details' }
    if ($aeoMarkers.Count -lt 2) { $signals += [pscustomobject]@{ Signal='poor_aeo_geo'; Result='POSSIBLE OPTIMIZATION GAP'; Evidence="Detected $($aeoMarkers.Count)/3 marker groups: $($aeoMarkers -join ', ')"; Confidence='Low: only a shallow AEO/GEO heuristic' } }
    else { $signals += [pscustomobject]@{ Signal='poor_aeo_geo'; Result='BASIC MARKERS FOUND'; Evidence="Detected marker groups: $($aeoMarkers -join ', ')"; Confidence='Low: not a full AEO/GEO quality assessment' } }

    # 10. stale_blog
    $blogHrefs = @($hrefs | Where-Object { $_ -match '(?i)blog|journal|insights|articles' })
    if ($blogHrefs.Count -gt 0) { $signals += [pscustomobject]@{ Signal='stale_blog'; Result='DEEPER CHECK REQUIRED'; Evidence="Found $($blogHrefs.Count) blog/insights/article link(s); latest publication date was not verified"; Confidence='Not assessable from homepage alone' } }
    else { $signals += [pscustomobject]@{ Signal='stale_blog'; Result='NOT ASSESSABLE'; Evidence='No blog/insights/article URL found in homepage HTML; absence of a link does not prove no blog exists'; Confidence='Low' } }

    # 11. no_press
    $pressMatches = @($hrefs | Where-Object { $_ -match '(?i)press|newsroom|media|announcements' })
    if ($pressMatches.Count -gt 0) { $signals += [pscustomobject]@{ Signal='no_press'; Result='PRESS/NEWS LINK FOUND'; Evidence=($pressMatches | Select-Object -First 5) -join '; '; Confidence='Medium for link presence; freshness needs page crawl' } }
    else { $signals += [pscustomobject]@{ Signal='no_press'; Result='NOT ASSESSABLE'; Evidence='No press/newsroom/media link detected on homepage'; Confidence='Low: may exist on an unlinked route' } }

    # 12. no_case_studies
    $caseMatches = @($hrefs | Where-Object { $_ -match '(?i)case.?stud|customer.?stor|portfolio|our-work|projects|success.?stor' })
    if ($caseMatches.Count -gt 0 -or [regex]::IsMatch($textForAnalysis, '(?i)case studies|customer stories|our work|success stories')) { $signals += [pscustomobject]@{ Signal='no_case_studies'; Result='PORTFOLIO/CASE-STUDY MARKER FOUND'; Evidence=(($caseMatches | Select-Object -First 5) -join '; '); Confidence='Medium for marker presence, not quality' } }
    else { $signals += [pscustomobject]@{ Signal='no_case_studies'; Result='NOT ASSESSABLE'; Evidence='No case-study/portfolio marker detected on homepage'; Confidence='Low: may exist on unlinked pages' } }

    # 13. no_video
    if ([regex]::IsMatch($scanText, '(?i)<video\b|youtube\.com/embed|youtu\.be/|vimeo\.com|wistia\.com|player\.vimeo')) { $signals += [pscustomobject]@{ Signal='no_video'; Result='VIDEO MARKER FOUND'; Evidence='Video tag or common video embed domain detected'; Confidence='Medium: visible playback still needs checking' } }
    else { $signals += [pscustomobject]@{ Signal='no_video'; Result='NO VIDEO MARKER DETECTED'; Evidence='No common video tags/embed markers found on homepage'; Confidence='Low: video may be loaded dynamically or on another page' } }

    # 14. weak_social
    $socialDomains = @()
    foreach ($sd in @('instagram.com','facebook.com','linkedin.com','x.com','twitter.com','tiktok.com','youtube.com')) {
        if (@($hrefs | Where-Object { $_ -match [regex]::Escape($sd) }).Count -gt 0) { $socialDomains += $sd }
    }
    if ($socialDomains.Count -eq 0) { $signals += [pscustomobject]@{ Signal='weak_social'; Result='NO SOCIAL LINKS DETECTED'; Evidence='No common social profile links found in homepage hrefs'; Confidence='Low: social presence/quality requires further research' } }
    else { $signals += [pscustomobject]@{ Signal='weak_social'; Result='SOCIAL LINKS FOUND'; Evidence=($socialDomains -join ', '); Confidence='Low: presence alone cannot measure posting frequency or audience strength' } }

    # 15. weak_email_capture
    $emailCapture = [regex]::IsMatch($scanText, '(?i)<input\b[^>]*type\s*=\s*["'']?email|newsletter|subscribe to our|sign up for updates|email updates|join our mailing list')
    if ($emailCapture) { $signals += [pscustomobject]@{ Signal='weak_email_capture'; Result='EMAIL-CAPTURE MARKER FOUND'; Evidence='Email input or newsletter/subscription wording detected'; Confidence='Medium for marker presence, not form functionality' } }
    else { $signals += [pscustomobject]@{ Signal='weak_email_capture'; Result='NO MARKER DETECTED'; Evidence='No email input or common newsletter/signup wording detected'; Confidence='Low: forms may be rendered dynamically or exist elsewhere' } }

    # 16. hiring
    $hiringHrefs = @($hrefs | Where-Object { $_ -match '(?i)career|jobs?|join.?our.?team|work.?with.?us|greenhouse\.io|lever\.co|workday|ashbyhq' })
    if ($hiringHrefs.Count -gt 0 -or [regex]::IsMatch($scanText, '(?i)careers|join our team|work with us|greenhouse\.io|lever\.co|ashbyhq')) { $signals += [pscustomobject]@{ Signal='hiring'; Result='HIRING MARKER FOUND'; Evidence=(($hiringHrefs | Select-Object -First 5) -join '; '); Confidence='Medium for marker presence; open roles need verification' } }
    else { $signals += [pscustomobject]@{ Signal='hiring'; Result='NOT ASSESSABLE'; Evidence='No careers/jobs link or common applicant-tracking marker found on homepage'; Confidence='Low: hiring pages may exist elsewhere' } }

    Write-Host "`n=== 4. 16-signal heuristic report for $targetUrl ===" -ForegroundColor Cyan
    $signals | Format-Table -Property Signal, Result, Confidence, Evidence -Wrap -AutoSize

    $report = [ordered]@{
        target_url = $targetUrl
        checked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        firecrawl_api_success = $true
        api_elapsed_seconds = $elapsedSeconds
        page_title = [string]$metadata.title
        reported_http_status = $metadata.statusCode
        final_url = $finalUrl
        estimated_extracted_word_count = $wordCount
        reported_credits_cost = $metadata.provider.creditsCost
        poc_source_scan = $integrationScan
        firecrawl_source_files = @($firecrawlSourceFiles | Sort-Object -Unique)
        signals = $signals
        disclaimer = 'Heuristic homepage-only findings. Not authoritative qualification scores. Blog/press/case studies/hiring and social strength may require linked-page or external checks.'
    }
    $reportPath = Join-Path $projectRoot 'firecrawl_slikk_signal_report.json'
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "`nReport saved to: $reportPath" -ForegroundColor Green
    Write-Host "This consumed one Firecrawl scrape request. Check the Firecrawl dashboard for the authoritative credit usage." -ForegroundColor Yellow

    if ($integrationScan -eq 'no_source_references_found') {
        Write-Host "FINAL: Firecrawl API works independently, but this scan did NOT find Firecrawl integrated into LeadFlow source code." -ForegroundColor Yellow
    } else {
        Write-Host "FINAL: Firecrawl references exist. Review the listed files and confirm the collector is wired into EnrichmentService; a source match is not end-to-end proof." -ForegroundColor Yellow
    }
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    Remove-Variable apiKey -ErrorAction SilentlyContinue
    Remove-Variable secureKey -ErrorAction SilentlyContinue
}
