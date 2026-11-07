"""Cada teste leva o nome do defeito que impede: o núcleo decide quem recebe o quê, quando e quantas vezes."""
import datetime as dt
import itertools
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nucleo as n

SEG_10H = dt.datetime(2026, 11, 9, 10, 0, tzinfo=ZoneInfo(n.TZ))  # segunda-feira


def contatos(qtd, **vars_):
    return [{"numero": f"55119{10000000 + i}", "vars": vars_ or {"nome": f"P{i}"}, "linha": i + 2} for i in range(qtd)]


# ---- número
def test_numero_com_ddd_e_sem_pais_ganha_55():
    assert n.normalizar_numero("(48) 99979-2326") == ("5548999792326", "")


def test_celular_antigo_de_8_digitos_recebe_o_nono_digito():
    assert n.normalizar_numero("48 9979-2326")[0] == "5548999792326"


def test_telefone_fixo_nao_vira_destino_de_whatsapp():
    num, motivo = n.normalizar_numero("48 3333-4444")
    assert num is None and "fixo" in motivo


def test_numero_curto_ou_estrangeiro_e_recusado_com_motivo():
    assert n.normalizar_numero("12345")[0] is None
    assert n.normalizar_numero("+1 415 555 0100")[0] is None
    assert n.normalizar_numero("")[0] is None


def test_ddd_inexistente_e_recusado():
    assert n.normalizar_numero("10 99999-9999")[0] is None


# ---- planilha
def test_csv_do_excel_com_bom_e_ponto_e_virgula_le_numero_e_variaveis():
    r = n.ler_csv("﻿Nome;Celular;Valor\nAna;(11) 91234-5678;R$ 10\n")
    assert r["contatos"][0]["numero"] == "5511912345678"
    assert r["contatos"][0]["vars"] == {"nome": "Ana", "valor": "R$ 10"}


def test_csv_sem_coluna_de_numero_e_recusado_inteiro():
    with pytest.raises(n.PlanilhaInvalida):
        n.ler_csv("nome,email\nAna,a@b.c\n")


def test_csv_acima_do_teto_de_linhas_e_recusado():
    corpo = "numero\n" + "\n".join(f"5511912{i:06d}" for i in range(n.MAX_LINHAS + 1))
    with pytest.raises(n.PlanilhaInvalida):
        n.ler_csv(corpo)


def test_numero_repetido_na_planilha_conta_uma_vez_e_invalido_aparece_com_a_linha():
    r = n.ler_csv("numero,nome\n11912345678,A\n(11) 91234-5678,B\n123,C\n")
    assert len(r["contatos"]) == 1 and r["duplicados"] == 1
    assert r["invalidos"][0]["linha"] == 4


# ---- template
def test_template_com_coluna_ausente_nao_envia_a_chave_literal():
    with pytest.raises(n.FaltaVariavel):
        n.renderizar("Oi {nome}, seu valor é {valor}", {"nome": "Ana"}, "x")


def test_variavel_vazia_nao_vira_oi_virgula_vazio():
    with pytest.raises(n.FaltaVariavel):
        n.renderizar("Oi {nome}", {"nome": ""}, "x")


def test_variacao_e_estavel_para_o_mesmo_numero_e_usa_as_duas_opcoes_no_lote():
    t = "{Oi|Olá} {nome}"
    assert n.renderizar(t, {"nome": "A"}, "5511900000001") == n.renderizar(t, {"nome": "A"}, "5511900000001")
    vistos = {n.renderizar(t, {"nome": "A"}, f"55119{i:08d}").split()[0] for i in range(40)}
    assert vistos == {"Oi", "Olá"}


def test_rodape_de_saida_nao_duplica_quando_o_autor_ja_pos():
    assert n.com_saida("Oi").endswith("SAIR para não receber mais mensagens.")
    assert n.com_saida("Oi, mande SAIR para parar") == "Oi, mande SAIR para parar"


# ---- ritmo
def test_conta_nova_nao_passa_de_20_no_primeiro_dia_e_o_resto_vai_para_amanha():
    p = n.planejar(contatos(50), "Oi {nome}", SEG_10H)["agenda"]
    dias = [a["quando"][:10] for a in p]
    assert dias.count("2026-11-09") == 20 and dias.count("2026-11-10") == 30


def test_aquecimento_dobra_a_cada_dia_ate_o_teto():
    r = n.Ritmo()
    assert [n.limite_do_dia(r, i) for i in range(6)] == [20, 40, 80, 160, 300, 300]


def test_envios_ja_feitos_hoje_descontam_do_teto_do_dia():
    p = n.planejar(contatos(5), "Oi {nome}", SEG_10H, ja_enviados_hoje=18)["agenda"]
    assert [a["quando"][:10] for a in p].count("2026-11-09") == 2


def test_lote_que_comeca_perto_das_18_nao_vaza_para_a_noite_e_continua_no_dia_seguinte():
    tarde = dt.datetime(2026, 11, 9, 17, 55, tzinfo=ZoneInfo(n.TZ))
    p = n.planejar(contatos(30), "Oi {nome}", tarde, idade_conta_dias=10)["agenda"]
    horas = [dt.datetime.fromisoformat(a["quando"]) for a in p]
    assert all(9 <= h.hour < 18 for h in horas), [h.isoformat() for h in horas if not 9 <= h.hour < 18]
    assert any(h.date() == dt.date(2026, 11, 10) for h in horas)


def test_pedido_de_madrugada_so_comeca_as_9():
    cedo = dt.datetime(2026, 11, 9, 3, 0, tzinfo=ZoneInfo(n.TZ))
    assert n.planejar(contatos(1), "Oi {nome}", cedo)["agenda"][0]["quando"].startswith("2026-11-09T09:00")


def test_intervalo_entre_mensagens_nunca_e_menor_que_o_minimo():
    p = n.planejar(contatos(15), "Oi {nome}", SEG_10H)["agenda"]
    t = [dt.datetime.fromisoformat(a["quando"]) for a in p]
    assert all((b - a).total_seconds() >= 20 for a, b in itertools.pairwise(t))


def test_quem_pediu_sair_nao_entra_no_plano_e_o_motivo_aparece():
    cs = contatos(3)
    r = n.planejar(cs, "Oi {nome}", SEG_10H, saidas=frozenset({cs[1]["numero"]}))
    assert len(r["agenda"]) == 2 and r["recusados"] == [{"numero": cs[1]["numero"], "motivo": "pediu para sair"}]


def test_linha_sem_a_coluna_do_template_e_recusada_sem_travar_as_outras():
    cs = contatos(2) + [{"numero": "5511900000099", "vars": {}, "linha": 9}]
    r = n.planejar(cs, "Oi {nome}", SEG_10H)
    assert len(r["agenda"]) == 2 and "nome" in r["recusados"][0]["motivo"]


def test_mesmo_pedido_gera_sempre_o_mesmo_plano():
    a = n.planejar(contatos(30), "{Oi|Olá} {nome}", SEG_10H)
    assert a == n.planejar(contatos(30), "{Oi|Olá} {nome}", SEG_10H)


# ---- vários números por conta
def test_o_decimo_numero_entra_e_o_decimo_primeiro_e_recusado():
    atuais = [f"55119{i:08d}" for i in range(9)]
    assert n.pode_conectar(atuais, "(11) 91234-5678")[0] is True
    ok, motivo = n.pode_conectar(atuais + ["5511912345678"], "(21) 98888-7777")
    assert not ok and "10" in motivo


def test_numero_repetido_ou_de_telefone_fixo_nao_ocupa_vaga_de_conexao():
    assert not n.pode_conectar(["5511912345678"], "11 91234-5678")[0]
    assert not n.pode_conectar([], "11 3333-4444")[0]


def test_numero_novo_recebe_fatia_pequena_e_ninguem_passa_do_proprio_teto_no_dia():
    rem = [{"id": "veterano", "idade_dias": 10}, {"id": "novo", "idade_dias": 0}]
    p = n.planejar_multi(contatos(300), "Oi {nome}", SEG_10H, rem)["agenda"]
    hoje = [a for a in p if a["quando"].startswith("2026-11-09")]
    por = {i: sum(1 for a in hoje if a["remetente"] == i) for i in ("veterano", "novo")}
    assert por["novo"] <= 20 and por["veterano"] > por["novo"] * 5
    # a capacidade somada de hoje (300 + 20) cobre o lote: repartir por igual empurraria 130 para amanhã sem necessidade
    assert len(hoje) == len(p) == 300


def test_cada_contato_recebe_de_um_numero_so():
    rem = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    p = n.planejar_multi(contatos(60), "Oi {nome}", SEG_10H, rem)["agenda"]
    assert len({a["numero"] for a in p}) == len(p) == 60


def test_quem_pediu_sair_nao_ocupa_cota_de_nenhum_numero():
    cs = contatos(10)
    r = n.planejar_multi(cs, "Oi {nome}", SEG_10H, [{"id": "a"}], saidas=frozenset({cs[0]["numero"]}))
    assert len(r["agenda"]) == 9 and r["recusados"][0]["motivo"] == "pediu para sair"


def test_mais_de_10_remetentes_ou_nenhum_ou_repetido_e_recusado():
    for rem in ([], [{"id": str(i)} for i in range(11)], [{"id": "a"}, {"id": "a"}]):
        with pytest.raises(ValueError):
            n.planejar_multi(contatos(1), "Oi {nome}", SEG_10H, rem)


def test_plano_com_varios_numeros_e_sempre_o_mesmo():
    rem = [{"id": "a", "idade_dias": 3}, {"id": "b"}]
    assert n.planejar_multi(contatos(40), "{Oi|Olá} {nome}", SEG_10H, rem) == \
        n.planejar_multi(contatos(40), "{Oi|Olá} {nome}", SEG_10H, rem)
