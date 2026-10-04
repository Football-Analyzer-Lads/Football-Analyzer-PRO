#!/usr/bin/env python3
import os, sys, traceback
from datetime import datetime
BASE=os.path.dirname(__file__)
os.chdir(BASE)
LOG=os.path.join(BASE,'updater.log')
def log(msg):
    with open(LOG,'a',encoding='utf-8') as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
try:
    from app import refresh
    log('Weekly update started')
    d=refresh(force_stats=True)
    errs=d.get('errors',[])
    log(f"Weekly update finished: played={len(d.get('seasons',{}).get('2026/27',[]))} errors={len(errs)}")
    for e in errs: log('ERROR: '+str(e))
except Exception as e:
    log('FATAL: '+repr(e))
    log(traceback.format_exc())
    sys.exit(1)