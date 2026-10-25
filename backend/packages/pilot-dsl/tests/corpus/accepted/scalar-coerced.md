# How many loaves per tray?

```decision id=D1
options:
  - 2
  - 3: tighter, one more per bake
  - Yes
  - No
recommend: 3
answer: 2
by: ada
at: 2026-10-12T12:34:00Z
```

```question id=Q1
default: 2026-10-12
answer: No
by: ben
```

```decision id=C1
type: confirmation
because: rider
proposal: Bake the extra tray
answer: Yes
by: ada
```
