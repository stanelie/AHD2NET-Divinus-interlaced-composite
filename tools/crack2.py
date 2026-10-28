import sys, itertools, string
sys.path.insert(0, r"C:/Users/selie/AppData/Local/Temp/pdfdeps")
from passlib.hash import des_crypt
H="Ca/laHEf4BTPI"
words=["xc3511","xmhdipc","ak47agai","helloQN","ubnt","vizxv","admin","root","meinsm",
"7ujMko0admin","7ujMko0vizxv","Zte521","hi3518","hi3511","hi3520","cat1029","jvbzd","anko",
"GMB182","ivdev","OxhlwSG8","oelinux123","klv123","klv1234","tlJwpbo6","cxlinux","winhicom",
"hichiphx","xmhdpc","gw","gweb","gwell","goke","goke2017","Goke2017","GM8136","gm8136",
"password","pass","default","000000","111111","123456","1234567","12345678","888888",
"666666","admin1234","smcadmin","service","supervisor","guest","fliradmin","1111","2601hx",
"hichip","juantech","realtek","dreambox","20080826","admin888","system","hikvision",
"hslwiftv","xljx","9999","daemon","bin","sync","shell","changeme","toor","hi3516","sh","wbox",
"cameras","camera","ipcam","ipcamera","XC3511","HeXhi","hx2011","hxcam","hxvision","easycam"]
# also try short lowercase brute (<=4) + digit variants quickly
for c in words:
    try:
        if des_crypt.verify(c,H): print("FOUND:",repr(c)); sys.exit()
    except: pass
# brute length 1..4 over lowercase+digits (fast enough? des_crypt pure python ~ slow; limit to <=4)
alph=string.ascii_lowercase+string.digits
import time; t=time.time(); n=0
for L in range(1,5):
    for tup in itertools.product(alph, repeat=L):
        s="".join(tup); n+=1
        try:
            if des_crypt.verify(s,H): print("FOUND(brute):",repr(s)); sys.exit()
        except: pass
        if time.time()-t>75:
            print(f"brute stopped at {s!r} after {n} tries, no match"); sys.exit()
print("no match in list+brute")
