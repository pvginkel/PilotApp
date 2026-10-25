"""Pilot's MCP server (F83, TD §4.5): a process beside the API, every tool one
REST call to it. It imports nothing of `app`: it reads no database and holds
no state."""
