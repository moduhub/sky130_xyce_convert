"""
Decompoe a divergencia de Y22 (achado 8 do README) numa medicao
INDEPENDENTE de Cgd/Cds/Cdb via extracao de 3 portas (gate, drain,
source; bulk aterrado, inferido por conservacao de carga/KCL sem
precisar excita-lo) -- ao contrario de so subtrair Cgd do Y22 total
(raciocinio por eliminacao, que nao prova nada sozinho e mistura Cdb
com Cds se source e bulk estiverem no mesmo no, como no teste de
Y-parameters de 2 portas em compare.py).

Varre a mesma faixa de frequencia de compare.py (1MHz-10GHz) no mesmo
ponto de operacao/L/W (Vgs=1.2V, Vds=0.9V, L=160nm, W=1.1um, corner tt)
para mostrar que a razao ngspice/Xyce de Cdb e constante com a
frequencia (capacitancia pura, nao artefato de ruido) -- gera o PNG
usado no README.

Uso:
    python3 validate/nfet_01v8_yparams/cdb_3port_check.py
"""
import argparse
import math
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
FSTART = "1meg"
FSTOP = "10g"
PTS_PER_DEC = 5
PORTS = ["gate", "drain", "source"]
AC = {"gate": (1, 0, 0), "drain": (0, 1, 0), "source": (0, 0, 1)}

DEVICE_LINE = f"XM1 d g s 0 sky130_fd_pr__nfet_01v8 l={L} w={W}"

NGSPICE_TB = """3port {port} - ngspice
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{device}

VDS d 0 dc {vds} ac {ac_d}
VGS g 0 dc {vgs} ac {ac_g}
VS s 0 dc 0 ac {ac_s}

.ac dec {ppd} {fstart} {fstop}

.control
run
wrdata out_{port}.csv real(i(VGS)) imag(i(VGS)) real(i(VDS)) imag(i(VDS)) real(i(VS)) imag(i(VS))
.endc
.end
"""

XYCE_TB = """3port {port} - Xyce
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{device}

VDS d 0 dc {vds} ac {ac_d}
VGS g 0 dc {vgs} ac {ac_g}
VS s 0 dc 0 ac {ac_s}

.ac dec {ppd} {fstart} {fstop}

.PRINT AC FORMAT=csv FILE=out_{port}.csv IR(VGS) II(VGS) IR(VDS) II(VDS) IR(VS) II(VS)

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


def run_ngspice(ngspice_dir, port):
    """Retorna (freqs, i_gate, i_drain, i_source) -- listas paralelas."""
    ac_g, ac_d, ac_s = AC[port]
    tb = ngspice_dir / f"tb_{port}.spice"
    tb.write_text(NGSPICE_TB.format(port=port, corner=CORNER, device=DEVICE_LINE,
                                     vgs=VGS_BIAS, vds=VDS_BIAS,
                                     ac_g=ac_g, ac_d=ac_d, ac_s=ac_s,
                                     ppd=PTS_PER_DEC, fstart=FSTART, fstop=FSTOP))
    subprocess.run(["ngspice", "-b", tb.name], cwd=ngspice_dir,
                    capture_output=True, text=True, check=True)
    freqs, ig, id_, is_ = [], [], [], []
    with open(ngspice_dir / f"out_{port}.csv") as fh:
        for line in fh:
            p = [float(x) for x in line.split()]
            if len(p) >= 12:
                freqs.append(p[0])
                ig.append(complex(p[1], p[3]))
                id_.append(complex(p[5], p[7]))
                is_.append(complex(p[9], p[11]))
    return freqs, ig, id_, is_


def run_xyce(xyce_dir, port):
    ac_g, ac_d, ac_s = AC[port]
    tb = xyce_dir / f"tb_{port}.spice"
    tb.write_text(XYCE_TB.format(port=port, corner=CORNER, device=DEVICE_LINE,
                                  vgs=VGS_BIAS, vds=VDS_BIAS,
                                  ac_g=ac_g, ac_d=ac_d, ac_s=ac_s,
                                  ppd=PTS_PER_DEC, fstart=FSTART, fstop=FSTOP))
    subprocess.run(["Xyce", tb.name], cwd=xyce_dir,
                    capture_output=True, text=True, check=True)
    freqs, ig, id_, is_ = [], [], [], []
    with open(xyce_dir / f"out_{port}.csv") as fh:
        lines = fh.read().splitlines()
        for line in lines[1:]:
            v = [float(x) for x in line.split(",")]
            freqs.append(v[0])
            ig.append(complex(v[1], v[2]))
            id_.append(complex(v[3], v[4]))
            is_.append(complex(v[5], v[6]))
    return freqs, ig, id_, is_


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", "/usr/local/share/pdk"))
    parser.add_argument("--pdk", default=os.environ.get("PDK", "sky130A"))
    parser.add_argument("--patches", default=str(REPO_ROOT / "patches/nfet_01v8.yaml"))
    parser.add_argument("--workdir", default="/tmp/validate_nfet_01v8_cdb_3port")
    parser.add_argument("--outdir", default=str(REPO_ROOT / "validate/results"))
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    workdir = Path(args.workdir)
    ngspice_dir = workdir / "ngspice_run"
    xyce_dir = workdir / "xyce_run"
    stage_models(args.pdk_root, args.pdk, ngspice_dir, xyce_dir, Path(args.patches))

    results = {}
    for label, ng_dir, runner in [("ngspice", ngspice_dir, run_ngspice), ("Xyce", xyce_dir, run_xyce)]:
        by_port = {port: runner(ng_dir, port) for port in PORTS}
        freqs = by_port["gate"][0]

        cgd, cds, cdb = [], [], []
        for i, f in enumerate(freqs):
            w = 2 * math.pi * f
            id_drain = by_port["drain"][2][i]  # excita drain, le corrente no drain (Ydd)
            ig_drain = by_port["drain"][1][i]  # excita drain, le corrente no gate (Ygd)
            id_source = by_port["source"][2][i]  # excita source, le corrente no drain (Yds)

            cgd_i = -ig_drain.imag / w  # Ygd: excita drain, le gate
            cds_i = -id_source.imag / w  # Yds: excita source, le drain
            cdb_i = id_drain.imag / w - cgd_i - cds_i  # KCL: Ydd = Cgd+Cds+Cdb

            cgd.append(cgd_i)
            cds.append(cds_i)
            cdb.append(cdb_i)

        results[label] = (freqs, cgd, cds, cdb)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    labels_caps = ["Cgd (via Ygd)", "Cds (via Yds)", "Cdb (via KCL)"]
    max_err = {}
    for col, cap_name in enumerate(labels_caps):
        ax = axes[col]
        _, *caps_ng = results["ngspice"]
        _, *caps_xy = results["Xyce"]
        freqs_ng = results["ngspice"][0]
        freqs_xy = results["Xyce"][0]
        ng_vals = caps_ng[col]
        xy_vals = caps_xy[col]

        ax.semilogx(freqs_ng, [abs(v) * 1e15 for v in ng_vals], "-", color="tab:blue",
                    linewidth=2, label="ngspice")
        ax.semilogx(freqs_xy, [abs(v) * 1e15 for v in xy_vals], "none", marker="x",
                    color="tab:orange", markersize=7, label="Xyce")
        ax.set_xlabel("freq (Hz)")
        ax.set_ylabel("|C| (fF)")
        ax.set_title(cap_name)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)

        errs = [abs(abs(n) - abs(x)) / max(abs(n), 1e-21) * 100 for n, x in zip(ng_vals, xy_vals)]
        max_err[cap_name] = max(errs)

    fig.suptitle(f"sky130_fd_pr__nfet_01v8: Cgd/Cds/Cdb via extracao de 3 portas\n"
                 f"L={L} W={W}, Vgs={VGS_BIAS}V Vds={VDS_BIAS}V, corner {CORNER}")
    fig.tight_layout()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"nfet_01v8_cdb_3port_{CORNER}.png"
    fig.savefig(png_path, dpi=150)

    print(f"Plot salvo em {png_path}\n")
    print(f"{'capacitancia':>16} {'max_err%':>12}")
    for name, err in max_err.items():
        print(f"{name:>16} {err:>12.2e}")


if __name__ == "__main__":
    main()
