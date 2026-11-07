"""Núcleo puro do zap-envios: número, planilha, template e ritmo. Sem rede, sem relógio, sem banco.

Por que puro: o risco deste produto é o ban do número e a mensagem errada para a pessoa errada. Os dois se
decidem aqui, antes de qualquer envio, e por isso têm de ser exatos e testáveis (o avaliador vem antes do gerador).
O envio de verdade (Evolution) e a fila ficam em outros módulos e só executam o que este plano disse.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from zoneinfo import ZoneInfo

TZ = "America/Sao_Paulo"
MAX_NUMEROS_POR_CONTA = 10  # cada número é um risco de ban separado; mais que isso é revenda, não aviso à própria base
MAX_LINHAS = 500  # por planilha: lista maior que isso é disparo frio, não aviso à própria base
RODAPE_SAIR = "\n\nResponda SAIR para não receber mais mensagens."
COLUNAS_NUMERO = ("numero", "telefone", "celular", "whatsapp", "fone", "phone", "tel")


class PlanilhaInvalida(ValueError):
    """A planilha inteira não serve (sem coluna de número, grande demais, vazia)."""


class FaltaVariavel(ValueError):
    """O template pede {coluna} que a linha não tem: nunca se envia a chave literal."""


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower().strip()


# ------------------------------------------------------------------ número

def normalizar_numero(bruto: str) -> tuple[str | None, str]:
    """(número só com dígitos e país, motivo da recusa). Brasil apenas: 55 + DDD + celular de 9 dígitos."""
    d = re.sub(r"\D", "", bruto or "").lstrip("0")
    if len(d) in (10, 11):
        d = "55" + d
    if len(d) not in (12, 13) or not d.startswith("55"):
        return None, "tamanho inválido (use DDD + número, só Brasil)"
    ddd, resto = d[2:4], d[4:]
    if not ("11" <= ddd <= "99") or ddd[1] == "0":
        return None, f"DDD {ddd} não existe"
    if len(resto) == 8:
        if resto[0] not in "6789":
            return None, "telefone fixo não tem WhatsApp"
        resto = "9" + resto  # celular antigo, sem o nono dígito
    if resto[0] != "9":
        return None, "celular precisa começar com 9"
    return "55" + ddd + resto, ""


# ------------------------------------------------------------------ planilha

def ler_csv(texto: str) -> dict:
    """{colunas, contatos:[{numero, vars, linha}], invalidos:[{linha, valor, motivo}], duplicados}."""
    texto = texto.lstrip("﻿")
    linhas = [ln for ln in texto.splitlines() if ln.strip()]
    if not linhas:
        raise PlanilhaInvalida("planilha vazia")
    sep = ";" if linhas[0].count(";") > linhas[0].count(",") else ","
    rows = list(csv.reader(io.StringIO("\n".join(linhas)), delimiter=sep))
    cab = [_sem_acento(c) for c in rows[0]]
    col = next((i for i, c in enumerate(cab) if c in COLUNAS_NUMERO), None)
    if col is None:
        raise PlanilhaInvalida("sem coluna de número (chame de numero, telefone, celular ou whatsapp)")
    dados = rows[1:]
    if len(dados) > MAX_LINHAS:
        raise PlanilhaInvalida(f"{len(dados)} linhas; o teto é {MAX_LINHAS} por planilha")
    contatos, invalidos, vistos, dup = [], [], set(), 0
    for n, r in enumerate(dados, start=2):
        valor = r[col] if col < len(r) else ""
        num, motivo = normalizar_numero(valor)
        if not num:
            invalidos.append({"linha": n, "valor": valor, "motivo": motivo})
        elif num in vistos:
            dup += 1
        else:
            vistos.add(num)
            vars_ = {cab[i]: v.strip() for i, v in enumerate(r) if i != col and i < len(cab) and cab[i]}
            contatos.append({"numero": num, "vars": vars_, "linha": n})
    return {"colunas": [c for i, c in enumerate(cab) if i != col and c], "contatos": contatos,
            "invalidos": invalidos, "duplicados": dup}


# ------------------------------------------------------------------ template

_CHAVE = re.compile(r"\{([^{}]+)\}")


def _sorteio(semente: str, n: int) -> int:
    return int(hashlib.sha256(semente.encode()).hexdigest(), 16) % n


def renderizar(template: str, vars_: dict[str, str], semente: str) -> str:
    """{nome} troca pela coluna; {oi|olá|e aí} escolhe uma opção, sempre a mesma para a mesma semente.
    A variação evita 500 mensagens byte a byte iguais, que é o padrão que derruba o número."""
    def troca(m: re.Match) -> str:
        dentro = m.group(1)
        if "|" in dentro:
            ops = dentro.split("|")
            return ops[_sorteio(semente + dentro, len(ops))]
        v = vars_.get(_sem_acento(dentro), "")
        if not v:
            raise FaltaVariavel(_sem_acento(dentro))
        return v
    return _CHAVE.sub(troca, template)


def com_saida(texto: str) -> str:
    """Toda mensagem leva a forma de sair (LGPD e higiene do número); não duplica se o autor já pôs."""
    return texto if re.search(r"\bsair\b", texto, re.IGNORECASE) else texto + RODAPE_SAIR


# ------------------------------------------------------------------ ritmo

@dataclass(frozen=True)
class Ritmo:
    janela: tuple[int, int] = (9, 18)       # só envia entre 09:00 e 18:00 (horário de Brasília)
    intervalo_s: tuple[int, int] = (20, 60)  # pausa aleatória entre mensagens
    teto_dia: int = 300                      # mesmo teto do maus-conexoes (CONEXOES_TETO_DIA)
    primeiro_dia: int = 20                   # conta nova: 20, 40, 80, 160, ... até o teto


RITMO_PADRAO = Ritmo()


def limite_do_dia(r: Ritmo, idade_dias: int) -> int:
    return min(r.teto_dia, r.primeiro_dia * 2 ** max(0, min(idade_dias, 10)))


def _abre(d: dt.date, r: Ritmo) -> dt.datetime:
    return dt.datetime.combine(d, dt.time(r.janela[0]), tzinfo=ZoneInfo(TZ))


def planejar(contatos: list[dict], template: str, inicio: dt.datetime, *, idade_conta_dias: int = 0,
             ja_enviados_hoje: int = 0, saidas: frozenset[str] = frozenset(), ritmo: Ritmo = RITMO_PADRAO) -> dict:
    """{agenda:[{numero, texto, quando}], recusados:[{numero, motivo}]}. Determinístico: mesma entrada, mesmo plano."""
    z = ZoneInfo(TZ)
    cur = inicio.astimezone(z)
    primeiro = cur.date()
    por_dia: dict[dt.date, int] = {primeiro: ja_enviados_hoje}
    agenda, recusados = [], []
    for c in contatos:
        if c["numero"] in saidas:
            recusados.append({"numero": c["numero"], "motivo": "pediu para sair"})
            continue
        try:
            texto = com_saida(renderizar(template, c.get("vars", {}), c["numero"]))
        except FaltaVariavel as e:
            recusados.append({"numero": c["numero"], "motivo": f"falta a coluna {e}"})
            continue
        while True:
            dia = cur.date()
            cur = max(cur, _abre(dia, ritmo))
            idade = idade_conta_dias + (dia - primeiro).days
            if cur.hour >= ritmo.janela[1] or por_dia.get(dia, 0) >= limite_do_dia(ritmo, idade):
                cur = _abre(dia + dt.timedelta(days=1), ritmo)
                continue
            break
        agenda.append({"numero": c["numero"], "texto": texto, "quando": cur.isoformat()})
        por_dia[cur.date()] = por_dia.get(cur.date(), 0) + 1
        lo, hi = ritmo.intervalo_s
        cur += dt.timedelta(seconds=lo + _sorteio(c["numero"] + str(len(agenda)), hi - lo + 1))
    return {"agenda": agenda, "recusados": recusados}


# ------------------------------------------------------------------ vários números por conta

def pode_conectar(conectados: list[str], novo: str) -> tuple[bool, str]:
    """(pode, motivo). O limite é por conta (10), o número tem de ser de WhatsApp válido e não repetido."""
    num, motivo = normalizar_numero(novo)
    if not num:
        return False, motivo
    if num in conectados:
        return False, "esse número já está conectado"
    if len(conectados) >= MAX_NUMEROS_POR_CONTA:
        return False, f"o limite é {MAX_NUMEROS_POR_CONTA} números por conta"
    return True, ""


def planejar_multi(contatos: list[dict], template: str, inicio: dt.datetime, remetentes: list[dict], *,
                   saidas: frozenset[str] = frozenset(), ritmo: Ritmo = RITMO_PADRAO) -> dict:
    """Reparte o lote entre os números da conta. `remetentes`: [{id, idade_dias, ja_hoje}].

    Cada número segue o próprio aquecimento e o próprio teto (o ban é por número), então um número novo recebe
    uma fatia pequena e o veterano, a grande. Cada contato vai para um só número. Cada item da agenda leva `remetente`."""
    ids = [r["id"] for r in remetentes]
    if not ids:
        raise ValueError("nenhum número conectado")
    if len(set(ids)) != len(ids):
        raise ValueError("número repetido entre os remetentes")
    if len(ids) > MAX_NUMEROS_POR_CONTA:
        raise ValueError(f"o limite é {MAX_NUMEROS_POR_CONTA} números por conta")
    recusados = [{"numero": c["numero"], "motivo": "pediu para sair"} for c in contatos if c["numero"] in saidas]
    pesos = {r["id"]: max(1, limite_do_dia(ritmo, r.get("idade_dias", 0)) - r.get("ja_hoje", 0)) for r in remetentes}
    fatias: dict[str, list[dict]] = {i: [] for i in ids}
    for c in contatos:
        if c["numero"] not in saidas:
            # quem ficaria com a menor carga RELATIVA à própria capacidade de hoje; empate pelo id (determinístico)
            fatias[min(ids, key=lambda i: ((len(fatias[i]) + 1) / pesos[i], i))].append(c)
    agenda = []
    for r in remetentes:
        p = planejar(fatias[r["id"]], template, inicio, idade_conta_dias=r.get("idade_dias", 0),
                     ja_enviados_hoje=r.get("ja_hoje", 0), ritmo=ritmo)
        agenda += [{**a, "remetente": r["id"]} for a in p["agenda"]]
        recusados += p["recusados"]
    agenda.sort(key=lambda a: (a["quando"], a["remetente"]))
    return {"agenda": agenda, "recusados": recusados}
