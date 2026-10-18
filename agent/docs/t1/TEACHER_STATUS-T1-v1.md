# Teacher route and credential metadata status

**Status:** configuration presence checked; no Teacher HTTP request was sent. Availability is `NOT_TESTED`.

The existing `scripts/ai_teacher_generator/.env` in the main repository is present and non-empty. A metadata-only inspection confirmed `TEACHER_PROVIDER=opencode`, `TEACHER_MODEL=deepseek-v4.1-flash`, and route `https://opencode.ai/zen/go/v1/chat/completions`. A credential value is present, but this report deliberately does not reveal it. The file was not copied to the agent worktree; no key was created, changed, or logged. Process environment variables for `TEACHER_*` were absent.

The configured route and model ID match the official [OpenCode Go documentation](https://docs.opencode.ai/docs/go/). This records route configuration only, not HTTP reachability, quota, or authorization. The tiny availability request was intentionally not sent because the user deferred model evaluation until after data freeze and it was not necessary to prepare the evaluator. Do not generate batches or change provider/model routing as part of T1.
