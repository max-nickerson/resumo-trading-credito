# Resumo Trading Crédito — layout do e-mail

Só o visual, com **dados fictícios**: gera o e-mail diário de trading de crédito (HTML para colar no Outlook) e o PDF igual.

```bash
pip install pandas numpy matplotlib
python resumo_trading_credito.py 2026-10-08     # sem data = hoje
```

Saída em `saida/`: `resumo_trading_credito_AAAAMMDD.html` e `.pdf` (o PDF usa o Edge/Chrome em modo headless).

Seções: cabeçalho e volume consolidado; Debêntures não isentas e isentas (cartões, destaques, bolhas, evolução de 30 dias,
todos os trades e, nas isentas, negócios contra a marcação); Bancários; Estruturados (com distribuição por classe).

Para ligar nos dados reais, troque só `dados_ficticios(dia)` por uma função que devolva o mesmo dicionário.
