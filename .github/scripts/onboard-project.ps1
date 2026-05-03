<#
.SYNOPSIS
    Onboard a GitHub Project (v2) with full Agile/Scrum fields and tooling.

.DESCRIPTION
    Creates or reuses a GitHub ProjectV2 and provisions:

    BASIC preset (always):
      - Sprint        (Iteration)
      - Priority      (Critical / High / Medium / Low)
      - Story Points  (Number)
      - Category      (configurable single-select)

    FULL preset (default, adds):
      - Type          (Epic / Story / Task / Bug / Spike)
      - Effort        (XS / S / M / L / XL  -- T-shirt sizing)
      - Epic          (free-text epic name)
      - Blocked       (No / Yes)
      - Risk          (None / Low / Medium / High)

    Optionally:
      - Creates GitHub Milestones for the first N sprints in the linked repo
      - Creates issue labels for each Type value
      - Links the repo to the project

    Requires gh CLI authenticated with the "project" and "repo" scopes:
      gh auth login --scopes project,repo

.PARAMETER Org
    GitHub organisation login.  Default: ITlusions

.PARAMETER ProjectTitle
    Display title for the project.

.PARAMETER RepoName
    Repository to link (format: owner/repo). Also required for milestones + labels.

.PARAMETER Preset
    "basic" -- Sprint, Priority, Story Points, Category only.
    "full"  -- basic + Type, Effort, Epic, Blocked, Risk.  (Default)

.PARAMETER CategoryOptions
    Comma-separated Category options.
    Default: "Provisioning,Azure Integration,Infrastructure,Testing,Documentation,Security"

.PARAMETER SprintCount
    Create this many GitHub Milestones named "Sprint 1", "Sprint 2", ... in the repo.
    Set to 0 to skip.  Default: 0

.PARAMETER SprintLengthDays
    Duration of each sprint in days (used for milestone due dates).  Default: 14

.PARAMETER SprintStartDate
    Start date for Sprint 1 (ISO: YYYY-MM-DD).  Default: today.

.PARAMETER CreateLabels
    Create GitHub issue labels for each Type option.  Requires RepoName.

.PARAMETER SkipIfExists
    Reuse an existing project instead of aborting when it already exists.

.EXAMPLE
    # Minimal -- just sprint fields
    .\onboard-project.ps1 -ProjectTitle "My Service" -Preset basic

.EXAMPLE
    # Full Agile with 6 sprints and type labels
    .\onboard-project.ps1 `
        -ProjectTitle "My Service" `
        -RepoName     "ITlusions/ITL.MyService" `
        -SprintCount  6 `
        -CreateLabels

.EXAMPLE
    # Re-run on existing project (adds any missing fields only)
    .\onboard-project.ps1 -ProjectTitle "Subscription Vending" -SkipIfExists
#>

[CmdletBinding()]
param(
    [string] $Org              = "ITlusions",
    [Parameter(Mandatory)][string] $ProjectTitle,
    [string] $RepoName         = "",
    [ValidateSet("basic","full")]
    [string] $Preset           = "full",
    [string] $CategoryOptions  = "Provisioning,Azure Integration,Infrastructure,Testing,Documentation,Security",
    [int]    $SprintCount      = 0,
    [int]    $SprintLengthDays = 14,
    [string] $SprintStartDate  = (Get-Date -Format "yyyy-MM-dd"),
    [switch] $CreateLabels,
    [switch] $CreateViews,
    [switch] $SkipIfExists
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Helper: GraphQL via gh -f/-F flags
# ---------------------------------------------------------------------------
function Invoke-Gql {
    param([string]$Query, [hashtable]$Variables = @{})
    $ghArgs = [System.Collections.Generic.List[string]]::new()
    $ghArgs.AddRange([string[]]@("api", "graphql", "-f", "query=$Query"))
    foreach ($k in $Variables.Keys) { $ghArgs.Add("-F"); $ghArgs.Add("$k=$($Variables[$k])") }
    $result = (& gh @ghArgs) | ConvertFrom-Json
    if ($result.PSObject.Properties["errors"] -and $null -ne $result.errors) {
        throw ($result.errors | ConvertTo-Json -Depth 5)
    }
    return $result.data
}

$baseSteps = 6
if ($CreateViews)       { $baseSteps++ }
if ($SprintCount -gt 0) { $baseSteps++ }
if ($CreateLabels)      { $baseSteps++ }
$totalSteps = $baseSteps
$step       = 0
function Step { param([string]$Msg); $script:step++; Write-Host "[$script:step/$totalSteps] $Msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------------------
# 1. Auth check
# ---------------------------------------------------------------------------
Step "Checking gh authentication..."
$authOut   = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) { Write-Error "gh CLI not authenticated. Run: gh auth login" }
$scopeLine = $authOut | Where-Object { $_ -match "Token scopes" }
if ($scopeLine -and ($scopeLine -notmatch "project")) {
    Write-Warning "Token may be missing 'project' scope. Re-run: gh auth login --scopes project,repo"
}
Write-Host "  OK" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. Resolve org
# ---------------------------------------------------------------------------
Step "Resolving org '$Org'..."
$orgId = (Invoke-Gql 'query($login: String!) { organization(login: $login) { id } }' @{ login = $Org }).organization.id
Write-Host "  Org ID: $orgId" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. Find or create project
# ---------------------------------------------------------------------------
Step "Finding project '$ProjectTitle'..."
$projList = gh project list --owner $Org --format json | ConvertFrom-Json
$existing = $projList.projects | Where-Object { $_.title -eq $ProjectTitle }

if ($existing) {
    if (-not $SkipIfExists) {
        Write-Error "Project '$ProjectTitle' already exists (#$($existing.number)). Use -SkipIfExists to reuse it."
    }
    $projectNumber = $existing.number
    $projectId     = $existing.id
    Write-Host "  Reusing #$projectNumber (ID: $projectId)" -ForegroundColor Yellow
} else {
    $createQ = 'mutation($ownerId: ID!, $title: String!) { createProjectV2(input: { ownerId: $ownerId, title: $title }) { projectV2 { id number url } } }'
    $pv2     = (Invoke-Gql $createQ @{ ownerId = $orgId; title = $ProjectTitle }).createProjectV2.projectV2
    $projectNumber = $pv2.number
    $projectId     = $pv2.id
    Write-Host "  Created: $($pv2.url)" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 4. Read existing fields
# ---------------------------------------------------------------------------
Step "Reading existing fields..."
$existingFields = (gh project field-list $projectNumber --owner $Org --format json | ConvertFrom-Json).fields |
                    Select-Object -ExpandProperty name
Write-Host "  Found: $($existingFields -join ', ')" -ForegroundColor Gray

# ---------------------------------------------------------------------------
# 5. Add fields
# ---------------------------------------------------------------------------
Step "Adding Agile fields (preset: $Preset)..."

function Add-Field {
    param([string]$Name, [string]$DataType, [string[]]$Options = @())
    if ($existingFields -contains $Name) {
        Write-Host "  SKIP  '$Name' (exists)" -ForegroundColor DarkGray
        return
    }
    if ($DataType -eq "SINGLE_SELECT" -and $Options.Count -gt 0) {
        gh project field-create $projectNumber --owner $Org `
            --name $Name --data-type SINGLE_SELECT `
            --single-select-options ($Options -join ",") | Out-Null
    } else {
        gh project field-create $projectNumber --owner $Org `
            --name $Name --data-type $DataType | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "Failed to create field '$Name'" }
    Write-Host "  + $Name ($DataType)" -ForegroundColor Green
}

# Sprint -- ITERATION only available via GraphQL
if ($existingFields -notcontains "Sprint") {
    $iterQ = 'mutation($pid: ID!, $nm: String!) { createProjectV2Field(input: { projectId: $pid, dataType: ITERATION, name: $nm }) { projectV2Field { ... on ProjectV2IterationField { id name } } } }'
    Invoke-Gql $iterQ @{ pid = $projectId; nm = "Sprint" } | Out-Null
    Write-Host "  + Sprint (ITERATION)" -ForegroundColor Green
} else {
    Write-Host "  SKIP  'Sprint' (exists)" -ForegroundColor DarkGray
}

# --- BASIC fields ---
Add-Field -Name "Priority"     -DataType "SINGLE_SELECT" -Options @("Critical","High","Medium","Low")
Add-Field -Name "Story Points" -DataType "NUMBER"
Add-Field -Name "Category"     -DataType "SINGLE_SELECT" -Options ($CategoryOptions -split ",")

# --- FULL fields ---
if ($Preset -eq "full") {
    Add-Field -Name "Work Type" -DataType "SINGLE_SELECT" -Options @("Epic","Story","Task","Bug","Spike")
    Add-Field -Name "Effort"  -DataType "SINGLE_SELECT" -Options @("XS","S","M","L","XL")
    Add-Field -Name "Epic"    -DataType "TEXT"
    Add-Field -Name "Blocked" -DataType "SINGLE_SELECT" -Options @("No","Yes")
    Add-Field -Name "Risk"    -DataType "SINGLE_SELECT" -Options @("None","Low","Medium","High")
}

# ---------------------------------------------------------------------------
# 6. Link repository
# ---------------------------------------------------------------------------
$repoId = $null
if ($RepoName -ne "") {
    Step "Linking repository '$RepoName'..."
    $parts  = $RepoName -split "/"
    $repoQ  = 'query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { id } }'
    $repoId = (Invoke-Gql $repoQ @{ owner = $parts[0]; name = $parts[1] }).repository.id
    $linkQ  = 'mutation($pid: ID!, $rid: ID!) { linkProjectV2ToRepository(input: { projectId: $pid, repositoryId: $rid }) { repository { nameWithOwner } } }'
    $linked = (Invoke-Gql $linkQ @{ pid = $projectId; rid = $repoId }).linkProjectV2ToRepository.repository.nameWithOwner
    Write-Host "  Linked: $linked" -ForegroundColor Green
} else {
    Step "No repository specified - skipping link."
    Write-Host "  (pass -RepoName owner/repo to link)" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# 7. Generate views setup guide (optional)
# Note: GitHub Projects v2 does not expose view creation via API or CLI.
#       This step queries field IDs and outputs exact setup instructions
#       + filter-query URLs so you can configure views in the UI in seconds.
# ---------------------------------------------------------------------------
if ($CreateViews) {
    Step "Generating views setup guide..."

    # Re-query field node IDs (needed for groupBy references)
    $fq     = 'query($login: String!, $num: Int!) { organization(login: $login) { projectV2(number: $num) { fields(first: 30) { nodes { __typename ... on ProjectV2Field { id name } ... on ProjectV2SingleSelectField { id name } ... on ProjectV2IterationField { id name } } } } } }'
    $fNodes = (Invoke-Gql $fq @{ login = $Org; num = "$projectNumber" }).organization.projectV2.fields.nodes
    $fMap   = @{}
    foreach ($f in $fNodes) {
        if ($f.PSObject.Properties["name"] -and $f.PSObject.Properties["id"]) { $fMap[$f.name] = $f.id }
    }

    $baseUrl = "https://github.com/orgs/$Org/projects/$projectNumber"

    $views = [ordered]@{
        "Board"        = @{ layout = "Board";   groupBy = "Status";   filter = "";                  note = "Kanban by Status" }
        "Sprint Board" = @{ layout = "Board";   groupBy = "Status";   filter = "sprint:@current"; note = "Current sprint only" }
        "Backlog"      = @{ layout = "Table";   groupBy = "Priority"; filter = "";                  note = "All items, sorted by Priority" }
    }
    if ($Preset -eq "full") {
        $views["Epics"] = @{ layout = "Table"; groupBy = "Epic"; filter = ""; note = "Grouped by Epic" }
    }

    Write-Host ""
    Write-Host "  -- Views to create in the GitHub UI --" -ForegroundColor Yellow
    Write-Host "  Open: $baseUrl" -ForegroundColor DarkCyan
    Write-Host ""

    $i = 1
    foreach ($vName in $views.Keys) {
        $v         = $views[$vName]
        $groupId   = if ($fMap.ContainsKey($v.groupBy)) { $fMap[$v.groupBy] } else { "" }
        $url        = if ($v.filter -ne "") { "$baseUrl`?query=$([uri]::EscapeDataString($v.filter))" } else { $baseUrl }

        Write-Host "  [$i] $vName  ($($v.note))" -ForegroundColor White
        Write-Host "      Layout  : $($v.layout)" -ForegroundColor Gray
        Write-Host "      Group by: $($v.groupBy)  (field ID: $groupId)" -ForegroundColor Gray
        if ($v.filter -ne "") {
        Write-Host "      Filter  : $($v.filter)" -ForegroundColor Gray
        Write-Host "      URL     : $url" -ForegroundColor DarkCyan
        }
        Write-Host ""
        $i++
    }

    # Write views config to a file for reference
    $guideFile = Join-Path (Split-Path $PSCommandPath) "views-setup.json"
    $views | ConvertTo-Json -Depth 5 | Set-Content $guideFile -Encoding utf8
    Write-Host "  Guide saved to: $guideFile" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# 8 (was 7). Create sprint milestones (optional)
# ---------------------------------------------------------------------------
if ($SprintCount -gt 0) {
    if ($RepoName -eq "") { Write-Warning "Skipping milestones: -RepoName is required."; $SprintCount = 0 }
}

if ($SprintCount -gt 0) {
    Step "Creating $SprintCount sprint milestones..."
    $start        = [datetime]::ParseExact($SprintStartDate, "yyyy-MM-dd", $null)
    $msRaw        = gh api "repos/$RepoName/milestones?state=all&per_page=100" | ConvertFrom-Json
    $existingMs   = @($msRaw) | Where-Object { $_ -and $_.PSObject.Properties["title"] } | Select-Object -ExpandProperty title

    for ($i = 1; $i -le $SprintCount; $i++) {
        $title  = "Sprint $i"
        $due    = $start.AddDays($SprintLengthDays * $i).ToString("yyyy-MM-ddT00:00:00Z")
        $descr  = "Sprint $i -- $($start.AddDays($SprintLengthDays * ($i - 1)).ToString('dd MMM')) to $($start.AddDays($SprintLengthDays * $i - 1).ToString('dd MMM yyyy'))"

        if ($existingMs -contains $title) {
            Write-Host "  SKIP  '$title' (exists)" -ForegroundColor DarkGray
        } else {
            gh api "repos/$RepoName/milestones" --method POST `
                -f title="$title" -f description="$descr" -f due_on="$due" | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create milestone '$title'" }
            else { Write-Host "  + $title  (due $($start.AddDays($SprintLengthDays * $i).ToString('dd MMM yyyy')))" -ForegroundColor Green }
        }
    }
}

# ---------------------------------------------------------------------------
# 9 (was 8). Create type labels (optional)
# ---------------------------------------------------------------------------
$typeLabelMap = @{
    "Epic"  = @{ color = "6e40c9"; description = "Large body of work spanning multiple sprints" }
    "Story" = @{ color = "0075ca"; description = "User story -- a piece of deliverable value" }
    "Task"  = @{ color = "e4e669"; description = "Technical task or chore" }
    "Bug"   = @{ color = "d73a4a"; description = "Something isn't working" }
    "Spike" = @{ color = "f9d0c4"; description = "Research or investigation task" }
}

if ($CreateLabels) {
    if ($RepoName -eq "") { Write-Warning "Skipping labels: -RepoName is required." }
    else {
        Step "Creating type labels..."
        $labelsRaw      = gh label list -R $RepoName --limit 100 --json name | ConvertFrom-Json
        $existingLabels = @($labelsRaw) | Where-Object { $_ -and $_.PSObject.Properties["name"] } | Select-Object -ExpandProperty name

        foreach ($type in $typeLabelMap.Keys) {
            $labelName = "type:$($type.ToLower())"
            if ($existingLabels -contains $labelName) {
                Write-Host "  SKIP  '$labelName' (exists)" -ForegroundColor DarkGray
            } else {
                gh label create $labelName `
                    --color $typeLabelMap[$type].color `
                    --description $typeLabelMap[$type].description `
                    -R $RepoName | Out-Null
                if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to create label '$labelName'" }
                else { Write-Host "  + $labelName" -ForegroundColor Green }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
$url = "https://github.com/orgs/$Org/projects/$projectNumber"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  '$ProjectTitle' is ready!  (preset: $Preset)" -ForegroundColor White
Write-Host "  Number : #$projectNumber" -ForegroundColor White
Write-Host "  URL    : $url" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Fields added:" -ForegroundColor Yellow
Write-Host "  Sprint, Priority, Story Points, Category"
if ($Preset -eq "full") {
    Write-Host "  Type, Effort, Epic, Blocked, Risk" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Sprint field -> Settings -> set duration + start date"
if ($CreateViews) {
    Write-Host "  2. Create the views listed above (run with -CreateViews for field IDs + URLs)"
} else {
    Write-Host "  2. Re-run with -CreateViews for a views setup guide with exact field IDs"
    Write-Host "     Or create manually: Board (group Status), Sprint Board (filter sprint:@current),"
    Write-Host "     Backlog (table), $(if ($Preset -eq 'full') { 'Epics (group Epic)' })"
}
Write-Host ""