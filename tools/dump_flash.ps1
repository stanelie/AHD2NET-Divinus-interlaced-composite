param(
  [string]$Port = 'COM6',
  [int]$Baud = 115200,
  [string]$LoadAddr = '0x42000000',
  [string]$Size = '0x800000',
  [string]$Out = "$PSScriptRoot\flash.hex",
  [int]$MaxMinutes = 90
)
Remove-Item -Force -ErrorAction SilentlyContinue $Out

$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout = 200
$sp.Handshake = [System.IO.Ports.Handshake]::None
$sp.DtrEnable = $false
$sp.RtsEnable = $false
$sp.ReadBufferSize = 65536
try { $sp.Open() } catch { Write-Output "OPEN FAILED: $($_.Exception.Message)"; exit 1 }
Start-Sleep -Milliseconds 150
try { $sp.DiscardInBuffer() } catch {}

function ReadWindow([int]$ms) {
  $buf = New-Object byte[] 16384
  $sb = New-Object System.Text.StringBuilder
  $end = (Get-Date).AddMilliseconds($ms)
  while ((Get-Date) -lt $end) {
    $n = 0; try { $n = $sp.Read($buf,0,$buf.Length) } catch [TimeoutException] { $n = 0 }
    if ($n -gt 0) { [void]$sb.Append([System.Text.Encoding]::ASCII.GetString($buf,0,$n)) }
  }
  return $sb.ToString()
}

# wake + load flash into RAM
$sp.Write("`r"); [void](ReadWindow 400)
Write-Output "Loading $Size bytes from flash to RAM at $LoadAddr ..."
$sp.Write("sf read $LoadAddr 0x0 $Size`r")
$r = ReadWindow 20000
Write-Output $r
if ($r -notmatch 'Read: OK') { Write-Output "SF READ did not confirm OK - aborting."; $sp.Close(); exit 2 }

# stream the dump
$fs = New-Object System.IO.StreamWriter($Out, $false, [System.Text.Encoding]::ASCII)
$fs.AutoFlush = $false
Write-Output "Dumping md.b $LoadAddr $Size ..."
$sp.Write("md.b $LoadAddr $Size`r")

$buf = New-Object byte[] 16384
$total = 0
$lastData = Get-Date
$start = Get-Date
$flushAt = 0
while ($true) {
  $n = 0; try { $n = $sp.Read($buf,0,$buf.Length) } catch [TimeoutException] { $n = 0 }
  if ($n -gt 0) {
    $fs.Write([System.Text.Encoding]::ASCII.GetString($buf,0,$n))
    $total += $n; $lastData = Get-Date
    if ($total - $flushAt -ge 262144) { $fs.Flush(); $flushAt = $total }
  }
  $idle = ((Get-Date) - $lastData).TotalMilliseconds
  if ($total -gt 1000 -and $idle -ge 6000) { break }       # stream ended
  if (((Get-Date) - $start).TotalMinutes -ge $MaxMinutes) { Write-Output "MAX TIME HIT"; break }
}
$fs.Flush(); $fs.Close(); $sp.Close()
$mins = [math]::Round(((Get-Date) - $start).TotalMinutes,1)
Write-Output "DONE. Captured $total chars in $mins min -> $Out"
