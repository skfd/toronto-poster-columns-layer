$taskName = "kk-GuelphHydrantsLayer"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false

Write-Host "Removed scheduled task '$taskName'."
