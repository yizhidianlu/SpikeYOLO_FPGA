# capture_uart.ps1 — capture ZYBO USB-UART (COM3 / 115200 8N1) to a file.
# Stop with Ctrl+C or after $TimeoutSec seconds.
param(
    [string]$Port = "COM3",
    [int]$Baud = 115200,
    [string]$OutFile = "runs/remote_machine/w9_pbt_uart.log",
    [int]$TimeoutSec = 120
)

$ErrorActionPreference = "Stop"
$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, "None", 8, "One"
$sp.NewLine = "`n"
$sp.ReadTimeout = 1000
$sp.Open()
Write-Host "[uart] $Port @ $Baud opened — capturing to $OutFile (timeout $TimeoutSec s)"
$start = Get-Date
$buf = ""
$writer = [System.IO.StreamWriter]::new((Resolve-Path -LiteralPath . | Select-Object -ExpandProperty Path) + "\\$OutFile", $false)
$writer.AutoFlush = $true
try {
    while ((Get-Date) - $start -lt [TimeSpan]::FromSeconds($TimeoutSec)) {
        try {
            $line = $sp.ReadLine()
            $writer.WriteLine($line)
            Write-Host $line
            if ($line -match "output fnv1a32 = 0x" -or $line -match "\*\*\* PASS \*\*\*" -or $line -match "TIMEOUT") {
                # Capture one more second of trailing output, then exit
                Start-Sleep -Seconds 2
                while ($sp.BytesToRead -gt 0) {
                    $line2 = $sp.ReadLine()
                    $writer.WriteLine($line2)
                    Write-Host $line2
                }
                Write-Host "[uart] saw terminator; closing"
                break
            }
        } catch [System.TimeoutException] {
            # keep polling
        }
    }
} finally {
    $writer.Close()
    $sp.Close()
    Write-Host "[uart] closed"
}
