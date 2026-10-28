param([string]$Port='COM6',[int]$Baud=115200,
  [string]$Out="$PSScriptRoot\..\firmware\analysis\uart_regs.log")
$sp=New-Object System.IO.Ports.SerialPort $Port,$Baud,([System.IO.Ports.Parity]::None),8,([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=150; $sp.Handshake=[System.IO.Ports.Handshake]::None; $sp.DtrEnable=$false; $sp.RtsEnable=$false
$sp.Open(); Start-Sleep -Milliseconds 150
$buf=New-Object byte[] 16384
$fs=New-Object System.IO.StreamWriter($Out,$false,[System.Text.Encoding]::ASCII); $fs.AutoFlush=$true
function send([string]$c,[int]$w){ $fs.Write("`n>>> $c`n"); $sp.Write($c+"`r"); $e=(Get-Date).AddMilliseconds($w); while((Get-Date)-lt $e){ $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}; if($n-gt0){$fs.Write([System.Text.Encoding]::ASCII.GetString($buf,0,$n))} } }
$sp.Write("`r"); Start-Sleep -Milliseconds 300; try{$sp.DiscardInBuffer()}catch{}
# PL011 regs: 0x18 FR, 0x24 IBRD, 0x28 FBRD, 0x2C LCRH, 0x30 CR
foreach($u in @(@('ttyAMA0_console',0x12040000),@('ttyAMA1',0x12041000),@('ttyAMA2',0x12042000))){
  $name=$u[0]; $base=$u[1]
  $ibrd='0x{0:X8}' -f ($base+0x24); $fbrd='0x{0:X8}' -f ($base+0x28)
  $lcrh='0x{0:X8}' -f ($base+0x2C); $cr='0x{0:X8}' -f ($base+0x30)
  send "echo $name IBRD FBRD LCRH CR:; devmem $ibrd; devmem $fbrd; devmem $lcrh; devmem $cr" 2200
}
$fs.Close(); $sp.Close()
Write-Output "uart regs done -> $Out"
