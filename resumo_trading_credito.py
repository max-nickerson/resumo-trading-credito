"""
Resumo Trading Crédito — SÓ O VISUAL, com dados fictícios (o layout do e-mail diário da mesa).

Gera, para uma data:
  saida/resumo_trading_credito_AAAAMMDD.html  -> e-mail (tabelas + estilos inline, gráficos embutidos em base64)
  saida/resumo_trading_credito_AAAAMMDD.pdf   -> o mesmo HTML impresso pelo Edge/Chrome (headless)

Seções (na ordem do e-mail): cabeçalho + faixa do volume consolidado; Debêntures (Não Isentas e Isentas); Bancários; Estruturados.
Cada grupo: 4 cartões (volume, nº de operações, maior ativo, maior emissor), DESTAQUES, gráfico de bolhas dos maiores trades,
evolução de 30 dias (barras = volume, linha = nº de negócios) e a tabela com TODOS OS TRADES. Isentas tem ainda o gráfico de
"negócios contra a marcação" (spread over menos taxa ANBIMA, mediana do dia); Estruturados tem a distribuição por classe.

Os dados vêm de `dados_ficticios(dia)`. Para ligar nos dados reais, troque só essa função por uma que devolva o mesmo dicionário.
Uso:  python resumo_trading_credito.py [AAAA-MM-DD]
"""
import base64
import io
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False                     # "R$" não é fórmula
import matplotlib.pyplot as plt  # noqa: E402

PASTA = Path(__file__).resolve().parent / "saida"
ASSINATURA = ("Nome Sobrenome", "Gerência de Trading", "Itaú Asset • WMS • Itaú Unibanco S.A.")
CDI_AA = 15.00                                                      # para converter %CDI em spread equivalente (bancários)
LARG = 1000                                                         # largura do e-mail em px

# ---------------------------------------------------------------- paleta (tirada do e-mail)
PRETO, TINTA, CINZA, CINZA_CL, BORDA = "#111111", "#1d1d1f", "#6b6b6b", "#f4f5f6", "#e3e5e8"
AZUL_FAIXA = "linear-gradient(90deg,#cbe8f0,#a6d3e1)"
AZUL_BORDA, VERMELHO, SOMBRA_COL = "#3f8fb2", "#a3262a", "#eef2f5"
BOLHAS = ["#14243d", "#2b4f74", "#4b87b1", "#78a5cb", "#23493a", "#2f6a55", "#3c6e8f", "#0f1d33"]
BARRA, LINHA, AZUL_BARRA = "#9b9b9b", "#111111", "#1f5f87"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ================================================================ dados fictícios
def dados_ficticios(dia):
    """Mesmo formato que a versão real vai devolver. Valores inventados (semente fixa pela data)."""
    rng = np.random.default_rng(int(dia.strftime("%Y%m%d")))
    venc = lambda a0, a1: [dia + pd.Timedelta(days=int(d)) for d in rng.integers(int(a0 * 365), int(a1 * 365), 200)]

    emp_cdi = [("TFLEA9", "LOCALIZA FLEET S/A"), ("CMGTA2", "CEMIG GERACAO E TRANSMISSAO S/A"), ("RENTF2", "LOCALIZA RENT A CAR S/A"),
               ("TFLEC0", "LOCALIZA FLEET S/A"), ("BCBF16", "HAPVIDA PARTICIPACOES E INVESTIMENTOS S.A."),
               ("UQFN15", "UNIAO QUIMICA FARMACEUTICA NACIONAL S.A."), ("AEGPA4", "AEGEA SANEAMENTO E PARTICIPACOES S/A"),
               ("VAMO14", "VAMOS LOCACAO DE CAMINHOES MAQUINAS E EQUIPAMENTOS S.A."), ("RENTQ8", "LOCALIZA RENT A CAR S/A"),
               ("INEL12", "INSPIRALI EDUCACAO S/A"), ("SUZBB1", "SUZANO S.A."), ("TUPY25", "TUPY S/A"), ("EQTL17", "EQUATORIAL ENERGIA S.A."),
               ("JSLGA5", "JSL S.A"), ("ASAIA1", "SENDAS DISTRIBUIDORA S/A"), ("SIMH16", "SIMPAR S.A."), ("NTSD16", "NOVA TRANSPORTADORA DO SUDESTE S.A. - NTS"),
               ("TIGR12", "TIGRE S.A PARTICIPACOES"), ("RDORD4", "REDE DOR SAO LUIZ S/A"), ("CEAB14", "C E A MODAS S.A."),
               ("DASAC5", "DIAGNOSTICOS DA AMERICA S/A"), ("COLNA3", "RODOVIAS DAS COLINAS S.A"), ("CPLD27", "COPEL DISTRIBUICAO S/A")]
    n1 = 47
    k = rng.integers(0, len(emp_cdi), n1)
    vol = np.round(np.sort(rng.lognormal(2.0, .8, n1))[::-1].clip(1, 60), 1)
    tx = np.round(rng.gamma(2.2, .6, n1).clip(.3, 6), 2)
    dur = np.round(rng.uniform(.4, 5, n1), 2)
    anb = np.round(tx + rng.normal(0, .12, n1), 2)
    ind = rng.choice(["DI", "DI", "DI", "DI", "DI", "DI", "DI", "IPCA", "%CDI"], n1)
    nao = pd.DataFrame({"ticker": [emp_cdi[i][0] for i in k], "empresa": [emp_cdi[i][1] for i in k], "vencimento": venc(1, 10)[:n1],
                        "duration": dur, "volume": vol, "taxa": tx, "indexador": ind, "taxa_anbima": anb, "incentivada": "N"})
    nao.loc[nao.indexador == "IPCA", "taxa"] = np.round(rng.uniform(7, 8.5, (nao.indexador == "IPCA").sum()), 2)
    nao.loc[nao.indexador == "%CDI", "taxa"] = np.round(rng.uniform(104, 112, (nao.indexador == "%CDI").sum()), 2)
    nao["spread_over"] = np.where(nao.indexador == "IPCA", rng.integers(60, 160, n1), np.nan)
    nao.loc[nao.indexador != "DI", "taxa_anbima"] = np.nan

    emp_ipca = [("JALL15", "JALLES MACHADO S.A."), ("ISAEB2", "ISA ENERGIA BRASIL S.A."), ("CCPV11", "CONCESSIONARIA DE RODOVIAS PRVIAS S.A."),
                ("BTEL13", "V.TAL - REDE NEUTRA DE TELECOMUNICACOES S.A."), ("CART13", "CONCESSIONARIA AUTO RAPOSO TAVARES S/A"),
                ("CGASA2", "COMPANHIA DE GAS DE SAO PAULO - COMGAS"), ("VALEC1", "VALE S/A"), ("CBAN32", "CONCESSIONARIA ROTA DAS BANDEIRAS S/A"),
                ("CEPEC2", "COMPANHIA ENERGETICA DE PERNAMBUCO-CELPE"), ("VLIM18", "VLI MULTIMODAL S.A."), ("CGASA4", "COMPANHIA DE GAS DE SAO PAULO - COMGAS"),
                ("PEJA23", "PRIO FORTE S.A."), ("VRDN12", "VIARONDON CONCESSIONARIA DE RODOVIA S/A"), ("SBSPK8", "CIA SANEAMENTO BASICO EST. SP - SABESP"),
                ("CDES11", "VPORTS AUTORIDADE PORTUARIA S/A")]
    n2 = 42
    k = rng.integers(0, len(emp_ipca), n2)
    vol = np.round(np.sort(rng.lognormal(1.6, .8, n2))[::-1].clip(1, 75), 1)
    dur = np.round(rng.uniform(3, 10, n2), 2)
    so = np.round(rng.normal(70, 45, n2)).astype(int)
    sa = so - np.round(rng.normal(10, 18, n2)).astype(int)
    ref = [f"B{int(30 + d // 1.5):02d}" for d in dur]
    ntnb = 7.0 + .02 * dur
    pre = rng.random(n2) < .07
    isen = pd.DataFrame({"ticker": [emp_ipca[i][0] for i in k], "empresa": [emp_ipca[i][1] for i in k], "vencimento": venc(4, 16)[:n2],
                         "duration": dur, "volume": vol, "taxa": np.round(ntnb + so / 100, 2), "taxa_anbima": sa, "ref": ref,
                         "spread_over": so, "indexador": np.where(pre, "PRÉ", "IPCA"), "incentivada": "S"})
    isen.loc[pre, "ref"] = "ODF30"
    isen.loc[pre, "taxa"] = np.round(13.5 + so[pre] / 100, 2)

    bancos = ["INDUSTRIAL", "VOTO", "XP", "BTG", "MERCANTIL", "SANTANDER", "STELLANTIS", "NUBANK", "SAFRA", "BRADESCO", "C6", "ABC", "BB", "PORTO SEGURO"]
    n3 = 31
    tipo = rng.choice(["LF", "LF", "LF", "LFSN", "LFSC", "CDB"], n3)
    prazo = np.where(np.isin(tipo, ["LFSN", "LFSC"]), rng.uniform(1.5, 5.3, n3), rng.uniform(.2, 3.2, n3))
    vol = np.round(np.sort(rng.lognormal(2.8, .7, n3))[::-1].clip(5, 100), 1)
    spr = np.round(.15 + .1 * prazo + np.where(np.isin(tipo, ["LFSN", "LFSC"]), .3, 0) + rng.normal(0, .06, n3), 2).clip(.05)
    banc = pd.DataFrame({"ativo": tipo, "emissor": rng.choice(bancos, n3), "vencimento": [dia + pd.Timedelta(days=int(p * 365)) for p in prazo],
                         "prazo": prazo, "volume": vol, "taxa": spr, "indexador": "CDI+"})
    cdi_pct = rng.random(n3) < .1
    banc.loc[cdi_pct, "indexador"] = "%CDI"
    banc.loc[cdi_pct, "taxa"] = np.round(100 + banc.taxa[cdi_pct] / CDI_AA * 100, 1)

    estr = pd.DataFrame({"data": [dia] * 3, "ativo": ["FIDC", "CRA", "CRA"], "codigo": ["0579124S34", "CRA022008NB", "CRA02300JR5"],
                         "emissor": ["Pravaler Crédito Universitário Fundo de Investimento em Direitos Creditórios", "RAIZEN", "RAIZEN"],
                         "vencimento": [dia + pd.Timedelta(days=d) for d in (1060, 2150, 1480)], "volume": [25.0, 5.0, 1.0],
                         "taxa": ["1,10", "49,00%par", "49,00%par"], "indexador": ["CDI+", "IPCA+", "IPCA+"]})

    dias = pd.bdate_range(end=dia, periods=22)
    hist = {g: pd.DataFrame({"volume": np.round(rng.lognormal(np.log(m), .35, 22)), "negocios": np.round(rng.lognormal(np.log(n), .3, 22))}, index=dias)
            for g, m, n in (("nao", 420, 45), ("isen", 300, 40), ("banc", 950, 40), ("estr", 50, 12))}
    hist["nao"].iloc[-1] = [nao.volume.sum(), len(nao)]
    hist["isen"].iloc[-1] = [isen.volume.sum(), len(isen)]
    hist["banc"].iloc[-1] = [banc.volume.sum(), len(banc)]
    hist["estr"].iloc[-1] = [estr.volume.sum(), len(estr)]
    dias_m = pd.bdate_range(end=dia, periods=31)
    contra = pd.Series(np.round(rng.normal(0, 17, 31), 1), dias_m)
    contra.iloc[-1] = float(np.median(isen.spread_over - isen.taxa_anbima))
    return dict(nao=nao, isen=isen, banc=banc, estr=estr, hist=hist, contra=contra)


# ================================================================ formatação
def br(v, casas=1):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def mm(v):
    return f"R$ {br(v)} MM"


def data_br(d, ano=True):
    return f"{d:%d}/{MESES[d.month - 1]}/{d:%y}" if ano else f"{d:%d}/{MESES[d.month - 1]}"


def mes_ano(d):
    return f"{MESES[d.month - 1]}/{d:%y}"


def taxa_txt(ind, t):
    return {"DI": f"CDI+ {br(t, 2)}", "CDI+": f"CDI+ {br(t, 2)}", "%CDI": f"{br(t, 1)}% CDI", "IPCA": f"IPCA+ {br(t, 2)}"}.get(ind, br(t, 2))


# ================================================================ gráficos (matplotlib -> PNG base64)
def png(fig):
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(b.getvalue()).decode()


def _eixos(ax):
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0, labelsize=7.5, colors=CINZA)
    ax.grid(color="#ececec", lw=.8)
    ax.set_axisbelow(True)


def bolhas(df, x, y, rotulo, ylab, legenda, xfmt=lambda v: f"{br(v)} anos", yfmt=lambda v: br(v, 2), casas=2, texto=None, maximo=12):
    """Maiores trades: ativos que somam ~80% do volume (agrupados por papel), bolha = volume."""
    g = df.groupby(rotulo).agg(**{x: (x, "mean"), y: (y, "mean"), "volume": ("volume", "sum")}).sort_values("volume", ascending=False)
    g = g[g.volume.cumsum().shift(fill_value=0) < .8 * g.volume.sum()].head(maximo)
    texto = texto or (lambda nome: nome)
    fig, ax = plt.subplots(figsize=(9.6, 3.8))
    _eixos(ax)
    s = 220 + 1700 * g.volume / g.volume.max()
    for k, (nome, r) in enumerate(g.iterrows()):
        ax.scatter(r[x], r[y], s=s.iloc[k], color=BOLHAS[k % len(BOLHAS)], alpha=.95, zorder=3, edgecolor="white", lw=.6)
    y0, y1 = g[y].min(), g[y].max()
    pad = max((y1 - y0) * .45, .2)
    ax.set_ylim(y0 - pad, y1 + pad)
    x0, x1 = g[x].min(), g[x].max()
    ax.set_xlim(x0 - (x1 - x0) * .12 - .1, x1 + (x1 - x0) * .25 + .3)
    yt = [y0 - pad * .8, (y0 + y1) / 2, y1 + pad * .8]
    ax.set_yticks(yt, [yfmt(v) for v in yt])
    xt = [x0, (x0 + x1) / 2, x1]
    ax.set_xticks(xt, [xfmt(v) for v in xt])
    ax.text(0, 1.04, ylab, transform=ax.transAxes, fontsize=7.5, fontweight="bold", color=TINTA)
    ax.text(.04, -.17, legenda, transform=ax.transAxes, fontsize=7, color=CINZA)
    _rotulos(fig, ax, [(f"{texto(nome)}; {br(r[y], casas)}", r[x], r[y], s.iloc[k] ** .5 / 2) for k, (nome, r) in enumerate(g.iterrows())])
    return png(fig)


def _rotulos(fig, ax, itens):
    """Rótulo 'ATIVO; valor' ao lado de cada bolha com traço de ligação; escolhe a posição livre (direita, esquerda, acima, abaixo...)
    sem encostar em outro rótulo nem em outra bolha."""
    rend = fig.canvas.get_renderer()
    ocup = []
    for _, bx, by, rr in itens:                                       # caixas das bolhas (em pixels)
        cx, cy = ax.transData.transform((bx, by))
        rp = rr * fig.dpi / 72
        ocup.append((cx - rp, cy - rp, cx + rp, cy + rp))
    ordem = sorted(range(len(itens)), key=lambda k: -itens[k][3])
    for k in ordem:
        txt, bx, by, rr = itens[k]
        d = rr + 8
        cand = [(d, 0, "left"), (-d, 0, "right")]
        for raio in (d, d + 14, d + 28, d + 44, d + 60):                # depois: em volta da bolha, cada vez mais longe
            for ang in (20, -20, 160, -160, 45, -45, 135, -135, 90, -90, 70, -70, 110, -110):
                dx, dy = raio * np.cos(np.radians(ang)), raio * np.sin(np.radians(ang))
                cand.append((dx, dy, "left" if dx > 5 else "right" if dx < -5 else "center"))
        ab = ax.get_window_extent(rend)
        melhor = None
        for dx, dy, ha in cand:
            a = ax.annotate(txt, (bx, by), xytext=(dx, dy), textcoords="offset points", ha=ha, va="center", fontsize=7.2, fontweight="bold",
                            color=TINTA, zorder=6, arrowprops=dict(arrowstyle="-", color="#c8c8c8", lw=.6, shrinkA=1, shrinkB=rr * .9))
            bb = a.get_window_extent(rend)
            a.remove()
            caixa = (bb.x0 - 2, bb.y0 - 1, bb.x1 + 2, bb.y1 + 1)
            fora = caixa[0] < ab.x0 or caixa[2] > ab.x1 + 60 or caixa[1] < ab.y0 or caixa[3] > ab.y1
            # custo: área sobreposta a rótulos/bolhas já postos + punição forte por sair do gráfico + distância (prefere perto)
            sobre = sum(max(0, min(caixa[2], o[2]) - max(caixa[0], o[0])) * max(0, min(caixa[3], o[3]) - max(caixa[1], o[1]))
                        for j, o in enumerate(ocup) if j != k)
            custo = sobre + 1e5 * fora + .5 * np.hypot(dx, dy)
            if melhor is None or custo < melhor[0]:
                melhor = (custo, dx, dy, ha, caixa)
            if sobre == 0 and not fora:
                break
        _, dx, dy, ha, caixa = melhor
        ax.annotate(txt, (bx, by), xytext=(dx, dy), textcoords="offset points", ha=ha, va="center", fontsize=7.2, fontweight="bold",
                    color=TINTA, zorder=6, arrowprops=dict(arrowstyle="-", color="#c8c8c8", lw=.6, shrinkA=1, shrinkB=rr * .9))
        ocup.append(caixa)


def evolucao(h):
    """30 dias: barras = volume (R$ MM, eixo da direita), linha = nº de negócios (eixo da esquerda)."""
    fig, ax = plt.subplots(figsize=(9.6, 3.3))
    ax2 = ax.twinx()
    for a in (ax, ax2):
        for s in a.spines.values():
            s.set_visible(False)
        a.tick_params(length=0, labelsize=7.5, colors=CINZA)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color("#d9d9d9")
    ax2.spines["right"].set_visible(True)
    ax2.spines["right"].set_color("#d9d9d9")
    xs = np.arange(len(h))
    ax2.bar(xs, h.volume, width=.55, color=BARRA, zorder=1)
    for i, v in enumerate(h.volume):
        ax2.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=6.5, fontweight="bold", color="#444")
    ax.plot(xs, h.negocios, color=LINHA, lw=2, zorder=5, marker="o", ms=4.5, mfc="white", mec=LINHA, mew=1.4)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.set_ylim(0, max(h.negocios.max() * 2, 10))
    ax2.set_ylim(0, h.volume.max() * 1.6)
    ax.set_xticks(xs, [data_br(d, ano=False) for d in h.index], fontsize=6.8)
    ax.text(-.02, 1.03, "Negócios", transform=ax.transAxes, fontsize=7.5, fontweight="bold", color=TINTA, ha="right")
    ax.text(1.02, 1.03, "R$ MM", transform=ax.transAxes, fontsize=7.5, fontweight="bold", color=TINTA)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BARRA), plt.Line2D([], [], color=LINHA, lw=3)], labels=["Volume (R$ MM)", "Nº de negócios"],
              loc="lower left", bbox_to_anchor=(.02, 1.06), ncol=2, frameon=False, fontsize=7.5, handlelength=1.2)
    return png(fig)


def contra_marcacao(s):
    fig, ax = plt.subplots(figsize=(10.4, 3.4))
    _eixos(ax)
    ax.grid(axis="x", visible=False)
    cor = [AZUL_BARRA if v > 0 else "#a7a9ac" for v in s]
    ax.bar(np.arange(len(s)), s.values, width=.62, color=cor, zorder=3)
    for i, v in enumerate(s.values):
        ax.text(i, v + (1 if v >= 0 else -1), br(v) if abs(v - round(v)) > 1e-9 else f"{v:.0f}", ha="center", va="bottom" if v >= 0 else "top",
                fontsize=6.4, fontweight="bold", color="#333")
    ax.axhline(0, color="#bdbdbd", lw=.8)
    ax.set_xticks(np.arange(len(s)), [data_br(d, ano=False) for d in s.index], fontsize=5.2)
    m = max(abs(s).max() * 1.25, 10)
    ax.set_ylim(-m, m)
    ax.text(-.03, 1.03, "bps", transform=ax.transAxes, fontsize=7.5, fontweight="bold", color=TINTA)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=AZUL_BARRA), plt.Rectangle((0, 0), 1, 1, color="#a7a9ac")],
              labels=["Acima da ANBIMA", "Abaixo da ANBIMA"], loc="lower left", bbox_to_anchor=(.0, 1.02), ncol=2, frameon=False, fontsize=7.5,
              handlelength=1)
    return png(fig)


# ================================================================ HTML (tabelas + estilos inline: o que o Outlook respeita)
F = "font-family:Arial,Helvetica,sans-serif;"


def img(b64):
    return f'<img src="data:image/png;base64,{b64}" width="{LARG - 40}" style="display:block;width:100%;max-width:{LARG - 40}px;height:auto;border:0;">'


def titulo(t, top=22):
    return (f'<div style="{F}font-size:11.5px;font-weight:bold;letter-spacing:1.6px;color:{TINTA};text-transform:uppercase;'
            f'margin:{top}px 0 10px 0;">{t}</div>')


def faixa_secao(t):
    return (f'<div style="{F}background:#b9dfe9;background-image:{AZUL_FAIXA};border-radius:6px;padding:14px 22px;margin:22px 0 14px 0;'
            f'font-size:16px;font-weight:bold;letter-spacing:.8px;color:{TINTA};">{t}</div>')


def faixa_sub(t):
    return (f'<div style="{F}background:{CINZA_CL};border-left:4px solid {AZUL_BORDA};border-radius:3px;padding:10px 16px;margin:10px 0 14px 0;'
            f'font-size:12.5px;font-weight:bold;letter-spacing:1px;color:{TINTA};">{t}</div>')


def kpis(vol, n, ativo, ativo_sub, emissor, emissor_sub):
    def cartao(rot, val, sub, preto=False):
        fundo = f"background:{PRETO};color:white;" if preto else f"background:white;color:{TINTA};border:1px solid {BORDA};"
        cr = "#d6d6d6" if preto else "#8a8a8a"
        tam = 21 if preto else (19 if len(val) < 22 else 12.5)
        s = f'<div style="font-size:9.5px;color:#9a9a9a;margin-top:4px;">{sub}</div>' if sub else ""
        return (f'<td width="25%" style="padding:0 5px;vertical-align:top;"><div style="{F}{fundo}border-radius:8px;padding:22px 10px;text-align:center;'
                f'min-height:62px;"><div style="font-size:10px;letter-spacing:1.4px;color:{cr};margin-bottom:6px;">{rot}</div>'
                f'<div style="font-size:{tam}px;font-weight:bold;line-height:1.25;">{val}</div>{s}</div></td>')
    return ('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:4px 0 14px 0;"><tr>'
            + cartao("VOLUME TOTAL", mm(vol), "", True) + cartao("Nº DE OPERAÇÕES", str(n), "") + cartao("MAIOR ATIVO", ativo, ativo_sub)
            + cartao("MAIOR EMISSOR", emissor, emissor_sub) + "</tr></table>")


def destaques(itens, titulo_box="DESTAQUES"):
    li = "".join(f'<li style="margin:3px 0;">{x}</li>' for x in itens)
    return (f'<div style="{F}border:1px solid {BORDA};border-left:4px solid {AZUL_BORDA};border-radius:6px;padding:14px 22px 12px 22px;'
            f'margin:6px 0 14px 0;background:#fbfbfc;"><div style="font-size:11px;font-weight:bold;letter-spacing:1.6px;color:{TINTA};'
            f'margin-bottom:6px;">{titulo_box}</div><ul style="margin:0;padding-left:16px;font-size:12px;color:#2b2b2b;line-height:1.55;">{li}</ul></div>')


def atip(t):
    return f'<span style="color:{VERMELHO};font-weight:bold;">{t}</span>'


def tabela(cab, linhas, sombra=(), negrito=(), fonte=10.5):
    """cab: [(texto, alinhamento)], linhas: listas de str; sombra: índices de colunas com fundo azulado."""
    th = "".join(f'<th style="{F}background:{PRETO};color:white;font-size:9.5px;letter-spacing:.6px;padding:9px 6px;text-align:{a};'
                 f'white-space:nowrap;text-transform:uppercase;">{c}</th>' for c, a in cab)
    tr = ""
    for ln in linhas:
        tds = ""
        for j, v in enumerate(ln):
            bg = f"background:{SOMBRA_COL};" if j in sombra else ""
            fw = "font-weight:bold;" if j in negrito else ""
            tds += (f'<td style="{F}{bg}{fw}font-size:{fonte}px;color:#333;padding:7px 6px;border-bottom:1px solid #eeeeee;'
                    f'text-align:{cab[j][1]};">{v}</td>')
        tr += f"<tr>{tds}</tr>"
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {BORDA};">'
            f'<tr>{th}</tr>{tr}</table>')


def barras_classe(partes):
    tot = sum(v for _, v in partes) or 1
    cores = {0: PRETO, 2: "#1f4e79"}
    linhas = ""
    for k, (nome, v) in enumerate(partes):
        p = v / tot
        ativo = v > 0
        cor_txt = TINTA if ativo else "#9a9a9a"
        barra = (f'<div style="background:#ececec;border-radius:7px;height:12px;width:100%;">'
                 f'<div style="background:{cores.get(k, "#2b5f8a")};border-radius:7px;height:12px;width:{p * 100:.1f}%;"></div></div>')
        linhas += (f'<tr><td style="{F}font-size:12.5px;font-weight:bold;color:{cor_txt};padding:9px 8px;width:24%;">{nome}</td>'
                   f'<td style="padding:9px 8px;">{barra}</td><td style="{F}font-size:10.5px;font-weight:bold;color:{cor_txt};text-align:right;'
                   f'padding:9px 8px;width:22%;white-space:nowrap;">{mm(v)} • {br(p * 100)}%</td></tr>')
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #f0f0f0;">{linhas}</table>'


# ================================================================ seções
def destaques_debentures(nome, d, dia):
    tot, n = d.volume.sum(), len(d)
    em = d.groupby("empresa").volume.sum().sort_values(ascending=False)
    dur = (d.duration * d.volume).sum() / tot
    top_dur = d.loc[d.duration.idxmax()]
    ind = d.groupby("indexador").volume.sum() / tot * 100
    rot = {"DI": "CDI+", "IPCA": "IPCA+", "%CDI": "%CDI", "PRÉ": "PRÉ"}
    mix = ", ".join(f"<b>{rot.get(k, k)} ({br(v)}%)</b>" for k, v in ind.sort_values(ascending=False).items())
    it = [f"{nome} movimentaram <b>R$ {br(tot)} milhões</b> em {n} negócios, com ticket médio de R$ {br(tot / n)} MM.",
          f"<b>{em.index[0]}</b> liderou o volume por emissor (R$ {br(em.iloc[0])} MM), seguido por {em.index[1]} (R$ {br(em.iloc[1])} MM) "
          f"e {em.index[2]} (R$ {br(em.iloc[2])} MM).",
          f"<b>Duration média ponderada em {br(dur, 2)} anos</b>, com destaque para {top_dur.ticker} ({br(top_dur.duration, 2)} anos).",
          f"Distribuição por indexador: {mix}."]
    return it


def sec_nao_isentas(d, h, dia):
    d = d.sort_values("volume", ascending=False)
    at = d.groupby("ticker").volume.sum().sort_values(ascending=False)
    em = d.groupby("empresa").volume.sum().sort_values(ascending=False)
    it = destaques_debentures("Debêntures Não Isentas", d, dia)
    di = d[d.indexador == "DI"].drop_duplicates("ticker")
    hi, lo = di.nlargest(2, "taxa"), di.nsmallest(2, "taxa")
    it.append(f"{atip('Destaques atípicos:')} <b>maiores spreads:</b> " + " e ".join(f"{r.ticker} a CDI+ {br(r.taxa, 2)}" for r in hi.itertuples())
              + "; <b>menores spreads:</b> " + " e ".join(f"{r.ticker} a CDI+ {br(r.taxa, 2)}" for r in lo.itertuples()) + ".")
    x = di.assign(dif=(di.taxa - di.taxa_anbima) * 100)
    ac, ab = x.nlargest(2, "dif"), x.nsmallest(2, "dif")
    f_ = lambda r: f"{r.ticker} a {br(r.taxa, 2)} vs ANBIMA {br(r.taxa_anbima, 2)} (<b>{r.dif:+.0f} bps</b>; R$ {br(r.volume)} MM)".replace("-", "−")
    it.append(f"{atip('Acima da ANBIMA:')} " + " e ".join(f_(r) for r in ac.itertuples()) + ".")
    it.append(f"{atip('Abaixo da ANBIMA:')} " + " e ".join(f_(r) for r in ab.itertuples()) + ".")
    cab = [("Emissor", "left"), ("Vencimento", "center"), ("Duration", "center"), ("Volume (milhões)", "center"), ("Taxa negócio", "center"),
           ("Indexador", "center"), ("Spread over", "center"), ("Taxa ANBIMA", "center"), ("Empresa", "center"), ("Deb. incent.", "center")]
    ln = [[r.ticker, data_br(r.vencimento), br(r.duration, 2), f"{r.volume:.0f}", br(r.taxa, 2), r.indexador,
           "—" if np.isnan(r.spread_over) else f"{r.spread_over:.0f}", br(r.taxa_anbima), r.empresa, r.incentivada] for r in d.itertuples()]
    bol = bolhas(d[d.indexador == "DI"], "duration", "taxa", "ticker", "Taxa (CDI+ %a.a.)",
                 "Duration (anos) — ativos que respondem por ~80% do volume do período")
    return (faixa_sub("DEBÊNTURES NÃO ISENTAS")
            + kpis(d.volume.sum(), len(d), at.index[0], mm(at.iloc[0]), em.index[0], mm(em.iloc[0]))
            + destaques(it)
            + titulo(f"Maiores trades — Não isentas / CDI+ • {dia:%d/%m/%Y} (X = duration • Y = taxa negócio • bolha = volume)") + img(bol)
            + titulo("Evolução 30 dias — volume e negócios balcão • Debêntures não isentas") + img(evolucao(h))
            + titulo("Todos os trades — Debêntures não isentas") + tabela(cab, ln, sombra=(4,), negrito=(0, 4)))


def sec_isentas(d, h, contra, dia):
    d = d.sort_values("volume", ascending=False)
    at = d.groupby("ticker").volume.sum().sort_values(ascending=False)
    em = d.groupby("empresa").volume.sum().sort_values(ascending=False)
    it = destaques_debentures("Debêntures Isentas", d, dia)
    cab = [("Emissor", "left"), ("Vencimento", "center"), ("Duration", "center"), ("Volume (milhões)", "center"), ("Taxa negócio", "center"),
           ("Taxa ANBIMA", "center"), ("Ref.", "center"), ("Spread over", "center"), ("Indexador", "center"), ("Empresa", "center"),
           ("Deb. incent.", "center")]
    ln = [[r.ticker, data_br(r.vencimento), br(r.duration, 2), f"{r.volume:.0f}", br(r.taxa, 2), f"{r.taxa_anbima:.0f}", r.ref,
           f"{r.spread_over:.0f}", r.indexador, r.empresa, r.incentivada] for r in d.itertuples()]
    bol = bolhas(d[d.indexador == "IPCA"], "duration", "spread_over", "ticker", "Spread Over (bps)",
                 "Duration (anos) — ativos que respondem por ~80% do volume do período", casas=0, yfmt=lambda v: br(v, 2))
    hoje = contra.iloc[-1]
    dif = d.spread_over - d.taxa_anbima
    txt = (f"Em {dia:%d/%m}, a mediana dos negócios ficou <b>{br(abs(hoje))} bps {'acima' if hoje >= 0 else 'abaixo'} da marcação</b> ANBIMA. "
           f"<b>{(dif > 0).mean() * 100:.0f}%</b> dos negócios saíram acima da marcação e {((dif > 0) & (dif <= 5)).mean() * 100:.0f}% até 5 bps acima dela.")
    return (faixa_sub("DEBÊNTURES ISENTAS")
            + kpis(d.volume.sum(), len(d), at.index[0], mm(at.iloc[0]), em.index[0], mm(em.iloc[0]))
            + destaques(it)
            + titulo(f"Maiores trades — Isentas / IPCA+ • {dia:%d/%m/%Y} (X = duration • Y = spread over • bolha = volume)") + img(bol)
            + titulo("Evolução 30 dias — volume e negócios balcão • Debêntures isentas") + img(evolucao(h))
            + titulo("Todos os trades — Debêntures isentas") + tabela(cab, ln, sombra=(4, 7), negrito=(0, 4, 7))
            + titulo(f"Secundário de incentivadas: negócios contra a marcação • até {dia:%d/%m/%Y} (spread over menos taxa ANBIMA, bps, mediana do dia)")
            + destaques([txt], "NEGÓCIOS CONTRA A MARCAÇÃO") + img(contra_marcacao(contra)))


def sec_bancarios(d, h, dia):
    d = d.sort_values("volume", ascending=False).copy()
    d["spread_eq"] = np.where(d.indexador == "%CDI", (d.taxa / 100 - 1) * CDI_AA, d.taxa)
    d["papel"] = d.ativo + " " + d.emissor
    d["chave"] = d.papel + " " + d.vencimento.map(mes_ano)
    tot, n = d.volume.sum(), len(d)
    at = d.groupby("chave").volume.sum().sort_values(ascending=False)
    em = d.groupby("emissor").volume.sum().sort_values(ascending=False)
    ti = d.groupby("ativo").volume.sum().sort_values(ascending=False)
    pr = (d.prazo * d.volume).sum() / tot
    pos = d[d.indexador != "PRÉ"]
    lng = d.loc[d.prazo.idxmax()]
    it = [f"Bancários movimentaram <b>R$ {br(tot)} milhões</b> em {n} operações, com ticket médio de R$ {br(tot / n)} MM.",
          f"<b>{em.index[0]} liderou o volume</b> (R$ {br(em.iloc[0])} MM), à frente de {em.index[1]} (R$ {br(em.iloc[1])} MM) e {em.index[2]} (R$ {br(em.iloc[2])} MM).",
          f"Fluxo concentrado em <b>{ti.index[0]} (R$ {br(ti.iloc[0])} MM, {ti.iloc[0] / tot * 100:.0f}% do total)</b>, seguido por {ti.index[1]} (R$ {br(ti.iloc[1])} MM).",
          f"<b>Prazo médio ponderado de {br(pr, 2)} ano(s)</b> e spread médio de <b>CDI+{br((pos.spread_eq * pos.volume).sum() / pos.volume.sum(), 2)}%</b> "
          f"nos pós-fixados, que responderam por {br(pos.volume.sum() / tot * 100)}% do volume.",
          f"{atip('Destaques atípicos:')} <b>maior prazo:</b> {lng.papel} ({mes_ano(lng.vencimento)}), com {br(lng.prazo, 2)} anos."]
    g = d.assign(rot=d.papel)
    bol = bolhas(g.assign(ticker=g.rot + " " + g.vencimento.map(mes_ano)).rename(columns={"spread_eq": "spr"}), "prazo", "spr", "ticker",
                 "Spread equivalente (% a.a. sobre o CDI)",
                 f"Prazo (anos) — cada bolha = um papel (emissor + tipo + vencimento); papéis %CDI convertidos em spread equivalente com CDI de {br(CDI_AA, 2)}% a.a.",
                 texto=lambda k: k.rsplit(" ", 1)[0], maximo=11)
    cab = [("Ativo", "center"), ("Emissor", "center"), ("Vencimento", "center"), ("Volume (milhões)", "center"), ("Taxa negócio", "center"),
           ("Indexador", "center")]
    ln = [[r.ativo, r.emissor, mes_ano(r.vencimento), br(r.volume), br(r.taxa, 2), r.indexador] for r in d.itertuples()]
    return (faixa_secao("BANCÁRIOS")
            + kpis(tot, n, at.index[0], mm(at.iloc[0]), em.index[0], mm(em.iloc[0]))
            + destaques(it)
            + titulo(f"Maiores trades — Bancários • {dia:%d/%m/%Y} (X = prazo • Y = spread • bolha = volume)") + img(bol)
            + titulo("Evolução 30 dias — volume e negócios • Bancários") + img(evolucao(h))
            + titulo("Todos os trades") + tabela(cab, ln, sombra=(4,), negrito=(0,)))


def sec_estruturados(d, h, dia):
    tot, n = d.volume.sum(), len(d)
    top = d.loc[d.volume.idxmax()]
    cls = d.groupby("ativo").volume.sum()
    partes = [(c, float(cls.get(k, 0))) for c, k in (("CRA", "CRA"), ("CRI", "CRI"), ("FIDC", "FIDC"), ("Debêntures Estruturadas", "DEB"))]
    dom = cls.idxmax()
    outros = "; ".join(f"{k} respondeu por {br(v / tot * 100)}% ({mm(v)})" for k, v in cls.items() if k != dom)
    lng = d.loc[d.vencimento.idxmax()]
    it = [f"Estruturados movimentaram <b>R$ {br(tot)} milhões</b> em {n} negócio(s).",
          f"<b>{dom} dominou o fluxo, com {br(cls[dom] / tot * 100)}% do volume ({mm(cls[dom])})</b>; {outros}.",
          f"<b>{top.emissor} liderou</b> ({mm(top.volume)} a {top.indexador} {top.taxa}).",
          f"{atip('Destaques atípicos:')} <b>maior prazo:</b> {lng.ativo} {lng.emissor}, vencimento em {mes_ano(lng.vencimento)}."]
    cab = [("Data", "center"), ("Ativo", "center"), ("Código", "left"), ("Emissor", "center"), ("Vencimento", "center"), ("Volume (R$ MM)", "center"),
           ("Taxa negócio", "center"), ("Indexador", "center")]
    ln = [[f"{r.data:%d/%m/%Y}", r.ativo, r.codigo, r.emissor, mes_ano(r.vencimento), br(r.volume, 2), r.taxa, r.indexador] for r in d.itertuples()]
    return (faixa_secao("ESTRUTURADOS")
            + kpis(tot, n, f"{top.ativo} {top.emissor}", f"{mm(top.volume)} • {top.indexador} {top.taxa}", top.emissor, mm(top.volume))
            + destaques(it)
            + titulo("Distribuição por classe") + barras_classe(partes)
            + titulo("Todos os trades") + tabela(cab, ln, sombra=(6,), negrito=(0, 6))
            + titulo("Evolução 30 dias — volume e negócios • Estruturados") + img(evolucao(h)))


def monta_html(dia, D):
    deb = D["nao"].volume.sum() + D["isen"].volume.sum()
    banc, estr = D["banc"].volume.sum(), D["estr"].volume.sum()
    n = sum(len(D[k]) for k in ("nao", "isen", "banc", "estr"))
    cab = (f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
           f'<td width="200" style="padding:6px 0 14px 14px;"><table cellpadding="0" cellspacing="0"><tr>'
           f'<td style="{F}background:{PRETO};color:white;font-weight:bold;font-size:22px;border-radius:9px;padding:14px 10px;">itaú</td>'
           f'<td style="{F}font-size:22px;color:#333;padding-left:14px;">Asset</td></tr></table></td>'
           f'<td style="{F}font-size:22px;font-weight:bold;color:{TINTA};text-align:center;padding-right:200px;">Resumo Trading Crédito | {dia:%d/%m/%Y}</td>'
           f'</tr></table>'
           f'<div style="{F}background:{PRETO};color:white;border-radius:6px;padding:12px 16px;text-align:center;font-size:12px;">'
           f'Volume consolidado negociado no dia: <b>R$ {br(deb + banc + estr)} milhões</b> em {n} operações — Debêntures {mm(deb)} • '
           f'Bancários {mm(banc)} • Estruturados {mm(estr)}</div>')
    rod = (f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:34px;"><tr>'
           f'<td style="{F}font-size:12.5px;color:#555;line-height:1.6;"><b style="color:{TINTA};">{ASSINATURA[0]}</b><br>{ASSINATURA[1]}<br>{ASSINATURA[2]}</td>'
           f'<td style="{F}font-size:10px;color:#9a9a9a;text-align:right;vertical-align:middle;">Relatório gerado automaticamente a partir das bases de trading.</td>'
           f'</tr></table><div style="{F}background:{PRETO};color:white;font-size:10px;padding:6px 14px;margin-top:16px;">Corporativo | Interno</div>')
    corpo = (cab + faixa_secao("DEBÊNTURES") + sec_nao_isentas(D["nao"], D["hist"]["nao"], dia)
             + sec_isentas(D["isen"], D["hist"]["isen"], D["contra"], dia) + sec_bancarios(D["banc"], D["hist"]["banc"], dia)
             + sec_estruturados(D["estr"], D["hist"]["estr"], dia) + rod)
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Resumo Trading Crédito {dia:%d/%m/%Y}</title>'
            f'<style>@page{{size:A4;margin:10mm}} body{{margin:0;background:#ffffff}} tr{{page-break-inside:avoid}} img{{page-break-inside:avoid}}</style>'
            f'</head><body><table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">'
            f'<table width="{LARG}" cellpadding="0" cellspacing="0" style="width:{LARG}px;"><tr><td style="padding:18px 20px;">{corpo}</td></tr></table>'
            f'</td></tr></table></body></html>')


def imprime_pdf(html, pdf):
    nav = next((p for p in (shutil.which("msedge"), shutil.which("chrome"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                if p and Path(p).exists()), None)
    if nav is None:
        print("Edge/Chrome não encontrado: PDF não gerado.")
        return
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as perfil:
        subprocess.run([nav, "--headless", "--disable-gpu", f"--user-data-dir={perfil}", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", html.as_uri()], check=False, capture_output=True, timeout=180)
        for _ in range(120):                                       # o Edge às vezes devolve antes de terminar de gravar o PDF
            if pdf.exists() and pdf.stat().st_size > 0:
                break
            time.sleep(.5)
        time.sleep(1)


if __name__ == "__main__":
    dia = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else pd.Timestamp.today().normalize()
    PASTA.mkdir(exist_ok=True)
    html = PASTA / f"resumo_trading_credito_{dia:%Y%m%d}.html"
    html.write_text(monta_html(dia, dados_ficticios(dia)), encoding="utf-8")
    imprime_pdf(html, PASTA / f"resumo_trading_credito_{dia:%Y%m%d}.pdf")
    print(html)
