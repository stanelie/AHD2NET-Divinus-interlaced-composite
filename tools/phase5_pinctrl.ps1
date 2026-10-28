param([string]$Port='COM6',[int]$Baud=115200,
  [string]$Out="$PSScriptRoot\..\firmware\analysis\pinctrl.log")
$sp=New-Object System.IO.Ports.SerialPort $Port,$Baud,([System.IO.Ports.Parity]::None),8,([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=150; $sp.Handshake=[System.IO.Ports.Handshake]::None; $sp.DtrEnable=$false; $sp.RtsEnable=$false
$sp.Open(); Start-Sleep -Milliseconds 150
$buf=New-Object byte[] 16384
$fs=New-Object System.IO.StreamWriter($Out,$false,[System.Text.Encoding]::ASCII); $fs.AutoFlush=$true
function send([string]$c,[int]$w){ $fs.Write("`n>>> $c`n"); $sp.Write($c+"`r"); $e=(Get-Date).AddMilliseconds($w); while((Get-Date)-lt $e){ $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}; if($n-gt0){$fs.Write([System.Text.Encoding]::ASCII.GetString($buf,0,$n))} } }
$sp.Write("`r"); Start-Sleep -Milliseconds 300; try{$sp.DiscardInBuffer()}catch{}
send "ls /sys/kernel/debug/pinctrl/ 2>/dev/null" 1200
send "cat /sys/kernel/debug/pinctrl/*/pinmux-pins 2>/dev/null | grep -iE 'uart|UART' | head -20" 1500
# dump full live IOMUX table 0x112c0000..0x112c0080 for the record
send "for o in 00 04 08 0c 10 14 18 1c 20 24 28 2c 30 34 38 3c 40 44 48 4c 50 54 58 5c 60 64 68 6c 70 74; do printf '112c00%s = ' \$o; devmem 0x112c00\$o; done" 4000
$fs.Close(); $sp.Close()
Write-Output "pinctrl done -> $Out"
