"""Import a checked snapshot for the weekly chat-assisted update."""
import argparse, json
import server

p=argparse.ArgumentParser();p.add_argument('--input',required=True);a=p.parse_args()
incoming=server.validate_snapshot(json.loads(open(a.input,encoding='utf-8').read()))
with server.LOCK:
    old=server.source_snapshot(); merged=server.merge_snapshot(old,incoming); changes=server.changes_between(old,merged)
    server.atomic_write(server.SNAPSHOT,merged)
    server.atomic_write(server.HISTORY,(changes+server.read_json(server.HISTORY,[]))[:500])
print(f'Imported {len(incoming["tasks"])} supplied tasks; active snapshot has {len(merged["tasks"])} tasks; {len(changes)} changes recorded.')
