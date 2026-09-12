# report.py
import math
import matplotlib.pyplot as plt
from config import AREA_COST, TOTAL_AREA

def print_ext_breakdown(ext_counts, ext_cycles, total_cycles, label="PREDICTED"):
    total_instr = sum(ext_counts.values())
    print(f"\n[ {label} Extension Breakdown ]\n")
    print(f"  {'Ext':<10} {'Count':>9} {'Use%':>6} {'Pred Cycles':>12} "
          f"{'Cyc%':>6} {'AvgCPI':>7} {'Area%':>6}  Verdict")
    print("  " + "-" * 78)
    for ext in AREA_COST:
        count  = ext_counts.get(ext, 0)
        cycles = ext_cycles.get(ext, 0)
        if count == 0 and ext != 'I': continue
        avg_cpi  = cycles / count if count else 0
        use_pct  = count  / total_instr  * 100 if total_instr  else 0
        cyc_pct  = cycles / total_cycles * 100 if total_cycles else 0
        area_pct = AREA_COST[ext] / TOTAL_AREA * 100
        if ext == 'I':      verdict = "mandatory"
        elif use_pct > 2:   verdict = "keep"
        elif use_pct > 0.5: verdict = "evaluate"
        else:               verdict = "exclude"
        print(f"  {ext:<10} {count:>9,} {use_pct:>5.1f}% {cycles:>12,} "
              f"{cyc_pct:>5.1f}% {avg_cpi:>7.3f} {area_pct:>5.1f}%  {verdict}")
    print("  " + "-" * 78)
    avg_cpi_total = total_cycles / total_instr if total_instr else 0
    print(f"  {'TOTAL':<10} {total_instr:>9,} {'100.0%':>6} {total_cycles:>12,} "
          f"{'100.0%':>6} {avg_cpi_total:>7.3f}")


def plot_top_extensions_pie(ext_cycles, predicted_cycles, top_n=4):
    sorted_exts = sorted(ext_cycles.items(), key=lambda x: x[1], reverse=True)[:top_n]
    labels = [ext for ext, _ in sorted_exts]
    cycles = [cyc for _, cyc in sorted_exts]

    fig, ax = plt.subplots()
    wedges, texts, autotexts = ax.pie(
        cycles,
        labels=labels,
        startangle=90,
        autopct=lambda p: f'{p * sum(cycles) / predicted_cycles:.1f}%'
    )
    ax.legend(wedges, labels, title="Extensions", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
    ax.axis('equal')
    ax.set_title(f"Top {top_n} Extensions by Predicted Cycle Count\n(Total: {predicted_cycles:,})")
    plt.tight_layout()
    plt.show()

