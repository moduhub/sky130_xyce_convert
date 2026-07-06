"""
Decompoe a divergencia de Y22 (achado 8 do README) numa medicao
INDEPENDENTE de Cgd/Cds/Cdb via extracao de 3 portas (gate, drain,
source; bulk aterrado, inferido por conservacao de carga/KCL sem
precisar excita-lo) -- ao contrario de so subtrair Cgd do Y22 total
(raciocinio por eliminacao, que nao prova nada sozinho e mistura Cdb
com Cds se source e bulk estiverem no mesmo no, como no teste de
Y-parameters de 2 portas em compare.py).

Ponto de operacao e L/W identicos a compare.py (Vgs=1.2V, Vds=0.9V,
L=160nm, W=1.1um, corner tt), numa unica frequencia (1MHz).

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
FREQ = "1meg"
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

.ac lin 1 {freq} {freq}

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

.ac lin 1 {freq} {freq}

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
    ac_g, ac_d, ac_s = AC[port]
    tb = ngspice_dir / f"tb_{port}.spice"
    tb.write_text(NGSPICE_TB.format(port=port, corner=CORNER, device=DEVICE_LINE,
                                     vgs=VGS_BIAS, vds=VDS_BIAS,
                                     ac_g=ac_g, ac_d=ac_d, ac_s=ac_s, freq=FREQ))
    subprocess.run(["ngspice", "-b", tb.name], cwd=ngspice_dir,
                    capture_output=True, text=True, check=True)
    line = (ngspice_dir / f"out_{port}.csv").read_text().splitlines()[0]
    p = [float(x) for x in line.split()]
    return complex(p[1], p[3]), complex(p[5], p[7]), complex(p[9], p[11])


def run_xyce(xyce_dir, port):
    ac_g, ac_d, ac_s = AC[port]
    tb = xyce_dir / f"tb_{port}.spice"
    tb.write_text(XYCE_TB.format(port=port, corner=CORNER, device=DEVICE_LINE,
                                  vgs=VGS_BIAS, vds=VDS_BIAS,
                                  ac_g=ac_g, ac_d=ac_d, ac_s=ac_s, freq=FREQ))
    subprocess.run(["Xyce", tb.name], cwd=xyce_dir,
                    capture_output=True, text=True, check=True)
    lines = (xyce_dir / f"out_{port}.csv").read_text().splitlines()
    vals = [float(x) for x in lines[1].split(",")]
    # Xyce .PRINT AC sempre antepoe FREQ, mesmo sem pedir -- vals[0] e FREQ.
    return complex(vals[1], vals[2]), complex(vals[3], vals[4]), complex(vals[5], vals[6])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", "/usr/local/share/pdk"))
    parser.add_argument("--pdk", default=os.environ.get("PDK", "sky130A"))
    parser.add_argument("--patches", default=str(REPO_ROOT / "patches/nfet_01v8.yaml"))
    parser.add_argument("--workdir", default="/tmp/validate_nfet_01v8_cdb_3port")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    ngspice_dir = workdir / "ngspice_run"
    xyce_dir = workdir / "xyce_run"
    stage_models(args.pdk_root, args.pdk, ngspice_dir, xyce_dir, Path(args.patches))

    w = 2 * math.pi * 1e6
    for label, ng_dir, runner in [("ngspice", ngspice_dir, run_ngspice), ("Xyce", xyce_dir, run_xyce)]:
        Y = {}
        for port in PORTS:
            ig, id_, is_ = runner(ng_dir, port)
            Y[("g", port)] = ig
            Y[("d", port)] = id_
            Y[("s", port)] = is_

        cgd_gd = -Y[("g", "drain")].imag / w
        cgd_dg = -Y[("d", "gate")].imag / w
        cds = -Y[("d", "source")].imag / w
        cdb = Y[("d", "drain")].imag / w - cgd_gd - cds

        print(f"=== {label} ===")
        print(f"  Cgd (via Ygd, g<-d)  = {cgd_gd:.6e}")
        print(f"  Cgd (via Ydg, d<-g)  = {cgd_dg:.6e}  (nao-reciproco, esperado no BSIM4)")
        print(f"  Cds (via Yds, d<-s)  = {cds:.6e}")
        print(f"  Cdb (via KCL: Ydd/w - Cgd - Cds) = {cdb:.6e}")
        print()


if __name__ == "__main__":
    main()
