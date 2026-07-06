"""
Stub do gate de validacao ngspice-vs-Xyce. Ainda NAO executa simulacao --
so define a estrutura e a matriz de testes que decidimos priorizar, para
voce plugar as chamadas reais do ngspice/Xyce na sua maquina Docker (que
ja tem o PDK instalado).

Ordem de custo x cobertura (do relatorio anterior):
  1. gm/gds vs Vgs, Vds          -- barato, 1a ordem
  2. C-V (Cgg/Cgs/Cgd/Cdb/Csb)   -- barato, carga intrinseca + juncao
  3. Y-parameters (.AC) na faixa RF alvo -- medio, cobre tudo acima + parasitas
  4. IIP3 dois-tons (.HB vs transiente+FFT) -- medio-alto, nao-linearidade
  5. .NOISE                      -- barato, termico/flicker

Os 3 primeiros devem ser gate obrigatorio (bloqueia o build no Docker se
divergirem alem da tolerancia); os 2 ultimos rodam por device-alvo, nao
necessariamente em todo bin.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class ValidationCase:
    name: str
    description: str
    tolerance_pct: float
    blocking: bool  # se True, falha o build/Docker quando divergir


VALIDATION_MATRIX = [
    ValidationCase("gm_gds_dc", "gm/gds vs Vgs, Vds", tolerance_pct=2.0, blocking=True),
    ValidationCase("cv_curves", "Cgg/Cgs/Cgd/Cdb/Csb vs Vgs, Vds", tolerance_pct=3.0, blocking=True),
    ValidationCase("y_parameters", ".AC Y11/Y12/Y21/Y22 na faixa RF alvo", tolerance_pct=5.0, blocking=True),
    ValidationCase("iip3_two_tone", ".HB (Xyce) vs transiente+FFT (ngspice)", tolerance_pct=10.0, blocking=False),
    ValidationCase("noise", ".NOISE termico + flicker", tolerance_pct=15.0, blocking=False),
]


def run_case(case: ValidationCase,
             ngspice_runner: Callable[[str], dict],
             xyce_runner: Callable[[str], dict],
             netlist_template: str) -> Optional[bool]:
    """
    Placeholder: chame aqui os runners reais (subprocess para ngspice -b /
    Xyce na sua maquina Docker), parseie os .raw/.prn de cada um, compare
    com np.allclose(..., rtol=case.tolerance_pct/100) e retorne pass/fail.

    Deixado como TODO deliberadamente -- o formato de saida do ngspice
    (.raw binario/ascii) e do Xyce (.prn) sao diferentes o suficiente para
    merecer um parser dedicado por ferramenta, que depende de como voce
    already estrutura os testbenches no run.py atual.
    """
    raise NotImplementedError(
        f"TODO: plugar runner real para o caso '{case.name}' na maquina Docker"
    )


def main():
    print("Matriz de validacao configurada:")
    for case in VALIDATION_MATRIX:
        blocking_txt = "BLOQUEANTE" if case.blocking else "informativo"
        print(f"  [{blocking_txt}] {case.name}: {case.description} "
              f"(tolerancia {case.tolerance_pct}%)")
    print("\nPreencha run_case() com os runners de ngspice/Xyce da sua imagem Docker.")


if __name__ == "__main__":
    main()
