# T1 Teacher availability probe

This directory contains the preregistered, two-request synthetic probe and its fake-HTTP tests. The live probe was run once on 2026-10-11 Asia/Shanghai; its evidence is stored under `D:/AI/runs/shared-ledger/t1-teacher-probe-20261011/`. Do not rerun the live entry point as part of this evidence record.

The probe reads `D:/project/Android/shared-ledger/scripts/ai_teacher_generator/.env` into memory through the existing `live_provider.load_env` parser. It does not write or display the credential. The bounded wrapper adds the preregistered `max_tokens` field and records no request headers.

Run only the fake tests with:

```powershell
& 'D:\project\Android\shared-ledger-agent\agent\.venv\Scripts\python.exe' -m unittest discover -s 'agent\evaluation\t1_teacher_probe\tests' -v
```

The language pilot is a candidate-only synthetic probe. It cannot call tools, modify a ledger, or establish Teacher data quality or Student model quality.
