"""
Compara Y-parameters (Y11/Y12/Y21/Y22) do sky130_fd_pr__nfet_01v8 entre
ngspice (netlist original do PDK) e Xyce (netlist convertido por
converter.cli) via .AC, no ponto de polarizacao Vgs/Vds fixo. Gera o PNG
usado no README.

Metodo: duas excitacoes .AC separadas (2-porta, porta 1 = gate, porta 2
= drain, fonte/bulk aterrados):
  - excita porta 1 (VGS ac=1, VDS ac=0): Y11 = I(VGS)/1, Y21 = I(VDS)/1
  - excita porta 2 (VDS ac=1, VGS ac=0): Y12 = I(VGS)/1, Y22 = I(VDS)/1
(a fonte de tensao ideal na porta nao excitada funciona como curto AC,
condicao padrao para extracao de Y-parameters).

Requer rodar numa maquina com ngspice, Xyce e o PDK sky130 instalados
(PDK_ROOT/PDK exportados) -- ver docker/sky130_xyce_convert no repo
eda-env para o ambiente Docker de referencia.

Uso:
    python3 validate/nfet_01v8_yparams/compare.py
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
# AD/AS/PD/PS explicitos (diffusion de um finger, aproximado) -- com
# ad=as=pd=ps=0 (default do subckt) o gap Y22 imaginario e maior ainda
# (ver README, achado sobre GEOMOD/capacitancia de juncao).
AD_AS = "3.19e-13"
PD_PS = "2.9e-6"
VGS_BIAS = 1.2
VDS_BIAS = 0.9
FSTART = "1meg"
FSTOP = "10g"
PTS_PER_DEC = 10

DEVICE_LINE = (
    f"XM1 d g 0 0 sky130_fd_pr__nfet_01v8 l={L} w={W} "
    f"ad={AD_AS} as={AD_AS} pd={PD_PS} ps={PD_PS}"
)

NGSPICE_TB = """nfet_01v8 Y-params (porta={port}) - ngspice
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{device}

VDS d 0 dc {vds} ac {vds_ac}
VGS g 0 dc {vgs} ac {vgs_ac}

.ac dec {ppd} {fstart} {fstop}

.control
run
wrdata out_{tag}.csv real(i(VGS)) imag(i(VGS)) real(i(VDS)) imag(i(VDS))
.endc
.end
"""

XYCE_TB = """nfet_01v8 Y-params (porta={port}) - Xyce
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{device}

VDS d 0 dc {vds} ac {vds_ac}
VGS g 0 dc {vgs} ac {vgs_ac}

.ac dec {ppd} {fstart} {fstop}

.PRINT AC FORMAT=csv FILE=out_{tag}.csv FREQ IR(VGS) II(VGS) IR(VDS) II(VDS)

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


def run_ngspice_port(ngspice_dir, port):
    vgs_ac, vds_ac = (1, 0) if port == "gate" else (0, 1)
    tb_path = ngspice_dir / f"tb_{port}.spice"
    tb_path.write_text(NGSPICE_TB.format(
        port=port, corner=CORNER, device=DEVICE_LINE,
        vgs=VGS_BIAS, vds=VDS_BIAS, vgs_ac=vgs_ac, vds_ac=vds_ac,
        ppd=PTS_PER_DEC, fstart=FSTART, fstop=FSTOP, tag=port,
    ))
    subprocess.run(["ngspice", "-b", tb_path.name], cwd=ngspice_dir,
                    capture_output=True, text=True, check=True)
    freqs, i_gate, i_drain = [], [], []
    with open(ngspice_dir / f"out_{port}.csv") as fh:
        for line in fh:
            p = line.split()
            if len(p) >= 8:
                freqs.append(float(p[0]))
                i_gate.append(complex(float(p[1]), float(p[3])))
                i_drain.append(complex(float(p[5]), float(p[7])))
    return freqs, i_gate, i_drain


def run_xyce_port(xyce_dir, port):
    vgs_ac, vds_ac = (1, 0) if port == "gate" else (0, 1)
    tb_path = xyce_dir / f"tb_{port}.spice"
    tb_path.write_text(XYCE_TB.format(
        port=port, corner=CORNER, device=DEVICE_LINE,
        vgs=VGS_BIAS, vds=VDS_BIAS, vgs_ac=vgs_ac, vds_ac=vds_ac,
        ppd=PTS_PER_DEC, fstart=FSTART, fstop=FSTOP, tag=port,
    ))
    subprocess.run(["Xyce", tb_path.name], cwd=xyce_dir,
                    capture_output=True, text=True, check=True)
    freqs, i_gate, i_drain = [], [], []
    with open(xyce_dir / f"out_{port}.csv") as fh:
        reader = csv.reader(fh)
        next(reader)
        for row in reader:
            freqs.append(float(row[0]))
            i_gate.append(complex(float(row[2]), float(row[3])))
            i_drain.append(complex(float(row[4]), float(row[5])))
    return freqs, i_gate, i_drain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", "/usr/local/share/pdk"))
    parser.add_argument("--pdk", default=os.environ.get("PDK", "sky130A"))
    parser.add_argument("--patches", default=str(REPO_ROOT / "patches/nfet_01v8.yaml"))
    parser.add_argument("--workdir", default="/tmp/validate_nfet_01v8_yparams")
    parser.add_argument("--outdir", default=str(REPO_ROOT / "validate/results"))
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    workdir = Path(args.workdir)
    ngspice_dir = workdir / "ngspice_run"
    xyce_dir = workdir / "xyce_run"
    stage_models(args.pdk_root, args.pdk, ngspice_dir, xyce_dir, Path(args.patches))

    freq_g, ng_ig_g, ng_id_g = run_ngspice_port(ngspice_dir, "gate")
    _, xy_ig_g, xy_id_g = run_xyce_port(xyce_dir, "gate")
    freq_d, ng_ig_d, ng_id_d = run_ngspice_port(ngspice_dir, "drain")
    _, xy_ig_d, xy_id_d = run_xyce_port(xyce_dir, "drain")

    # Y11=Iin(gate exc)/1  Y21=Iout(gate exc)/1  Y12=Iin(drain exc)/1  Y22=Iout(drain exc)/1
    params = {
        "Y11": (freq_g, ng_ig_g, xy_ig_g),
        "Y21": (freq_g, ng_id_g, xy_id_g),
        "Y12": (freq_d, ng_ig_d, xy_ig_d),
        "Y22": (freq_d, ng_id_d, xy_id_d),
    }

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    max_err_by_param = {}
    for ax, (name, (freqs, ng, xy)) in zip(axes.flat, params.items()):
        ng_mag = [abs(v) for v in ng]
        xy_mag = [abs(v) for v in xy]
        ax.loglog(freqs, ng_mag, "-", color="tab:blue", linewidth=2, label="ngspice")
        ax.loglog(freqs, xy_mag, "none", marker="x", color="tab:orange",
                  markevery=3, markersize=7, label="Xyce")
        ax.set_title(f"|{name}|")
        ax.set_xlabel("freq (Hz)")
        ax.set_ylabel("S (siemens)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)

        errs = [abs(abs(n) - abs(x)) / max(abs(n), 1e-18) * 100 for n, x in zip(ng, xy)]
        max_err_by_param[name] = max(errs)

    fig.suptitle(f"sky130_fd_pr__nfet_01v8 Y-parameters: ngspice vs Xyce\n"
                 f"L={L} W={W}, Vgs={VGS_BIAS}V Vds={VDS_BIAS}V, corner {CORNER}")
    fig.tight_layout()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"nfet_01v8_yparams_{CORNER}.png"
    fig.savefig(png_path, dpi=150)

    print(f"Plot salvo em {png_path}\n")
    print(f"{'param':>6} {'max_err%':>12}")
    for name, err in max_err_by_param.items():
        print(f"{name:>6} {err:>12.2e}")


if __name__ == "__main__":
    main()
