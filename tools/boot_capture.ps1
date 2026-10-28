param(
  [string]$Port='COM6',[int]$Baud=115200,[int]$Seconds=110,
  [string]$Out="$PSScriptRoot\..\firmware\analysis\verbose_boot.log"
)
$BOOTARGS = "mem=36M console=ttyAMA0,115200 loglevel=8 ignore_loglevel root=/dev/mtdblock3 rootfstype=squashfs rw mtdparts=sfc:128K(boot),64K(env),1792K(kernel),3M(rootfs),-(usr) mmz_allocator=xmedia mmz=anonymous,0,0x42400000,28M chip=gk7205ev200 sensors=sc200ai g_cmos_yuv_flag=1 board=demo"
$sp=New-Object System.IO.Ports.SerialPort $Port,$Baud,([System.IO.Ports.Parity]::None),8,([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=200; $sp.Handshake=[System.IO.Ports.Handshake]::None; $sp.DtrEnable=$false; $sp.RtsEnable=$false
$sp.Open(); Start-Sleep -Milliseconds 120; try{$sp.DiscardInBuffer()}catch{}
$buf=New-Object byte[] 16384
$fs=New-Object System.IO.StreamWriter($Out,$false,[System.Text.Encoding]::ASCII); $fs.AutoFlush=$true
function send([string]$cmd,[int]$waitms){
  $sp.Write($cmd + "`r")
  $e=(Get-Date).AddMilliseconds($waitms)
  while((Get-Date) -lt $e){ $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}; if($n -gt 0){ $fs.Write(([System.Text.Encoding]::ASCII.GetString($buf,0,$n))) } }
}
$sp.Write("`r"); Start-Sleep -Milliseconds 300; try{$sp.DiscardInBuffer()}catch{}
send "setenv bootargs $BOOTARGS" 800
send "sf probe 0" 800
send "xmediaapp" 2500
send "sf read 0x41000000 0x30000 0x200000" 3000
# kick off boot, then stream for the rest of the window
$sp.Write("bootm 0x41000000`r")
$t=Get-Date
while(((Get-Date)-$t).TotalSeconds -lt $Seconds){
  $n=0; try{$n=$sp.Read($buf,0,$buf.Length)}catch{$n=0}
  if($n -gt 0){ $fs.Write(([System.Text.Encoding]::ASCII.GetString($buf,0,$n))) }
}
$fs.Close(); $sp.Close()
Write-Output "boot capture done -> $Out"
