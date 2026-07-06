# sky130_xyce_convert

Conversor sky130_fd_pr (dialeto ngspice/hspice) -> Xyce, para viabilizar
simulacoes Harmonic Balance (mixer, PA, LNA, PLL). Foco atual: `nfet_01v8`
/ `pfet_01v8`; expansao planejada para dispositivos de tensao mais alta.

## Por que essa arquitetura

- **`patches/*.yaml`**: manifesto declarativo de incompatibilidades
  conhecidas (regex de/para + motivo + se ja foi confirmado no device
  atual). Patches sao dados, nao logica espalhada em if/else -- facilita
  auditoria e voce reaproveita/estende esse manifesto conforme descobre
  casos novos (esperado ao entrar nos dispositivos HV).
- **`converter/joiner.py`**: junta linhas de continuacao `+` em "linhas
  logicas" antes de aplicar regex. Suficiente para o formato do sky130 --
  nao tentamos um parser SPICE/AST completo (over-engineering para o
  problema).
- **`converter/patcher.py`**: aplica o manifesto sobre as linhas logicas.
- **`converter/scanner.py`**: checks estruturais de sanidade -- gate que
  deve falhar alto, nunca converter silenciosamente errado. Hoje cobre:
  contagem de `.model` cards, contagem de bins declarada no corner file,
  deteccao de `.model` de diodo `level=3`, e **deteccao de parametros
  referenciados em expressoes `{...}` sem `.param` correspondente no
  conjunto de arquivos processado** (ver achado abaixo).
- **`validate.py`**: stub da matriz de validacao ngspice-vs-Xyce (gm/gds,
  C-V, Y-parameters, IIP3 via HB, ruido). Os runners reais (subprocess
  para ngspice/Xyce) ficam para voce plugar na maquina Docker que ja tem
  o PDK instalado -- os formatos de saida (.raw do ngspice vs .prn do
  Xyce) sao diferentes o bastante para merecer parser dedicado por
  ferramenta, dependente de como o `run.py` atual estrutura testbenches.

## Achados confirmados nos arquivos reais (nfet_01v8, corner tt)

Rodando `converter.cli scan` nos dois arquivos do repositorio:

1. **Ruido esta parametrizado com valores reais**, nao defaults do BSIM4:
   `noia=2.5e+42`, `em=41000000.0`, `ntnoi=1.0`, `af=1.0`, `tnoia`,
   `tnoib`, `rnoia=0.94`, `rnoib=0.26` por bin. `noib`/`kf` vem zerados
   (termos desligados), o que e normal e nao indica ausencia de modelo.

2. **Divergencia real de contagem de bins**: `tt.corner.spice` declara
   `Number of bins: 63` (63 blocos `Bin NNN` com offsets `_diff_N`,
   N=0..62), mas `tt.pm3.spice` tem **180** `.model` cards
   (`.model.0` a `.model.179`). Os `_diff_N` do corner file **nao sao
   referenciados em nenhum lugar do pm3.spice** -- o mecanismo usado la
   e outro: mismatch estatistico via `AGAUSS(...)*MC_MM_SWITCH` sobre
   parametros `*_slope` (nao `*_diff_N`).

3. **Dependencia externa -- RESOLVIDA**: `sky130_fd_pr__nfet_01v8__toxe_slope`,
   `..._vth0_slope`, `..._voff_slope`, `..._vth0_slope1` sao referenciados
   dentro de expressoes do pm3.spice mas nao tinham `.param` definido nos
   dois arquivos originalmente inspecionados. Confirmado na arvore real do
   PDK (`$PDK_ROOT/$PDK/libs.ref/sky130_fd_pr/spice/`, container Docker):
   os 4 sao definidos em `sky130_fd_pr__nfet_01v8__mismatch.corner.spice`.
   O pipeline de `scan`/`convert` precisa incluir esse arquivo no conjunto
   processado (ja coberto pelo glob `sky130_fd_pr__nfet_01v8__*.spice`
   usado em `docker/sky130_xyce_convert/install.sh` no eda-env) -- sem
   isso, o Xyce reclama de parametro indefinido ao instanciar o device
   fora do contexto completo do PDK.

4. **Boas noticias**: nao foram encontrados neste arquivo especifico:
   token solto `vt`, token solto `temp`, comentario `$`, nem `.model` de
   diodo com `level=3`. Os patches correspondentes ficam no manifesto
   como rede de seguranca (`verified_in_nfet_01v8_tt: not_found`), pois
   sao esperados em outros arquivos do PDK (primitivos de diodo/resistor
   explicitos, ainda nao inspecionados).

## Uso

```bash
# so diagnostico, nao escreve nada
python3 -m converter.cli scan \
    --input "path/para/sky130_fd_pr__nfet_01v8__tt.pm3.spice" \
            "path/para/sky130_fd_pr__nfet_01v8__tt.corner.spice" \
    --patches patches/nfet_01v8.yaml

# aplica patches e escreve netlists convertidos
python3 -m converter.cli convert \
    --input "path/para/*.spice" \
    --patches patches/nfet_01v8.yaml \
    --outdir build/xyce/nfet_01v8
```

## Proximos passos sugeridos

1. ~~Rodar `scan` contra a arvore completa do sky130_fd_pr...~~ RESOLVIDO --
   ver achado 3 acima (`mismatch.corner.spice`).
2. Confirmar a divergencia 63 vs 180 -- pode ser esperado (bins mais
   finos no lado eletrico do que no lado de corner-offset) ou pode
   indicar que faltam blocos `_diff_N` de 63 a 179 em algum outro
   arquivo. Se confirmado como esperado, adicionar `expected_counts` no
   `cmd_convert`/CI para travar a contagem futura.
3. Estender `patches/` para os dispositivos HV -- bons candidatos a
   trazer parametros dependentes de `sa`/`sb`/drift region que podem
   tocar as expressoes "dinamicas" que o Xyce rejeita (ver conversa
   sobre resistores dependentes de tensao).
4. Preencher `validate.py` com runners reais de ngspice/Xyce na maquina
   Docker, comecando pelos 3 casos bloqueantes (gm/gds, C-V, Y-params).
5. ~~Integrar como estagio de build no Dockerfile~~ FEITO -- ver
   `docker/sky130_xyce_convert/install.sh` e o stage `xyce-pdk-convert`
   no `Dockerfile` do repo `eda-env` (`FROM pdk-stage`, escopo restrito
   a `nfet_01v8` por enquanto, `scan` bloqueia o build so em hard-fails
   -- diodo level=3 / mismatch de contagem de bins -- nao nos achados
   ainda em aberto). Esse repo e consumido via `git clone` + `checkout`
   pinado por `SKY130_XYCE_CONVERT_VERSION` (build-arg), mesmo padrao
   usado para magic/xschem/pdk. Pendente: publicar este repo em
   `github.com/moduhub/sky130_xyce_convert` (hoje ainda sem git/remoto
   local) para o `SKY130_XYCE_CONVERT_REPO_URL` default resolver.
6. Avaliar propor isso como flag/hook no `open_pdks`
   (`--enable-xyce-sky130`), no mesmo padrao de magic/xschem/netgen,
   em vez de tentar mergear netlists convertidas no `sky130_fd_pr`
   canonico (repo de fonte de foundry, resistente a edits
   format-specific). Depende de validar a conversao em producao
   primeiro (item 4).
