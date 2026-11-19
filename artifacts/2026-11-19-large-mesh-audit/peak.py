"""Run a command and print its exit code, peak resident memory and wall time."""
import resource
import subprocess
import sys
import time

t = time.time()
p = subprocess.run(sys.argv[1:])
print(f"{p.returncode}\t{resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024}\t{time.time() - t:.0f}")
