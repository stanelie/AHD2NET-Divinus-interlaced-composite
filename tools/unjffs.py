import sys
sys.path.insert(0, r"C:/Users/selie/AppData/Local/Temp/pdfdeps")
from jefferson.cli import main
sys.argv = ["jefferson", sys.argv[1], "-d", sys.argv[2], "-f"]
main()
