"""Real Toad CLI with all-thread stack dumps on SIGUSR1, for the target-menu wait."""
import faulthandler, signal
from pathlib import Path
from toad.cli import main
OUT = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live') / __import__('os').environ['MENU_RUN']
stacks = (OUT / 'stacks.txt').open('w')
faulthandler.register(signal.SIGUSR1, file=stacks, all_threads=True)
if __name__ == '__main__':
    main()
