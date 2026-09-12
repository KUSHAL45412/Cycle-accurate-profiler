from vcdvcd import VCDVCD
import json

vcd = VCDVCD('verilator_tb.vcd')
signals_json = {}
for s, sig in vcd.signals.items():
    signals_json[s] = [{'time': t, 'value': v} for (t, v) in sig.tv]
with open('yourdump.json', 'w') as f:
    json.dump(signals_json, f, indent=2)

