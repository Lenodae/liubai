"""Reproducible synthetic workload in a disposable database; no real task reads."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = """
import datetime as dt, json, statistics, time, uuid
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from tasks.models import Task
from execution.models import TimeEntry
from load_analysis.workspace import build
from load_analysis.deadlines import get
u=get_user_model().objects.create_user('synthetic_benchmark')
today=timezone.localdate(); week=today-dt.timedelta(days=today.weekday())
tasks=[Task(owner=u,title=f'Synthetic {i}',status='in_progress',request_key=uuid.uuid4(),request_fingerprint='benchmark') for i in range(1000)]
Task.objects.bulk_create(tasks)
TimeEntry.objects.bulk_create([TimeEntry(task=tasks[i%1000],date=today,minutes=15) for i in range(10000)],batch_size=500)
result={}
for name,fn in [('workspace',build),('deadlines',get)]:
    samples=[]
    for _ in range(5):
        with CaptureQueriesContext(connection) as q:
            started=time.perf_counter(); data=fn(u.pk,week,'week'); samples.append(time.perf_counter()-started)
    result[name]={'median_seconds':round(statistics.median(samples),4),'max_seconds':round(max(samples),4),'queries':len(q)}
assert data['work'] and len(data['work'])==1000
assert build(u.pk,week,'week')['actual']['minutes']==150000
print(json.dumps({'tasks':1000,'time_entries':10000,'results':result}))
"""
with tempfile.TemporaryDirectory(prefix="liubai-load-bench-") as tmp:
    env = {**os.environ, "TASKFLOW_STATE_DIR": tmp, "TASKFLOW_DB": str(Path(tmp) / "db.sqlite3")}
    python = str(ROOT / ".venv/bin/python")
    subprocess.run(
        [python, "manage.py", "migrate", "--noinput"],
        cwd=ROOT,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    run = subprocess.run(
        [python, "manage.py", "shell", "-c", SCRIPT],
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(run.stdout.strip().splitlines()[-1])
    (ROOT / "evidence/load-benchmark.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
