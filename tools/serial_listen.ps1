param(
  [string]$Port = 'COM6',
  [int]$Baud = 115200,
  [int]$Seconds = 120,
  [string]$Out = "$PSScriptRoot\boot.log"
)
# Fresh capture each run
$raw = "$Out.bin"
Remove-Item -Force -ErrorAction SilentlyContinue $Out, $raw

$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout = 500
$sp.Handshake = [System.IO.Ports.Handshake]::None
# Do NOT drive DTR/RTS; some boards reset or hold-in-reset off these lines
$sp.DtrEnable = $false
$sp.RtsEnable = $false
try { $sp.Open() } catch { Write-Output "OPEN FAILED: $($_.Exception.Message)"; exit 1 }

$fs = [System.IO.File]::Open($raw, 'Create', 'Write', 'Read')
$sw = New-Object System.IO.StreamWriter($Out, $false, [System.Text.Encoding]::UTF8)
$buf = New-Object byte[] 4096
$deadline = (Get-Date).AddSeconds($Seconds)
$total = 0
Write-Output "LISTENING on $Port @ $Baud 8N1 for $Seconds s. Power the board now."
while ((Get-Date) -lt $deadline) {
  try {
    $n = $sp.Read($buf, 0, $buf.Length)
    if ($n -gt 0) {
      $fs.Write($buf, 0, $n); $fs.Flush()
      $txt = [System.Text.Encoding]::ASCII.GetString($buf, 0, $n)
      $sw.Write($txt); $sw.Flush()
      $total += $n
    }
  } catch [TimeoutException] { }
}
$sp.Close(); $fs.Close(); $sw.Close()
Write-Output "DONE. Captured $total bytes -> $Out (ascii) / $raw (raw)"
