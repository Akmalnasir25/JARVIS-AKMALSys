"""What does the real chat model actually call when Manuel says cari lagu / play?

This drives _chat_call with the same prompt, the same tool set and the same
history the HUD builds, and records the tool_calls the model returns. No GUI.

Run:  python ui/_yt_route.py
"""
import json
import os, sys
from pathlib import Path

ROOT = Path(r"C:\Users\akmal\jarvis-desktop")
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

import main as J

api = J.Api()
api._emit = lambda *a, **k: None  # silence the orb while probing

s = J.load_json(J.SECRETS, {})
if not s.get("api_key"):
    print("no api_key in secrets.json — cannot probe the model")
    sys.exit(2)

print("model:", api._chat_model(s))

history = []
turns = [
    "cari lagu hindia secukupnya dalam youtube",
    "main lagu tu",
]


def probe(text):
    history.append({"role": "user", "content": text})
    tools = J.tools_for(text, history)
    names = [t["function"]["name"] for t in tools]
    messages = [{"role": "system", "content": J.CHAT_PROMPT}] + history[-20:]
    m = api._chat_call(s, messages, tools)
    calls = m.get("tool_calls") or []
    picked = [(c.get("function", {}).get("name"),
               c.get("function", {}).get("arguments")) for c in calls]
    print("\nUSER:", text)
    print("  tools offered:", ",".join(names))
    if picked:
        for n, a in picked:
            print("  CALLED:", n, (a or "")[:120])
    else:
        print("  CALLED: (none) — replied in prose")
        print("  REPLY:", (m.get("content") or "")[:300])
    history.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
    # A real turn appends one tool result per call. Omitting them is what made
    # the second request 400: an assistant message carrying tool_calls must be
    # followed by a matching tool message for every id.
    for c in calls:
        fn = c.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            result = api._chat_tool(fn.get("name", ""), args)
        except Exception as e:
            result = "Tool gagal: %s" % e
        history.append({"role": "tool", "tool_call_id": c.get("id"), "content": result[:4000]})
        print("  RESULT:", (result or "")[:160].replace("\n", " / "))
    return picked, names


p1, n1 = probe(turns[0])
p2, n2 = probe(turns[1])

print("\n-- verdict --")
names1 = [n for n, _ in p1]
names2 = [n for n, _ in p2]
print("turn 1 called:", names1 or "(none)")
print("turn 2 called:", names2 or "(none)")
if any(n == "open_media" for n in names2):
    print("=> turn 2 routed to open_media, which plays from media/ only — the WEB player is unreachable")
if not any(n == "web_youtube_play" for n in names1 + names2):
    print("=> no tool exists that plays a YouTube result inside the stage")
