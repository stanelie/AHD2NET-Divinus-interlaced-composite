param(
  [string]$Port = 'COM6',
  [int]$Baud = 115200,
  [string[]]$Cmds = @(''),
  [int]$IdleMs = 400,
  [int]$MaxMs = 8000
)
$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout = 150
$sp.Handshake = [System.IO.Ports.Handshake]::None
$sp.NewLine = "`r"
$sp.DtrEnable = $false
$sp.RtsEnable = $false
try { $sp.Open() } catch { Write-Output "OPEN FAILED: $($_.Exception.Message)"; exit 1 }
Start-Sleep -Milliseconds 100
try { $sp.DiscardInBuffer() } catch {}

function ReadUntilIdle {
  $buf = New-Object byte[] 8192
  $sb = New-Object System.Text.StringBuilder
  $last = Get-Date
  $start = Get-Date
  while ($true) {
    $n = 0
    try { $n = $sp.Read($buf, 0, $buf.Length) } catch [TimeoutException] { $n = 0 }
    if ($n -gt 0) {
      [void]$sb.Append([System.Text.Encoding]::ASCII.GetString($buf, 0, $n))
      $last = Get-Date
    }
    if (((Get-Date) - $last).TotalMilliseconds -ge $IdleMs) { break }
    if (((Get-Date) - $start).TotalMilliseconds -ge $MaxMs) { break }
  }
  return $sb.ToString()
}

# wake prompt
$sp.Write("`r")
[void](ReadUntilIdle)

foreach ($c in $Cmds) {
  Write-Output "===CMD=== $c"
  $sp.Write($c + "`r")
  $out = ReadUntilIdle
  # strip non-printables except tab/newline
  $clean = ($out -replace "[^\x09\x0A\x0D\x20-\x7E]", '')
  Write-Output $clean
}
$sp.Close()
