param([string]$Port='COM6',[int]$Baud=115200,[int]$Seconds=35,
  [string]$Out="$PSScriptRoot\..\firmware\analysis\shell_boot.log")
$BA = "mem=36M console=ttyAMA0,115200 loglevel=0 root=/dev/mtdblock3 rootfstype=squashfs rw mtdparts=sfc:128K(boot),64K(env),1792K(kernel),3M(rootfs),-(usr) mmz_allocator=xmedia mmz=anonymous,0,0x42400000,28M chip=gk7205ev200 sensors=sc200ai g_cmos_yuv_flag=1 board=demo init=/bin/sh"
$sp=New-Object System.IO.Ports.SerialPort $Port,$Baud,([System.IO.Ports.Parity]::None),8,([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=150; $sp.Handshake=[System.IO.Ports.Handshake]::None; $sp.DtrEnable=$false; $sp.RtsEnable=$false
$sp.Open(); Start-Sleep -Milliseconds 150
$buf=New-Object byte[] 16384
$fs=New-Object System.IO.StreamWriter($Out,$false,[System.Text.Encoding]::ASCII); $fs.AutoFlush=$true
function send([string]$c,[int]$w){ $sp.Write($c+"`r"); $e=(Get-Date).AddMilliseconds($w); while((Get-Date)-lt $e){ $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}; if($n-gt0){$fs.Write([System.Text.Encoding]::ASCII.GetString($buf,0,$n))} } }
$sp.Write("`r"); Start-Sleep -Milliseconds 300; try{$sp.DiscardInBuffer()}catch{}
send "setenv bootargs $BA" 800
send "sf probe 0" 800
send "xmediaapp" 2500
send "sf read 0x41000000 0x30000 0x200000" 3000
$sp.Write("bootm 0x41000000`r")
# stream the boot, then poke for a shell prompt near the end
$t=Get-Date
while(((Get-Date)-$t).TotalSeconds -lt ($Seconds-6)){ $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}; if($n-gt0){$fs.Write([System.Text.Encoding]::ASCII.GetString($buf,0,$n))} }
# confirm shell: send marker commands
send "" 300
send "echo __SHELL_OK__ `$(id -u 2>/dev/null)" 1500
send "uname -a" 1200
$fs.Close(); $sp.Close()
$txt=(Get-Content $Out -Raw) -replace "[^\x09\x0A\x0D\x20-\x7E]",""
Write-Output "=== last 18 lines ==="
($txt -split "`n") | Select-Object -Last 18
