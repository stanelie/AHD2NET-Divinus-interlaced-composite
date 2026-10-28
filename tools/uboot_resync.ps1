param([string]$Port='COM6',[int]$Baud=115200)
$sp = New-Object System.IO.Ports.SerialPort $Port,$Baud,([System.IO.Ports.Parity]::None),8,([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=200; $sp.Handshake=[System.IO.Ports.Handshake]::None
$sp.DtrEnable=$false; $sp.RtsEnable=$false
$sp.Open(); Start-Sleep -Milliseconds 100
# Send Ctrl-C repeatedly to interrupt any running md/loop; drain between
$buf=New-Object byte[] 16384
for($i=0;$i -lt 20;$i++){
  $sp.Write([byte[]]@(3),0,1)          # Ctrl-C
  Start-Sleep -Milliseconds 150
  try{ while($sp.BytesToRead -gt 0){ [void]$sp.Read($buf,0,$buf.Length) } }catch{}
}
# wait for stream to go quiet (board stopped sending)
$quiet=0; $t=Get-Date
while(((Get-Date)-$t).TotalSeconds -lt 30){
  Start-Sleep -Milliseconds 300
  $n=0; try{ $n=$sp.BytesToRead }catch{}
  if($n -gt 0){ try{ while($sp.BytesToRead -gt 0){ [void]$sp.Read($buf,0,$buf.Length) } }catch{}; $quiet=0 }
  else { $quiet++; if($quiet -ge 6){ break } }  # ~1.8s quiet
}
# now ask for a prompt
try{ $sp.DiscardInBuffer() }catch{}
$sp.Write("`r"); Start-Sleep -Milliseconds 300
$sp.Write("version`r"); Start-Sleep -Milliseconds 600
$sb=New-Object System.Text.StringBuilder
$e=(Get-Date).AddSeconds(3)
while((Get-Date) -lt $e){
  $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}
  if($n -gt 0){ [void]$sb.Append(([System.Text.Encoding]::ASCII.GetString($buf,0,$n))) }
}
$sp.Close()
$clean = ($sb.ToString() -replace "[^\x09\x0A\x0D\x20-\x7E]","")
Write-Output "=== after resync ==="
Write-Output $clean
