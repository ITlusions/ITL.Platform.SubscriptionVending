<#
.SYNOPSIS
    Onboard a GitHub Project (v2) with sprint planning fields.

.DESCRIPTION
    Creates or reuses an existing GitHub ProjectV2 in an organisation and adds:
      - Sprint       (Iteration)
      - Priority     (Single Select: Critical / High / Medium / Low)
      - Story Points (Number)
      - Category     (Single Select: configurable)

    Requires the GitHub CLI (gh) authenticated with the "project" scope:
      gh auth login --scopes project

.PARAMETER Org
    GitHub organisation login.  Default: ITlusions

.PARAMETER ProjectTitle
    Display title for the project.

.PARAMETER RepoName
    Optional repository to link (format: owner/repo).

.PARAMETER CategoryOptions
    Comma-separated Category options.
    Default: "Provisioning,Azure Integration,Infrastructure,Testing,Documentation,Security"

.PARAMETER SkipIfExists
    Reuse an existing project with the same title instead of aborting.

.EXAMPLE
    .\onboard-project.ps1 -ProjectTitle "My New Service" -RepoName "ITlusions/ITL.MyService"

.EXAMPLE
    .\onboard-project.ps1 -ProjectTitle "Subscription Vending" -SkipIfExists
#>

[CmdletBinding()]
param(
    [string]  $Org             = "ITlusions",
    [Parameter(Mandatory)][string] $ProjectTitle,
    [string]  $RepoName        = "",
    [string]  $CategoryOptions = "Provisioning,Azure Integration,Infrastructure,Testing,Documentation,Security",
    [switch]  $SkipIfExists
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Helper: call gh api graphql with query + optional variables hashtable
# Variables are passed as -F key=value (gh handles the typing)
# ---------------------------------------------------------------------------
function Invoke-Gql {
    param(
        [string]    $Query,
        [hashtable] $Variables = @{}
    )
    $ghArgs = [System.Collections.Generic.List[string]]::new()
    $ghArgs.AddRange([string[]]@("api", "graphql", "-f", "query=$Query"))
    foreach ($k in $Variables.Keys) {
        $ghArgs.Add("-F")
        $ghArgs.Add("$k=$($Variables[$k])")
    }
    $raw    = & gh @ghArgs
    $result = $raw | ConvertFrom-Json
    if ($result.PSObject.Properties["errors"] -and $null -ne $result.errors) {
        throw ($result.errors | ConvertTo-Json -Depth 5)
    }
    return $result.data
}

# ---------------------------------------------------------------------------
# 1. Check gh auth
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[1/6] Checking gh authentication..." -ForegroundColor Cyan
$authOut = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "gh CLI is not authenticated. Run: gh auth login"
}
$scopeLine = $authOut | Where-Object { $_ -match "Token scopes" }
if ($scopeLine -and ($scopeLine -notmatch "project")) {
    Write-Warning "Token may be missing 'project' scope. Re-run: gh auth login --scopes project"
}
Write-Host "  OK" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. Resolve org node ID
# ---------------------------------------------------------------------------
Write-Host "[2/6] Resolving org '$Org'..." -ForegroundColor Cyan
$orgData = Invoke-Gql -Query 'query($login: String!) { organization(login: $login) { id } }' -Variables @{ login = $Org }
$orgId   = $orgData.organization.id
Write-Host "  Org ID: $orgId" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. Find or create project
# ---------------------------------------------------------------------------
Write-Host "[3/6] Looking for existing project '$ProjectTitle'..." -ForegroundColor Cyan
$projList = gh project list --owner $Org --format json | ConvertFrom-Json
$existing = $projList.projects | Where-Object { $_.title -eq $ProjectTitle }

if ($existing) {
    if (-not $SkipIfExists) {
        Write-Error "Project '$ProjectTitle' already exists (#$($existing.number)). Use -SkipIfExists to reuse it."
    }
    $projectNumber = $existing.number
    $projectId     = $existing.id
    Write-Host "  Reusing existing project #$projectNumber (ID: $projectId)" -ForegroundColor Yellow
} else {
    Write-Host "[3/6] Creating project '$ProjectTitle'..." -ForegroundColor Cyan
    $createQ   = 'mutation($ownerId: ID!, $title: String!) { createProjectV2(input: { ownerId: $ownerId, title: $title }) { projectV2 { id number url } } }'
    $pv2       = (Invoke-Gql -Query $createQ -Variables @{ ownerId = $orgId; title = $ProjectTitle }).createProjectV2.projectV2
    $projectId     = $pv2.id
    $projectNumber = $pv2.number
    Write-Host "  Created: $($pv2.url)" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 4. Read existing fields
# ---------------------------------------------------------------------------
Write-Host "[4/6] Reading existing fields..." -ForegroundColor Cyan
$fieldJson      = gh project field-list $projectNumber --owner $Org --format json | ConvertFrom-Json
$existingFields = $fieldJson.fields | Select-Object -ExpandProperty name
Write-Host "  Fields: $($existingFields -join ', ')" -ForegroundColor Gray

# ---------------------------------------------------------------------------
# 5. Add missing sprint planning fields
# ---------------------------------------------------------------------------
Write-Host "[5/6] Adding sprint planning fields..." -ForegroundColor Cyan

function Add-Field {
    param([string]$Name, [string]$DataType, [string[]]$Options = @())
    if ($existingFields -contains $Name) {
        Write-Host "  SKIP '$Name' (already exists)" -ForegroundColor DarkGray
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

# Sprint uses ITERATION type -- only createable via GraphQL (gh CLI does not expose it)
if ($existingFields -notcontains "Sprint") {
    $iterQ = 'mutation($pid: ID!, $nm: String!) { createProjectV2Field(input: { projectId: $pid, dataType: ITERATION, name: $nm }) { projectV2Field { ... on ProjectV2IterationField { id name } } } }'
    Invoke-Gql -Query $iterQ -Variables @{ pid = $projectId; nm = "Sprint" } | Out-Null
    Write-Host "  + Sprint (ITERATION)" -ForegroundColor Green
} else {
    Write-Host "  SKIP 'Sprint' (already exists)" -ForegroundColor DarkGray
}

Add-Field -Name "Priority"     -DataType "SINGLE_SELECT" -Options @("Critical","High","Medium","Low")
Add-Field -Name "Story Points" -DataType "NUMBER"
Add-Field -Name "Category"     -DataType "SINGLE_SELECT" -Options ($CategoryOptions -split ",")

# ---------------------------------------------------------------------------
# 6. Link repository (optional)
# ---------------------------------------------------------------------------
if ($RepoName -ne "") {
    Write-Host "[6/6] Linking repository '$RepoName'..." -ForegroundColor Cyan
    $parts  = $RepoName -split "/"
    $repoQ  = 'query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { id } }'
    $repoId = (Invoke-Gql -Query $repoQ -Variables @{ owner = $parts[0]; name = $parts[1] }).repository.id

    $linkQ  = 'mutation($pid: ID!, $rid: ID!) { linkProjectV2ToRepository(input: { projectId: $pid, repositoryId: $rid }) { repository { nameWithOwner } } }'
    $linked = (Invoke-Gql -Query $linkQ -Variables @{ pid = $projectId; rid = $repoId }).linkProjectV2ToRepository.repository.nameWithOwner
    Write-Host "  Linked: $linked" -ForegroundColor Green
} else {
    Write-Host "[6/6] No repository specified - skipping link." -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  '$ProjectTitle' is ready for sprints!" -ForegroundColor White
Write-Host "  Number : #$projectNumber" -ForegroundColor White
Write-Host "  URL    : https://github.com/orgs/$Org/projects/$projectNumber" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps (in the GitHub UI):" -ForegroundColor Yellow
Write-Host "  1. Sprint field -> Settings -> set duration + start date"
Write-Host "  2. Add a Board view (group by Status)"
Write-Host "  3. Add a Sprint view (filter: current iteration)"
Write-Host "  4. Assign Priority + Sprint to existing issues"
Write-Host ""