"""
Motor de patches: le o manifesto declarativo (patches/*.yaml) e aplica as
transformacoes registradas sobre as linhas logicas de um arquivo sky130.

Filosofia: patches sao dados (regex de/para + motivo), nao logica
espalhada em if/else. Isso torna o pipeline auditavel e facil de
estender quando novos casos aparecerem (ex.: ao processar dispositivos
de tensao mais alta).
"""
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .joiner import LogicalLine


@dataclass
class Patch:
    id: str
    reason: str
    scope: str
    pattern: Optional[str]
    repl: Optional[str]
    enabled: bool
    verified_in_nfet_01v8_tt: str = "unknown"
    compiled: Optional[re.Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        if self.pattern:
            self.compiled = re.compile(self.pattern)


@dataclass
class PatchApplication:
    patch_id: str
    source_lines: List[int]
    before: str
    after: str


def load_patches(yaml_path: Path) -> List[Patch]:
    with open(yaml_path, "r", encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
    patches = []
    for entry in manifest.get("patches", []):
        patches.append(Patch(
            id=entry["id"],
            reason=entry.get("reason", "").strip(),
            scope=entry.get("scope", "all"),
            pattern=entry.get("pattern"),
            repl=entry.get("repl"),
            enabled=entry.get("enabled", True),
            verified_in_nfet_01v8_tt=entry.get("verified_in_nfet_01v8_tt", "unknown"),
        ))
    return patches


def load_external_deps(yaml_path: Path) -> List[str]:
    with open(yaml_path, "r", encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
    return manifest.get("known_external_dependencies", []) or []


def apply_patches(
    logical_lines: List[LogicalLine],
    patches: List[Patch],
    filename: str,
) -> tuple[List[LogicalLine], List[PatchApplication]]:
    applications: List[PatchApplication] = []
    result: List[LogicalLine] = []

    for ll in logical_lines:
        text = ll.text
        for patch in patches:
            if not patch.enabled or patch.compiled is None:
                continue
            if patch.scope not in ("all",) and patch.scope != "testbench_only":
                # scope explicito por lista de padroes de arquivo (glob simples)
                if not any(Path(filename).match(p) for p in patch.scope):
                    continue
            if patch.scope == "testbench_only":
                continue  # tratado em outro estagio (validate.py), nao aqui
            new_text = patch.compiled.sub(patch.repl, text)
            if new_text != text:
                applications.append(PatchApplication(
                    patch_id=patch.id,
                    source_lines=ll.source_lines,
                    before=text,
                    after=new_text,
                ))
                text = new_text
        result.append(LogicalLine(text=text, source_lines=ll.source_lines,
                                   raw_fragments=ll.raw_fragments))
    return result, applications
