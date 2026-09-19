# Archived prompt-to-deployment implementation

This directory preserves the original intake, extraction, field validation,
hardcoded compiler/templates, Ansible heuristics, guards and deployment scripts.
It is historical source, not part of the active RAG API or a supported deployment
path. Its imports/paths reflect the old application. Nothing here is imported or
executed by the root app.py.

The active system checks architecture readiness before returning a JSON plan.
The calling application owns discussion; separate generators own Terraform/Ansible
files and subsequent execution. See the root README for the current contract.
