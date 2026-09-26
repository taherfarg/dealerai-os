"""The sales agents: intent, copilot, profile, follow-up.

Unlike the content agents, these do not register themselves with
`agents/base.py`. They are not planned — nobody draws a DAG that contains
"a customer wrote" — so they are called by name from the event handlers, which
open one `agent_runs` row each for the traces to hang from (sales/runs.py).

That also keeps them out of the autonomy gate's approval path, which is
deliberate: in the inbox the person pressing Send is the approval, and an
`approvals` row per draft would queue work for a reviewer who does not exist
(docs/sales/04-ai-copilot.md § 8).
"""
