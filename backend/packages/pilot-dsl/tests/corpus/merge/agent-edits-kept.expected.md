---
title: Which tent for the trip?
summary: Two nights at the lake, by car.
---

# Which tent for the trip?

The forecast says rain on the second night.
Pack the tarp.

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
answer: The village hall
by: agent
at: 2026-10-12T09:00:00Z
```

```action id=A1
check: the tent is in the car
```

```question id=Q2
default: Two
```
