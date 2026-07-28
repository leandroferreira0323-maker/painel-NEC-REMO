"""
Robô de extração — Painel de Serviços Comerciais (WmWeb / REMO Engenharia)

O que ele faz:
1. Loga no sistema wmweb.remo.com.br usando usuário e senha vindos de
   variáveis de ambiente (nunca escritos neste arquivo).
2. Abre a tela do Painel para cada Unidade Operacional (UO 67 e UO 271).
3. Lê os dados já carregados na grid (DevExtreme) da página — o mesmo
   dado que aparece na tela, só que em formato estruturado.
4. Converte para o formato que o painel HTML já espera (mesmos nomes de
   coluna que a planilha original, então o dashboard não precisa mudar).
5. Salva tudo em data.json, na raiz do repositório.

Variáveis de ambiente necessárias (configuradas como "Secrets" no GitHub,
nunca digitadas aqui):
    WMWEB_LOGIN   -> seu usuário de login no wmweb
    WMWEB_SENHA   -> sua senha

Uso local (opcional, para testar na sua máquina antes de subir pro GitHub):
    pip install playwright
    playwright install chromium
    WMWEB_LOGIN="seu.usuario" WMWEB_SENHA="sua_senha" python scraper.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright

BASE_URL = "https://wmweb.remo.com.br"
LOGIN_URL = f"{BASE_URL}/Account/Login"
PAINEL_URL = f"{BASE_URL}/ServicosComerciais/Painel"

# Unidades a consultar: código -> rótulo usado no painel
UNIDADES = {
    67: "UO 67 - Passos",
    271: "UO 271 - Bom Despacho",
}

# Fuso horário de Brasília (UTC-3), usado para montar a data de hoje
BR_TZ = timezone(timedelta(hours=-3))


def hoje_br() -> str:
    return datetime.now(BR_TZ).strftime("%Y-%m-%d")


def login(page):
    login_user = os.environ.get("WMWEB_LOGIN")
    login_pass = os.environ.get("WMWEB_SENHA")
    if not login_user or not login_pass:
        print("ERRO: defina as variáveis de ambiente WMWEB_LOGIN e WMWEB_SENHA.", file=sys.stderr)
        sys.exit(1)

    page.goto(LOGIN_URL, wait_until="networkidle")
    page.fill("#Login", login_user)
    page.fill("#Senha", login_pass)
    page.click("button[type=submit]")
    # Espera a navegação pós-login terminar
    page.wait_for_load_state("networkidle")

    if "/Account/Login" in page.url:
        print("ERRO: login não foi aceito. Verifique usuário/senha nos Secrets.", file=sys.stderr)
        sys.exit(1)


def extrair_uo(page, cod_uo: int, data_painel: str) -> list[dict]:
    url = f"{PAINEL_URL}?codUo={cod_uo}&dataPainel={data_painel}"
    page.goto(url, wait_until="networkidle")

    # Espera a grid principal (#tabelaGrid) do DevExtreme terminar de montar
    page.wait_for_function(
        "() => window.jQuery && $('#tabelaGrid').data('dxDataGrid') "
        "&& $('#tabelaGrid').dxDataGrid('instance').getDataSource().items().length >= 0",
        timeout=30000,
    )
    # Pequena espera extra para garantir que todas as linhas carregaram
    page.wait_for_timeout(1500)

    items = page.evaluate(
        "() => $('#tabelaGrid').dxDataGrid('instance').getDataSource().items()"
    )
    return items or []


def montar_data_hora(data_iso: str | None, hora_formatada: str | None) -> str:
    """Combina a data (DATA, formato ISO) com a hora local já formatada
    (ex.: '05:46') retornada pela própria página, produzindo
    'YYYY-MM-DD HH:MM:00', no mesmo formato que o painel HTML espera."""
    if not data_iso or not hora_formatada:
        return ""
    data_parte = data_iso[:10]  # 'YYYY-MM-DD'
    return f"{data_parte} {hora_formatada}:00"


def converter_para_schema_painel(item: dict, unidade_label: str) -> dict:
    """Traduz os campos crus da API/grid para os nomes de coluna que o
    dashboard HTML já usa (os mesmos da planilha original), incluindo o
    campo real de Improdutivos, que antes tínhamos que estimar."""
    return {
        "Unidade": unidade_label,
        "Supervisor": item.get("SUPERVISOR") or "",
        "Controlador": item.get("NOME_CONTROLADOR") or "",
        "Classificação": item.get("CLASSIFICACAO") or "",
        "Situação": item.get("SITUACAO") or "",
        "Frota": item.get("NUM_EQUIPE") or item.get("PLACA") or "",
        "Início Jornada": montar_data_hora(item.get("DATA"), item.get("INICIO_JORNADA_FORMATADO")),
        "Designados": item.get("DESIGNADOS") or 0,
        "Executados": item.get("EXECUTADOS") or 0,
        "Produtivos": item.get("PRODUTIVOS") or 0,
        "Improdutivos": item.get("IMPRODUTIVOS"),  # campo real, vindo do sistema
        "Meta": item.get("META") or 0,
        "Us Prev": item.get("US_PREV") or 0,
        "Produção": item.get("PRODUCAO") or 0,
        "% Produção": item.get("PERC_PRODUCAO") or "",
    }


def main():
    data_painel = os.environ.get("DATA_PAINEL", hoje_br())
    resultado = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        login(page)

        for cod_uo, label in UNIDADES.items():
            print(f"Extraindo {label} (codUo={cod_uo}, data={data_painel})...")
            items = extrair_uo(page, cod_uo, data_painel)
            print(f"  -> {len(items)} equipes encontradas.")
            for item in items:
                resultado.append(converter_para_schema_painel(item, label))

        browser.close()

    saida = {
        "atualizado_em": datetime.now(BR_TZ).isoformat(),
        "data_painel": data_painel,
        "equipes": resultado,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(resultado)} equipes salvas em data.json")


if __name__ == "__main__":
    main()
