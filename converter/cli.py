"""
CLI de conversao sky130 (ngspice/hspice-flavor) -> Xyce.

Uso:
    python -m converter.cli convert \
        --input cells/nfet_01v8/sky130_fd_pr__nfet_01v8__tt.pm3.spice \
                cells/nfet_01v8/sky130_fd_pr__nfet_01v8__tt.corner.spice \
        --patches patches/nfet_01v8.yaml \
        --outdir build/xyce/nfet_01v8

    python -m converter.cli scan \
        --input cells/nfet_01v8/*.spice \
        --patches patches/nfet_01v8.yaml

O comando "scan" roda so os checks estruturais (sem escrever nada) --
util como primeiro passo antes de decidir os patches, ou como gate
isolado no CI/Dockerfile.
"""
import argparse
import glob
import sys
from pathlib import Path

from .joiner import join_continuations, split_for_output
from .patcher import load_patches, load_external_deps, apply_patches
from .scanner import scan_files


def _expand_inputs(patterns: list[str]) -> list[Path]:
    paths = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches:
            # pode ser um caminho literal que nao e glob
            if Path(pattern).exists():
                matches = [pattern]
        paths.extend(Path(m) for m in matches)
    return paths


def cmd_scan(args):
    filepaths = _expand_inputs(args.input)
    if not filepaths:
        print(f"Nenhum arquivo encontrado para: {args.input}", file=sys.stderr)
        return 1

    report = scan_files(filepaths)
    print(report.summary())

    external_deps = set()
    if args.patches:
        external_deps = set(load_external_deps(Path(args.patches)))

    already_known = report.undefined_params & {d.split("__")[-1] if "__" in d else d
                                                for d in external_deps}
    truly_new = report.undefined_params - {
        d.lower() for d in external_deps
    } - {d.split("__")[-1].lower() for d in external_deps}

    if truly_new:
        print(f"\n  NOVO (nao catalogado em known_external_dependencies): {sorted(truly_new)}")

    expected_counts = {}  # ex.: {"sky130_fd_pr__nfet_01v8__tt.pm3.spice": 63} se voce confirmar o numero certo
    if report.has_blocking_issues(expected_counts):
        print("\n>>> BLOQUEANTE: issues encontradas, ver acima.", file=sys.stderr)
        return 2
    return 0


def cmd_convert(args):
    filepaths = _expand_inputs(args.input)
    if not filepaths:
        print(f"Nenhum arquivo encontrado para: {args.input}", file=sys.stderr)
        return 1

    patches = load_patches(Path(args.patches))
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    total_applications = []
    for fp in filepaths:
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        logical = join_continuations(lines)
        patched, applications = apply_patches(logical, patches, filename=fp.name)
        total_applications.extend(applications)

        out_lines = []
        for ll in patched:
            out_lines.extend(split_for_output(ll.text))

        out_path = outdir / fp.name
        out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"  {fp.name}: {len(applications)} patch(es) aplicado(s) -> {out_path}")

    print(f"\nTotal de patches aplicados: {len(total_applications)}")
    for app in total_applications:
        print(f"  [{app.patch_id}] linha(s) original(is) {app.source_lines}: "
              f"{app.before[:60]!r} -> {app.after[:60]!r}")

    # roda o scanner nos arquivos de SAIDA para validar a conversao
    print()
    report = scan_files(list(outdir.glob("*.spice")))
    print(report.summary())

    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Roda checks estruturais sem converter")
    p_scan.add_argument("--input", nargs="+", required=True)
    p_scan.add_argument("--patches", required=False)
    p_scan.set_defaults(func=cmd_scan)

    p_conv = sub.add_parser("convert", help="Aplica patches e escreve netlists Xyce")
    p_conv.add_argument("--input", nargs="+", required=True)
    p_conv.add_argument("--patches", required=True)
    p_conv.add_argument("--outdir", required=True)
    p_conv.set_defaults(func=cmd_convert)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
