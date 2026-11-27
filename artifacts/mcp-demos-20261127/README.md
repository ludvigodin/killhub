# Killhub MCP demo

Open the [recorded observations](evidence.json) for the first three examples. Finish with the [containment replay](containment-replay.mp4). The evidence comes from the November 27 VX1 run.

| Segment | What to show |
| --- | --- |
| Filesystem | Compare `fs-fault` and `fs-fixed`. Both can read the approved resource. Only the faulty response contains the restricted synthetic marker. |
| Email | Compare `mail-fixed` and `mail-fault`. Read the identical success responses aloud, then reveal the second recipient in the faulty run’s independent delivery journal. |
| Documentation tool | Show the changed description and the two contract hashes under `docs-contract`. Then show the separate OpenCode trace in `opencode_behavior`. The badge operation was excluded from the model’s catalog. |
| Containment | Play the replay. Pause at 5.240 seconds for the worker’s independent confirmation that the VM is gone. The [raw timeline](worker-timeline.jsonl) ends with the public application accepting the follow-up job. |

The harness selected checks from the discovered tools using deterministic rules. The recording demonstrates those checks and the observed OpenCode session. Production planner selection remains unverified.
