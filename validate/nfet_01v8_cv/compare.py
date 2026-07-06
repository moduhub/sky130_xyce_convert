"""
Compara C-V (Cgs, Cgd) do sky130_fd_pr__nfet_01v8 entre ngspice (netlist
original do PDK) e Xyce (netlist convertido por converter.cli), lendo os
parametros internos do BSIM4 (cgs/cgd) diretamente via .DC + query de
variavel interna do dispositivo -- sem precisar de .AC.

Cobertura parcial de propósito: Xyce nao expõe cgb/cbd/cbs (nem id) via
essa mesma query de variavel interna (`N(XM1:MSKY130_FD_PR__NFET_01V8:*)`)
-- so cgs/cgd/gm/gds/vth responderam nos testes manuais. Cgg/Cdb/Csb
ficam de fora ate acharmos outro caminho (ex.: extrair via .AC 3-porta
com fonte no source, como o resto do Y-parameter). Ver README.

Gotcha de metodologia (nao e diferenca de simulador): no ngspice, ler um
parametro interno de dispositivo (`@m.xm1...[cgs]`) dentro de um `.dc`
sem um `.save` explicito anterior retorna o MESMO valor (do ultimo ponto
do sweep) em todas as linhas -- silenciosamente errado. Precisa de
`.save @m.xm1...[cgs] @m.xm1...[cgd] ...` antes do `.dc` para o ngspice
de fato amostrar por ponto.

Requer rodar numa maquina com ngspice, Xyce e o PDK sky130 instalados
(PDK_ROOT/PDK exportados).

Uso:
    python3 validate/nfet_01v8_cv/compare.py
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from converter.joiner import join_continuations, split_for_output  # noqa: E402
from converter.patcher import load_patches, apply_patches  # noqa: E402

CORNER = "tt"
L = "160e-9"
W = "1.1e-6"
VGS_BIAS = 1.2
VDS_BIAS = 0.9
SUBCKT_NAME = "MSKY130_FD_PR__NFET_01V8"
NGSPICE_DEVPATH = "xm1.msky130_fd_pr__nfet_01v8"

DEVICE_LINE = f"XM1 d g 0 0 sky130_fd_pr__nfet_01v8 l={L} w={W}"

# sweep: nome, fonte varrida, fonte fixa, valor fixo
SWEEPS = [
    ("vgs", "VGS", "VDS", VDS_BIAS),
    ("vds", "VDS", "VGS", VGS_BIAS),
]

NGSPICE_TB = """nfet_01v8 C-V vs {sweep_name} - ngspice
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{device}

VDS d 0 dc {vds_dc}
VGS g 0 dc {vgs_dc}

.save v(g) v(d) @m.{devpath}[cgs] @m.{devpath}[cgd]

.dc {swept} 0 1.8 0.02

.control
run
wrdata out_{sweep_name}.csv v(g) v(d) @m.{devpath}[cgs] @m.{devpath}[cgd]
.endc
.end
"""

XYCE_TB = """nfet_01v8 C-V vs {sweep_name} - Xyce
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{device}

VDS d 0 dc {vds_dc}
VGS g 0 dc {vgs_dc}

.dc {swept} 0 1.8 0.02

.PRINT DC FORMAT=csv FILE=out_{sweep_name}.csv V(g) V(d) N(XM1:{subckt}:CGS) N(XM1:{subckt}:CGD)

.end
"""


def stage_models(pdk_root, pdk, ngspice_dir, xyce_dir, patches_path):
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


def run_ngspice_sweep(ngspice_dir, sweep_name, swept, vgs_dc, vds_dc):
    tb_path = ngspice_dir / f"tb_{sweep_name}.spice"
    tb_path.write_text(NGSPICE_TB.format(
        sweep_name=sweep_name, corner=CORNER, device=DEVICE_LINE,
        vgs_dc=vgs_dc, vds_dc=vds_dc, swept=swept, devpath=NGSPICE_DEVPATH,
    ))
    subprocess.run(["ngspice", "-b", tb_path.name], cwd=ngspice_dir,
                    capture_output=True, text=True, check=True)
    # wrdata: (x,y) pair per requested vector, sem coluna lider extra.
    # Pedimos v(g) v(d) cgs cgd => 4 pares = 8 colunas; col[0] e o valor
    # varrido (x de qualquer par serve, todos identicos).
    x, cgs, cgd = [], [], []
    with open(ngspice_dir / f"out_{sweep_name}.csv") as fh:
        for line in fh:
            p = line.split()
            if len(p) >= 8:
                x.append(float(p[0]))
                cgs.append(float(p[5]))
                cgd.append(float(p[7]))
    return x, cgs, cgd


def run_xyce_sweep(xyce_dir, sweep_name, swept, vgs_dc, vds_dc):
    tb_path = xyce_dir / f"tb_{sweep_name}.spice"
    tb_path.write_text(XYCE_TB.format(
        sweep_name=sweep_name, corner=CORNER, device=DEVICE_LINE,
        vgs_dc=vgs_dc, vds_dc=vds_dc, swept=swept, subckt=SUBCKT_NAME,
    ))
    subprocess.run(["Xyce", tb_path.name], cwd=xyce_dir,
                    capture_output=True, text=True, check=True)
    # colunas: V(g), V(d), CGS, CGD
    x_col = 0 if swept == "VGS" else 1
    x, cgs, cgd = [], [], []
    with open(xyce_dir / f"out_{sweep_name}.csv") as fh:
        reader = csv.reader(fh)
        next(reader)
        for row in reader:
            x.append(float(row[x_col]))
            cgs.append(float(row[2]))
            cgd.append(float(row[3]))
    return x, cgs, cgd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", "/usr/local/share/pdk"))
    parser.add_argument("--pdk", default=os.environ.get("PDK", "sky130A"))
    parser.add_argument("--patches", default=str(REPO_ROOT / "patches/nfet_01v8.yaml"))
    parser.add_argument("--workdir", default="/tmp/validate_nfet_01v8_cv")
    parser.add_argument("--outdir", default=str(REPO_ROOT / "validate/results"))
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    workdir = Path(args.workdir)
    ngspice_dir = workdir / "ngspice_run"
    xyce_dir = workdir / "xyce_run"
    stage_models(args.pdk_root, args.pdk, ngspice_dir, xyce_dir, Path(args.patches))

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    max_err = {}
    for col, (sweep_name, swept, fixed, fixed_val) in enumerate(SWEEPS):
        vgs_dc = 0 if swept == "VGS" else fixed_val
        vds_dc = 0 if swept == "VDS" else fixed_val

        x_ng, cgs_ng, cgd_ng = run_ngspice_sweep(ngspice_dir, sweep_name, swept, vgs_dc, vds_dc)
        x_xy, cgs_xy, cgd_xy = run_xyce_sweep(xyce_dir, sweep_name, swept, vgs_dc, vds_dc)

        for row, (label, ng, xy) in enumerate([("Cgs", cgs_ng, cgs_xy), ("Cgd", cgd_ng, cgd_xy)]):
            ax = axes[row][col]
            ax.plot(x_ng, [abs(v) * 1e15 for v in ng], "-", color="tab:blue", linewidth=2, label="ngspice")
            ax.plot(x_xy, [abs(v) * 1e15 for v in xy], "none", marker="x", color="tab:orange",
                    markevery=6, markersize=6, label="Xyce")
            ax.set_xlabel(f"{swept} (V), {fixed}={fixed_val}V fixo")
            ax.set_ylabel(f"|{label}| (fF)")
            ax.set_title(f"{label} vs {swept}")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)

            n = min(len(ng), len(xy))
            errs = [abs(ng[i] - xy[i]) / max(abs(ng[i]), 1e-21) * 100 for i in range(n)]
            max_err[f"{label}_vs_{swept}"] = max(errs)

    fig.suptitle(f"sky130_fd_pr__nfet_01v8 C-V: ngspice vs Xyce\nL={L} W={W}, corner {CORNER}")
    fig.tight_layout()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"nfet_01v8_cv_{CORNER}.png"
    fig.savefig(png_path, dpi=150)

    print(f"Plot salvo em {png_path}\n")
    print(f"{'curva':>14} {'max_err%':>12}")
    for name, err in max_err.items():
        print(f"{name:>14} {err:>12.2e}")


if __name__ == "__main__":
    main()
