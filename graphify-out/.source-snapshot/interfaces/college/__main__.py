import sys
from interfaces.college.app import main

main(ensure_backend='--ensure-backend' in sys.argv[1:])
