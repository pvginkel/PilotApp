# Which cache for the price list?

The price list is read on every page view. Two ways to keep it warm:

- answer: this list item is prose, not an answer
- options: and neither is this one

| store | cost |
|---|---|
| memory | none |

```decision id=D1
options:
  - Memory: in the process, lost on restart
  - Redis: a sidecar, kept across restarts
recommend: Memory
```

Prose after the block, with `by: carol` in it, is never read.

<!-- a comment is prose too -->
