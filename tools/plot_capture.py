"""Render the checked capture-demo JSON as a standalone timing diagram.

uv run --with matplotlib --python 3.12 tools/plot_capture.py build/fault-demo.json build/fault-demo.svg
"""
import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render(data, output):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "svg.fonttype": "none"})
    fig, axes = plt.subplots(2, 1, figsize=(10, 4.8), sharex=True)
    fig.set_facecolor("#fcfbf7")
    stop = next(row for row in data if row["faulted"])["events"][2:4]
    limit = max(e["cycle"] for row in data for e in row["events"]) + 30
    for ax, row in zip(axes, data):
        ax.set_facecolor("#fcfbf7")
        color = "#b9472e" if row["faulted"] else "#176e82"
        cycles = [0] + [e["cycle"] for e in row["events"]] + [limit]
        pins = [1] + [e["pins"] for e in row["events"]] + [row["events"][-1]["pins"]]
        for lane, baseline in [(0, 1.4), (4, 0)]:
            levels = [baseline + 0.65 * ((v >> lane) & 1) for v in pins]
            ax.step([t / 10 for t in cycles], levels, where="post", color=color, lw=2)
        ax.axvspan(stop[0]["cycle"] / 10, stop[1]["cycle"] / 10, alpha=0.10, color="#b9472e")
        ax.set_yticks([0.325, 1.725], ["Target response", "UART echo"])
        ax.set_ylim(-0.3, 2.5)
        ax.set_xlim(0, limit / 10)
        ax.spines[["top", "left", "right"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.grid(axis="x", alpha=0.16)
        title = "LOW STOP BIT · 3.2 µs controlled fault" if row["faulted"] else "VALID STOP BIT · normal frame"
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=color)
    axes[-1].set_xlabel("Time from RUN, synchronized capture (µs at 10 MHz)")
    fig.suptitle("One firmware engine. A timed fault. A captured response.", x=0.03,
                 ha="left", fontsize=15, fontweight="bold")
    fig.text(0.03, 0.015, "Digital simulation · UART FF, 32 clocks/bit · modeled target · 100 ns capture resolution", color="#555555", fontsize=9)
    fig.tight_layout(rect=[0, 0.04, 1, 0.94])
    fig.savefig(output, facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    with open(args.input) as source:
        render(json.load(source), args.output)
