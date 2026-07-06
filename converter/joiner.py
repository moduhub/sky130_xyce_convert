"""
Junta linhas de continuacao SPICE ("+" no inicio da linha) em "linhas
logicas" unicas, preservando o mapeamento para as linhas originais (para
mensagens de erro uteis). Nao tenta ser um parser SPICE completo -- so
resolve continuacao, que e suficiente para aplicar patches via regex.

Uma "linha logica" e uma lista de (numero_da_linha_original, texto) que,
quando concatenada, representa um unico statement.
"""
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class LogicalLine:
    text: str                      # linha logica completa (continuacoes unidas)
    source_lines: List[int]        # numeros de linha originais (1-indexed)
    raw_fragments: List[str]       # fragmentos originais, para reconstrucao


def join_continuations(lines: List[str]) -> List[LogicalLine]:
    logical_lines: List[LogicalLine] = []
    current_fragments: List[str] = []
    current_source: List[int] = []

    def flush():
        if current_fragments:
            joined = " ".join(f.strip() for f in current_fragments)
            logical_lines.append(
                LogicalLine(
                    text=joined,
                    source_lines=list(current_source),
                    raw_fragments=list(current_fragments),
                )
            )

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("+"):
            # continuacao do statement anterior
            current_fragments.append(stripped[1:].strip())
            current_source.append(idx)
            continue

        if stripped.startswith("*"):
            # Comentario e transparente a continuacao: o sky130 intercala
            # comentarios tipo "* Model Flag Parameters" NO MEIO de blocos
            # .model de varias linhas. Sem este caso, o comentario seria
            # tratado como inicio de nova linha logica e as linhas "+"
            # seguintes (lmin/lmax/wmin/wmax/level/... os parametros BSIM4
            # de verdade) seriam absorvidas para dentro do comentario --
            # apagando silenciosamente o .model inteiro. Emite o comentario
            # como sua propria linha logica, sem tocar no statement real
            # que ainda esta sendo acumulado.
            logical_lines.append(
                LogicalLine(text=line, source_lines=[idx], raw_fragments=[line])
            )
            continue

        # nova linha logica comeca aqui: fecha a anterior
        flush()
        current_fragments = [line]
        current_source = [idx]

    flush()
    return logical_lines


def split_for_output(logical_line: str, max_len: int = 200) -> List[str]:
    """
    Reemite uma linha logica no estilo Xyce, quebrando com '+' se ficar
    excessivamente longa. Xyce aceita linhas bem longas, entao isso e
    conservador/opcional -- usado so por legibilidade do netlist gerado.
    """
    if len(logical_line) <= max_len:
        return [logical_line]

    out = []
    remaining = logical_line
    first = True
    while remaining:
        chunk = remaining[:max_len]
        # evita cortar no meio de um parametro se possivel
        if len(remaining) > max_len:
            cut = chunk.rfind(" ")
            if cut > max_len * 0.5:
                chunk = remaining[:cut]
        remaining = remaining[len(chunk):].lstrip()
        out.append(chunk if first else f"+ {chunk}")
        first = False
    return out
