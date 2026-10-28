param([string]$Port='COM6',[int]$Baud=115200,
  [string]$Out="$PSScriptRoot\..\firmware\analysis\shell_inspect.log")
$sp=New-Object System.IO.Ports.SerialPort $Port,$Baud,([System.IO.Ports.Parity]::None),8,([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=150; $sp.Handshake=[System.IO.Ports.Handshake]::None; $sp.DtrEnable=$false; $sp.RtsEnable=$false
$sp.Open(); Start-Sleep -Milliseconds 150
$buf=New-Object byte[] 16384
$fs=New-Object System.IO.StreamWriter($Out,$false,[System.Text.Encoding]::ASCII); $fs.AutoFlush=$true
function send([string]$c,[int]$w){
  $fs.Write("`n>>> $c`n"); $sp.Write($c+"`r")
  $e=(Get-Date).AddMilliseconds($w)
  while((Get-Date)-lt $e){ $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}; if($n-gt0){$fs.Write([System.Text.Encoding]::ASCII.GetString($buf,0,$n))} }
}
$sp.Write("`r"); Start-Sleep -Milliseconds 300; try{$sp.DiscardInBuffer()}catch{}
send "mount -t devtmpfs none /dev" 900
send "mount -t proc none /proc" 500
send "mount -t sysfs none /sys" 500
send "mount -t tmpfs none /tmp" 500
send "mount -t debugfs none /sys/kernel/debug" 600
send "sh /etc/init.d/rcS >/tmp/rcs.log 2>&1; echo RCS_DONE" 9000
send "sleep 15; echo SLEPT" 17000
send "pidof camapp" 1200
send "P=`$(pidof camapp); echo PID=`$P" 1000
send "ls -l /proc/`$(pidof camapp)/fd" 2500
send "ls -l /proc/`$(pidof camapp)/fd | grep -iE 'tty|mem|serial'" 1500
send "cat /sys/kernel/debug/gpio" 2500
send "echo PINMUX:; devmem 0x112c0044; devmem 0x112c0030; devmem 0x112c0034; devmem 0x112c0038; devmem 0x112c003c; devmem 0x100c000c" 2500
send "cat /proc/tty/driver/ttyAMA 2>/dev/null; cat /proc/tty/drivers | head" 1500
send "grep -c . /tmp/rcs.log; grep -iE 'ptz_uart|UART' /tmp/rcs.log | tail -6" 1500
$fs.Close(); $sp.Close()
Write-Output "inspect done -> $Out"
