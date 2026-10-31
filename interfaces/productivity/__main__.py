import argparse

from interfaces.productivity.launcher import main

parser = argparse.ArgumentParser(description='FRIDAY habit tracker and to-do desktop')
parser.add_argument('--view', choices=['today', 'habits', 'tasks'], default='today')
args = parser.parse_args()
main(args.view)
