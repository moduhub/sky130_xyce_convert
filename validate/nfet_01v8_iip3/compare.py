"""
Compara IIP3 (two-tone, terceira ordem) do sky130_fd_pr__nfet_01v8 entre
ngspice (transiente + FFT) e Xyce (.HB nativo) -- os dois metodos que
`validate.py` ja previa (".HB (Xyce) vs transiente+FFT (ngspice)").

Tons de teste: f1=100MHz, f2=101MHz, amplitude 5mV cada, no mesmo
ponto de polarizacao dos outros testes (Vgs=1.2V, Vds=0.9V, L=160nm,
W=1.1um, corner tt). Le a corrente de dreno (I(VDS)) nas 4 frequencias
relevantes: fundamentais (f1, f2) e produtos de intermodulacao de
terceira ordem (2f1-f2, 2f2-f1).

Notas de metodologia (ver README para o achado completo):
  - ngspice: usa `linearize` antes de gravar (senao o `.tran` grava os
    passos adaptativos internos, nao uniformes -- quebra a FFT). Usa
    numero PAR de amostras casando exatamente com multiplos de 1MHz
    (senao nenhuma das 4 frequencias cai exatamente num bin da FFT e
    ha vazamento espectral mesmo sem janela). Roda sem janela (retangular)
    porque as 4 frequencias caem exatamente em bins inteiros por
    construcao. Precisa de `.options reltol=1e-10` (bem mais apertado
    que o default) para o IM3 (~100dB abaixo da fundamental) nao ficar
    dominado por ruido numerico do solver -- reltol mais apertado ainda
    (1e-11, 1e-12) quebra a simulacao em vez de convergir mais.
  - Xyce: `.HB <f1> <f2>` (frequencias POSICIONAIS separadas por espaco,
    sem "TONES=" ou "FREQ=" -- essas dao erro de parser). NUMFREQ e
    opcional (usa default se omitido). `.PRINT HB_FD` da diretamente
    Re/Im por frequencia, sem precisar de FFT.

Uso:
    python3 validate/nfet_01v8_iip3/compare.py
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from converter.joiner import join_continuations, split_for_output  # noqa: E402
from converter.patcher import load_patches, apply_patches  # noqa: E402

CORNER = "tt"
L = "160e-9"
W = "1.1e-6"
VGS_BIAS = 1.2
VDS_BIAS = 0.9
F1 = 100e6
F2 = 101e6
VIN = 5e-3
TSTEP = 0.5e-9
TSTOP = 20e-6

DEVICE_LINE = f"XM1 d g 0 0 sky130_fd_pr__nfet_01v8 l={L} w={W}"

NGSPICE_TB = f"""nfet_01v8 IIP3 two-tone - ngspice
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{{corner}}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{{device}}

VDS d 0 dc {{vds}}
VDC gx 0 dc {{vgs}}
VT1 gx x SIN(0 {{vin}} {F1:g})
VT2 x g SIN(0 {{vin}} {F2:g})

.options reltol=1e-10 vntol=1e-18 abstol=1e-21
.tran {TSTEP:g} {TSTOP:g}

.control
run
linearize i(VDS)
wrdata out_tran.csv i(VDS)
.endc
.end
"""

XYCE_TB = f"""nfet_01v8 IIP3 two-tone - Xyce
.param mc_mm_switch=0
.param mc_pr_switch=0
.include "sky130_fd_pr__nfet_01v8__{{corner}}.corner.spice"
.include "sky130_fd_pr__nfet_01v8__mismatch.corner.spice"

{{device}}

VDS d 0 dc {{vds}}
VDC gx 0 dc {{vgs}}
VT1 gx x SIN(0 {{vin}} {F1:g})
VT2 x g SIN(0 {{vin}} {F2:g})

.HB {F1:g} {F2:g}

.PRINT HB_FD FORMAT=csv FILE=out_hb_fd.csv I(VDS)

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


def run_ngspice(ngspice_dir):
    tb = ngspice_dir / "tb.spice"
    tb.write_text(NGSPICE_TB.format(corner=CORNER, device=DEVICE_LINE,
                                     vgs=VGS_BIAS, vds=VDS_BIAS, vin=VIN))
    subprocess.run(["ngspice", "-b", tb.name], cwd=ngspice_dir,
                    capture_output=True, text=True, check=True)

    data = np.loadtxt(ngspice_dir / "out_tran.csv")
    t, i_vds = data[:, 0], data[:, 1]
    # numero par de amostras: garante que f1/f2 (multiplos de 1MHz) caiam
    # exatamente em bins da FFT -- ver docstring do modulo.
    if len(t) % 2 == 1:
        t, i_vds = t[:-1], i_vds[:-1]
    n = len(t)
    dt = t[1] - t[0]

    spectrum = np.fft.rfft(i_vds)  # sem janela: alvo cai exato no bin
    freqs = np.fft.rfftfreq(n, dt)
    amp = np.abs(spectrum) / n

    def at(f_target):
        idx = np.argmin(np.abs(freqs - f_target))
        return amp[idx]

    points = {
        "f1": at(F1), "f2": at(F2),
        "im3_lo": at(2 * F1 - F2), "im3_hi": at(2 * F2 - F1),
    }
    return points, freqs, amp


def run_xyce(xyce_dir):
    tb = xyce_dir / "tb.spice"
    tb.write_text(XYCE_TB.format(corner=CORNER, device=DEVICE_LINE,
                                  vgs=VGS_BIAS, vds=VDS_BIAS, vin=VIN))
    subprocess.run(["Xyce", tb.name], cwd=xyce_dir,
                    capture_output=True, text=True, check=True)

    rows = {}
    with open(xyce_dir / "out_hb_fd.csv") as fh:
        lines = fh.read().splitlines()
        for line in lines[1:]:
            f, re, im = (float(x) for x in line.split(","))
            rows[round(f)] = (re ** 2 + im ** 2) ** 0.5

    def at(f_target):
        return rows[round(f_target)]

    points = {
        "f1": at(F1), "f2": at(F2),
        "im3_lo": at(2 * F1 - F2), "im3_hi": at(2 * F2 - F1),
    }
    return points, rows


def iip3_from_amplitudes(a_fund, a_im3, vin):
    return vin * (a_fund / a_im3) ** 0.5


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", "/usr/local/share/pdk"))
    parser.add_argument("--pdk", default=os.environ.get("PDK", "sky130A"))
    parser.add_argument("--patches", default=str(REPO_ROOT / "patches/nfet_01v8.yaml"))
    parser.add_argument("--workdir", default="/tmp/validate_nfet_01v8_iip3")
    parser.add_argument("--outdir", default=str(REPO_ROOT / "validate/results"))
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    workdir = Path(args.workdir)
    ngspice_dir = workdir / "ngspice_run"
    xyce_dir = workdir / "xyce_run"
    stage_models(args.pdk_root, args.pdk, ngspice_dir, xyce_dir, Path(args.patches))

    ng, ng_freqs, ng_amp = run_ngspice(ngspice_dir)
    xy, xy_rows = run_xyce(xyce_dir)

    labels = ["f1 (100MHz)", "f2 (101MHz)", "IM3 lo (99MHz)", "IM3 hi (102MHz)"]
    keys = ["f1", "f2", "im3_lo", "im3_hi"]
    ng_vals = [ng[k] for k in keys]
    xy_vals = [xy[k] for k in keys]

    fig, ax = plt.subplots(figsize=(8, 6))
    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width / 2, ng_vals, width, label="ngspice (transiente+FFT)", color="tab:blue")
    ax.bar(x + width / 2, xy_vals, width, label="Xyce (.HB)", color="tab:orange")
    ax.set_yscale("log")
    ax.set_ylabel("|I(VDS)| (A)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title(f"sky130_fd_pr__nfet_01v8 two-tone (IIP3): ngspice vs Xyce\n"
                 f"L={L} W={W}, Vgs={VGS_BIAS}V Vds={VDS_BIAS}V, Vin={VIN*1e3:.0f}mV/tom, corner {CORNER}")
    ax.legend()
    ax.grid(True, which="both", axis="y", alpha=0.3)
    fig.tight_layout()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"nfet_01v8_iip3_{CORNER}.png"
    fig.savefig(png_path, dpi=150)

    # --- Espectro em torno dos tons: FFT do ngspice (linha continua) vs
    # pontos discretos do .HB do Xyce (grade de intermodulacao, nao um
    # espectro denso -- HB so resolve exatamente as frequencias de
    # mistura que ele mesmo calcula). ---
    # Piso baixo o bastante para nao mascarar produtos de intermodulacao
    # de ordem mais alta genuinamente pequenos (ex.: 5a ordem em 98/103MHz
    # fica ~3e-16 no Xyce -- um piso de 1e-15 os "achataria" a zero).
    floor = 1e-22
    fmin, fmax = 95e6, 106e6
    mask = (ng_freqs >= fmin) & (ng_freqs <= fmax)
    ng_freqs_win = ng_freqs[mask]
    ng_db_win = 20 * np.log10(np.maximum(ng_amp[mask], floor))

    xy_freqs_win = sorted(f for f in xy_rows if fmin <= f <= fmax)
    xy_db_win = [20 * np.log10(max(xy_rows[f], floor)) for f in xy_freqs_win]

    fig2, ax2 = plt.subplots(figsize=(10, 6))
    ax2.plot(ng_freqs_win / 1e6, ng_db_win, "-", color="tab:blue", linewidth=1,
             label="ngspice (FFT do transiente)")
    ax2.plot(np.array(xy_freqs_win) / 1e6, xy_db_win, "o", color="tab:orange",
              markersize=7, label="Xyce (.HB, grade discreta)")
    for f_target, tag in [(F1, "f1"), (F2, "f2"),
                          (2 * F1 - F2, "IM3"), (2 * F2 - F1, "IM3")]:
        ax2.axvline(f_target / 1e6, color="gray", linewidth=0.5, linestyle=":")
    ax2.set_xlabel("freq (MHz)")
    ax2.set_ylabel("|I(VDS)| (dBA)")
    ax2.set_title(f"Espectro two-tone usado na extracao do IIP3 (zoom {fmin/1e6:.0f}-{fmax/1e6:.0f}MHz)\n"
                  f"f1/f2 (fundamentais), IM3 3a ordem (99/102MHz); pontos Xyce em 98/103MHz (5a ordem) e\n"
                  f"96/97/104/105MHz (7a ordem) sao reais mas abaixo do chao de ruido do ngspice")
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    fig2.tight_layout()

    spectrum_png_path = outdir / f"nfet_01v8_iip3_spectrum_{CORNER}.png"
    fig2.savefig(spectrum_png_path, dpi=150)

    a_fund_ng = (ng["f1"] + ng["f2"]) / 2
    a_im3_ng = (ng["im3_lo"] + ng["im3_hi"]) / 2
    a_fund_xy = (xy["f1"] + xy["f2"]) / 2
    a_im3_xy = (xy["im3_lo"] + xy["im3_hi"]) / 2

    iip3_ng = iip3_from_amplitudes(a_fund_ng, a_im3_ng, VIN)
    iip3_xy = iip3_from_amplitudes(a_fund_xy, a_im3_xy, VIN)

    print(f"Plots salvos em {png_path} e {spectrum_png_path}\n")
    print(f"{'':>12} {'ngspice':>14} {'Xyce':>14}")
    for label, k in zip(labels, keys):
        print(f"{k:>12} {ng[k]:>14.4e} {xy[k]:>14.4e}")
    print()
    print(f"Vin_IIP3 ngspice = {iip3_ng*1e3:.2f} mV ({20*np.log10(iip3_ng):.2f} dBV)")
    print(f"Vin_IIP3 Xyce    = {iip3_xy*1e3:.2f} mV ({20*np.log10(iip3_xy):.2f} dBV)")
    print(f"Razao IIP3 (ngspice/Xyce) = {iip3_ng/iip3_xy:.3f}")


if __name__ == "__main__":
    main()
