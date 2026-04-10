#!/usr/bin/env python3
import sys
import psutil

pid = int(sys.argv[1])
try:
    p = psutil.Process(pid)
    print("PID", pid)
    print("NAME", p.name())
    print("CMD", " ".join(p.cmdline()))
except Exception as e:
    print("ERR", str(e))
