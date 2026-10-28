param([string]$Port='COM6',[int]$Baud=115200,[int]$Seconds=55)
# 1) ask the running firmware to reboot
try{
  $b=[Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:admin"))
  Invoke-RestMethod -Uri "http://10.8.0.236/api/system" -Method Post -Headers @{Authorization="Basic $b"} -ContentType "application/json" -Body '{"action":"reboot"}' -TimeoutSec 5 | Out-Null
  Write-Output "reboot request sent"
}catch{ Write-Output "reboot request: $($_.Exception.Message)" }

# 2) open serial and spam a harmless key (space) to catch 'Hit any key to stop autoboot'
$sp=New-Object System.IO.Ports.SerialPort $Port,$Baud,([System.IO.Ports.Parity]::None),8,([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=50; $sp.Handshake=[System.IO.Ports.Handshake]::None; $sp.DtrEnable=$false; $sp.RtsEnable=$false
$sp.Open()
$space=[byte[]]@(0x20)
$acc=New-Object System.Text.StringBuilder
$buf=New-Object byte[] 8192
$caught=$false
$t=Get-Date
while(((Get-Date)-$t).TotalSeconds -lt $Seconds){
  if(-not $caught){ $sp.Write($space,0,1) }          # spam space until caught
  Start-Sleep -Milliseconds 12
  $n=0; try{ while($sp.BytesToRead -gt 0){ $n=$sp.Read($buf,0,$buf.Length); [void]$acc.Append([System.Text.Encoding]::ASCII.GetString($buf,0,$n)) } }catch{}
  $s=$acc.ToString()
  if(-not $caught -and ($s -match "stop autoboot")){
    $caught=$true
    Start-Sleep -Milliseconds 250        # let a couple more spaces land to ensure interrupt
  }
  if($caught){
    # stop spamming; drain, send CR, look for prompt
    Start-Sleep -Milliseconds 400
    try{ while($sp.BytesToRead -gt 0){ $n=$sp.Read($buf,0,$buf.Length); [void]$acc.Append([System.Text.Encoding]::ASCII.GetString($buf,0,$n)) } }catch{}
    $sp.Write("`r"); Start-Sleep -Milliseconds 400
    try{ while($sp.BytesToRead -gt 0){ $n=$sp.Read($buf,0,$buf.Length); [void]$acc.Append([System.Text.Encoding]::ASCII.GetString($buf,0,$n)) } }catch{}
    break
  }
}
$sp.Close()
$clean=($acc.ToString() -replace "[^\x09\x0A\x0D\x20-\x7E]","")
$lines=$clean -split "`n"
Write-Output "=== caught=$caught ; last 12 lines ==="
$lines | Select-Object -Last 12
