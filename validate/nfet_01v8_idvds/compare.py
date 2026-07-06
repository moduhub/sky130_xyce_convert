"""
Compara Id-Vds do sky130_fd_pr__nfet_01v8 entre ngspice (netlist original
do PDK) e Xyce (netlist convertido por converter.cli) para o corner tt.
Gera o PNG usado no README como evidencia de confiabilidade da conversao.

Requer rodar numa maquina com ngspice, Xyce e o PDK sky130 instalados
(PDK_ROOT/PDK exportados) -- ver docker/sky130_xyce_convert no repo
eda-env para o ambiente Docker de referencia usado para gerar os
resultados publicados em validate/results/.

Uso:
    python3 validate/nfet_01v8_idvds/compare.py
    python3 validate/nfet_01v8_idvds/compare.py --pdk-root /usr/local/share/pdk --pdk sky130A
"""
import argparse
import csv
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

import sys  # noqa: E402
sys.path.insert(0, str(REPO_ROOT))

from converter.joiner import join_continuations, split_for_output  # noqa: E402
from converter.patcher import load_patches, apply_patches  # noqa: E402

CORNER = "tt"
L = "160e-9"
W = "1.1e-6"
VGS_VALUES = [0.6, 0.9, 1.2, 1.5, 1.8]

NGSPICE_TB = """nfet_01v8 Id-Vds (Vgs={vgs}) - ngspice
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

XM1 d g 0 0 sky130_fd_pr__nfet_01v8 l={l} w={w}

VDS d 0 dc 0
VGS g 0 dc {vgs}

.dc VDS 0 1.8 0.02

.control
run
wrdata out_{tag}.csv v(d) i(VDS)
.endc
.end
"""

XYCE_TB = """nfet_01v8 Id-Vds (Vgs={vgs}) - Xyce
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

XM1 d g 0 0 sky130_fd_pr__nfet_01v8 l={l} w={w}

VDS d 0 dc 0
VGS g 0 dc {vgs}

.dc VDS 0 1.8 0.02

.PRINT DC FORMAT=csv FILE=out_{tag}.csv V(d) I(VDS)

.end
"""


def stage_models(pdk_root, pdk, ngspice_dir, xyce_dir, patches_path):
    """Copia os arquivos originais para ngspice_dir e escreve a versao
    convertida (mesmo pipeline do `converter.cli convert`) em xyce_dir."""
    spice_dir = Path(pdk_root) / pdk / "libs.ref/sky130_fd_pr/spice"
    names = [
        f"sky130_fd_pr__nfet_01v8__{CORNER}.pm3.spice",
        f"sky130_fd_pr__nfet_01v8__{CORNER}.corner.spice",
        "sky130_fd_pr__nfet_01v8__mismatch.corner.spice",
    ]
    ngspice_dir.mkdir(parents=True, exist_ok=True)
    xyce_dir.mkdir(parents=True, exist_ok=True)

    patches = load_patches(patches_path)
    for name in names:
        src = spice_dir / name
        shutil.copy(src, ngspice_dir / name)

        lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        logical = join_continuations(lines)
        patched, _ = apply_patches(logical, patches, filename=name)
        out_lines = []
        for ll in patched:
            out_lines.extend(split_for_output(ll.text))
        (xyce_dir / name).write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def run_ngspice(ngspice_dir, vgs):
    tag = str(vgs).replace(".", "p")
    tb_path = ngspice_dir / f"tb_{tag}.spice"
    tb_path.write_text(NGSPICE_TB.format(vgs=vgs, l=L, w=W, tag=tag, corner=CORNER))
    subprocess.run(["ngspice", "-b", tb_path.name], cwd=ngspice_dir,
                    capture_output=True, text=True, check=True)
    vds, id_ = [], []
    with open(ngspice_dir / f"out_{tag}.csv") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 4:
                vds.append(float(parts[0]))
                id_.append(-float(parts[3]))
    return vds, id_


def run_xyce(xyce_dir, vgs):
    tag = str(vgs).replace(".", "p")
    tb_path = xyce_dir / f"tb_{tag}.spice"
    tb_path.write_text(XYCE_TB.format(vgs=vgs, l=L, w=W, tag=tag, corner=CORNER))
    subprocess.run(["Xyce", tb_path.name], cwd=xyce_dir,
                    capture_output=True, text=True, check=True)
    vds, id_ = [], []
    with open(xyce_dir / f"out_{tag}.csv") as fh:
        reader = csv.reader(fh)
        next(reader)
        for row in reader:
            vds.append(float(row[0]))
            id_.append(-float(row[1]))
    return vds, id_


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", "/usr/local/share/pdk"))
    parser.add_argument("--pdk", default=os.environ.get("PDK", "sky130A"))
    parser.add_argument("--patches", default=str(REPO_ROOT / "patches/nfet_01v8.yaml"))
    parser.add_argument("--workdir", default="/tmp/validate_nfet_01v8_idvds")
    parser.add_argument("--outdir", default=str(REPO_ROOT / "validate/results"))
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    workdir = Path(args.workdir)
    ngspice_dir = workdir / "ngspice_run"
    xyce_dir = workdir / "xyce_run"
    stage_models(args.pdk_root, args.pdk, ngspice_dir, xyce_dir, Path(args.patches))

    fig, ax = plt.subplots(figsize=(8, 6))
    colors = plt.cm.viridis([i / max(1, len(VGS_VALUES) - 1) for i in range(len(VGS_VALUES))])
    rows = []
    for vgs, color in zip(VGS_VALUES, colors):
        vds_ng, id_ng = run_ngspice(ngspice_dir, vgs)
        vds_xy, id_xy = run_xyce(xyce_dir, vgs)
        ax.plot(vds_ng, [i * 1e3 for i in id_ng], "-", color=color, linewidth=2,
                label=f"ngspice Vgs={vgs}V")
        ax.plot(vds_xy, [i * 1e3 for i in id_xy], "none", color=color, marker="x",
                markevery=8, markersize=7, label=f"Xyce Vgs={vgs}V")
        n = min(len(id_ng), len(id_xy))
        errs = [abs(id_ng[i] - id_xy[i]) / max(abs(id_ng[i]), 1e-15) * 100
                for i in range(n) if vds_ng[i] > 0.05]
        rows.append((vgs, max(errs), sum(errs) / len(errs)))

    ax.set_xlabel("Vds (V)")
    ax.set_ylabel("Id (mA)")
    ax.set_title(f"sky130_fd_pr__nfet_01v8 Id-Vds: ngspice (original) vs Xyce (convertido)\n"
                 f"L={L} W={W}, corner {CORNER}")
    ax.legend(fontsize=8, ncol=2, loc="lower right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"nfet_01v8_idvds_{CORNER}.png"
    fig.savefig(png_path, dpi=150)

    print(f"Plot salvo em {png_path}\n")
    print(f"{'Vgs':>6} {'max_err%':>12} {'mean_err%':>12}")
    for vgs, m, avg in rows:
        print(f"{vgs:>6} {m:>12.2e} {avg:>12.2e}")


if __name__ == "__main__":
    main()
