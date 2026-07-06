"""
Checks estruturais de sanidade -- o "gate" que deve falhar alto em vez de
converter silenciosamente errado.

Cobre, por enquanto:
  1. Contagem de .model cards vs. contagem de bins declarada no cabecalho
     do corner file (achamos uma divergencia real: 63 declarados vs. 180
     .model cards no nfet_01v8__tt -- ver known_issues no relatorio).
  2. Parametros referenciados dentro de expressoes {...} que nao tem
     definicao (.param) em nenhum arquivo do conjunto processado --
     sinal de dependencia externa nao capturada (achamos isso com
     *_slope usado para mismatch, definido em outro lugar da cadeia).
  3. Presenca de .model de diodo com level=3 (nao suportado no Xyce).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

MODEL_RE = re.compile(r"^\.model\s+(\S+)\b", re.IGNORECASE)
BINCOUNT_COMMENT_RE = re.compile(r"Number of bins:\s*(\d+)", re.IGNORECASE)
PARAM_DEF_RE = re.compile(r"^\.param\b|^\+\s*[A-Za-z_][A-Za-z0-9_]*\s*=", re.IGNORECASE)
PARAM_DEF_NAME_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=")
# Lookbehind evita casar o "e"/"E" de notacao cientifica (ex.: 4.148e-09)
# como se fosse um identificador solto.
IDENTIFIER_IN_EXPR_RE = re.compile(r"(?<![0-9.])[A-Za-z_][A-Za-z0-9_]*")
DIODE_LEVEL3_RE = re.compile(r"\.model\s+\S+\s+d\b.*\blevel\s*=\s*3(\.0)?\b", re.IGNORECASE)

# palavras reservadas / funcoes que nao contam como "parametro indefinido"
BUILTIN_TOKENS = {
    "l", "w", "nf", "ad", "as", "pd", "ps", "nrd", "nrs", "sa", "sb", "sd", "mult",
    "mc_mm_switch", "agauss", "sqrt", "abs", "min", "max", "pow", "temper", "temp",
    "d", "g", "s", "b", "nmos", "pmos",
}


@dataclass
class ScanReport:
    model_count_by_file: Dict[str, int] = field(default_factory=dict)
    declared_bin_count_by_file: Dict[str, int] = field(default_factory=dict)
    undefined_params: Set[str] = field(default_factory=set)
    diode_level3_hits: List[str] = field(default_factory=list)
    known_external_deps_confirmed: Set[str] = field(default_factory=set)

    def has_blocking_issues(self, expected_model_counts: Dict[str, int] = None) -> bool:
        blocking = bool(self.diode_level3_hits)
        if expected_model_counts:
            for fname, expected in expected_model_counts.items():
                actual = self.model_count_by_file.get(fname)
                if actual is not None and actual != expected:
                    blocking = True
        return blocking

    def summary(self) -> str:
        lines = ["=== Relatorio de scan estrutural ==="]
        for fname, count in self.model_count_by_file.items():
            lines.append(f"  {fname}: {count} .model cards")
        for fname, count in self.declared_bin_count_by_file.items():
            lines.append(f"  {fname}: 'Number of bins' declarado = {count}")
        if self.diode_level3_hits:
            lines.append(f"  ALERTA: diodo level=3 encontrado em: {self.diode_level3_hits}")
        if self.undefined_params:
            lines.append(
                "  ALERTA: parametros referenciados em expressoes mas sem "
                f".param no conjunto processado: {sorted(self.undefined_params)}"
            )
        return "\n".join(lines)


def _strip_comment_lines(text: str) -> str:
    """Remove linhas de comentario inteiras (iniciadas por '*') antes de
    procurar expressoes {...} -- evita falsos positivos vindos de blocos
    de comentario tipo '* statistics { mismatch { vary ... } }'."""
    kept = []
    for line in text.splitlines():
        if line.strip().startswith("*"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _collect_defined_params(all_text: str) -> Set[str]:
    defined = set()
    for m in PARAM_DEF_NAME_RE.finditer(all_text):
        defined.add(m.group(1).lower())
    return defined


def _collect_referenced_identifiers(all_text: str) -> Set[str]:
    referenced = set()
    for expr in re.findall(r"\{([^{}]*)\}", all_text):
        for ident in IDENTIFIER_IN_EXPR_RE.findall(expr):
            referenced.add(ident.lower())
    return referenced


def scan_files(filepaths: List[Path]) -> ScanReport:
    report = ScanReport()
    combined_text = []

    for fp in filepaths:
        text = fp.read_text(encoding="utf-8", errors="replace")
        combined_text.append(text)

        model_count = 0
        for line in text.splitlines():
            m = MODEL_RE.match(line.strip())
            if m:
                model_count += 1
                if DIODE_LEVEL3_RE.search(line):
                    report.diode_level3_hits.append(f"{fp.name}: {line.strip()}")
        if model_count:
            report.model_count_by_file[fp.name] = model_count

        bin_m = BINCOUNT_COMMENT_RE.search(text)
        if bin_m:
            report.declared_bin_count_by_file[fp.name] = int(bin_m.group(1))

    full_text = _strip_comment_lines("\n".join(combined_text))
    defined = _collect_defined_params(full_text)
    referenced = _collect_referenced_identifiers(full_text)

    undefined = {
        ident for ident in referenced
        if ident not in defined and ident not in BUILTIN_TOKENS and not ident.isdigit()
    }
    report.undefined_params = undefined

    return report
