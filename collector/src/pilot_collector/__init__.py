"""Pilot's collector (F152.1): it reads the Claude Code transcripts on a
fleet's home and publishes each one's facts into Pilot's record. It holds no
database and nothing of the app: what passes between it and Pilot is the
package `pilot-collection`."""

VERSION = "1.3.0"
"""The collector's version, which every publication names as the one that
read the file. It names how a file is read, and Pilot's inventory holds it
for each transcript: a walk publishes again every transcript read under
another version (F152.2), so it changes with a release that reads a file
differently and with no other."""
