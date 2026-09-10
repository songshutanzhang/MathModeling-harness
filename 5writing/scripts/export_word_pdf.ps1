param([Parameter(Mandatory=$true)][string]$InputDoc, [Parameter(Mandatory=$true)][string]$OutputPdf)
$ErrorActionPreference = 'Stop'
$wordInstance = $null
$wordDocument = $null
try {
    $wordInstance = New-Object -ComObject Word.Application
    $wordInstance.Visible = $false
    $wordInstance.DisplayAlerts = 0
    $wordDocument = $wordInstance.Documents.Open($InputDoc, $false, $true)
    [void]$wordDocument.Fields.Update()
    $wordDocument.ExportAsFixedFormat($OutputPdf, 17)
} finally {
    if ($null -ne $wordDocument) {
        $wordDocument.Close($false)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordDocument)
    }
    if ($null -ne $wordInstance) {
        $wordInstance.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordInstance)
    }
}
