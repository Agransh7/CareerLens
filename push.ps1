$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

git rev-parse --show-toplevel *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'This folder is not a Git repository yet. Send the GitHub repository URL and I will connect it.'
}

$origin = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0 -or -not $origin) {
    throw 'No GitHub remote named origin is configured. Send the repository URL to connect it.'
}

git check-ignore -q .env
if ($LASTEXITCODE -ne 0) {
    throw '.env is not ignored by Git. Add it to .gitignore before pushing so the API key stays private.'
}

git ls-files --error-unmatch .env *> $null
if ($LASTEXITCODE -eq 0) {
    throw '.env is already tracked by Git. Remove it from the repository index before pushing.'
}

git add -A
if ($LASTEXITCODE -ne 0) { throw 'Could not stage project changes.' }

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host 'No changes to commit.'
    exit 0
}

$message = Read-Host 'Commit message (press Enter for an automatic message)'
if ([string]::IsNullOrWhiteSpace($message)) {
    $message = 'Update CareerLens ' + (Get-Date -Format 'yyyy-MM-dd HH:mm')
}

git commit -m $message
if ($LASTEXITCODE -ne 0) { throw 'Git could not create the commit.' }

$branch = (git branch --show-current).Trim()
if (-not $branch) { throw 'Could not determine the current Git branch.' }
git push -u origin $branch
if ($LASTEXITCODE -ne 0) { throw 'Push failed. Check GitHub sign-in and the remote URL, then rerun this task.' }

Write-Host "Pushed $branch to origin successfully."
