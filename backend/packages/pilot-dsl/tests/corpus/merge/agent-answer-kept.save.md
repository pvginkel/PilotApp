---
title: Which tent for the trip?
summary: Two nights at the lake.
---

# Which tent for the trip?

The forecast says rain on the second night.

```decision id=D1
options:
  - Dome: sleeps four
  - Tunnel: sleeps six
recommend: Dome
answer: Tunnel
by: ada
at: 2026-10-12T09:40:00Z
note: The cousins are coming.
```

```question id=Q1
default: The lake car park
answer: deferred
by: agent
at: 2026-10-12T10:00:00Z
to: build
note: Ask once the route is fixed.
```

```action id=A1
answer: deferred
by: agent
to: plan
```
