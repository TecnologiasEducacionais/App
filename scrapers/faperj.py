# scrapers/faperj.py
import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin
from .config import KEYWORDS  # Importando as palavras-chave globais
from database import SessionLocal, Edital  # Import ORM

def extrair_dados_faperj(url_principal, selected_year):
    """
    Extrai dados de editais da FAPERJ com base no ano selecionado.
    Insere os dados diretamente no banco de dados.
    """
    dados = []
    try:
        logging.info(f"Extraindo dados da FAPERJ: {url_principal}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/90.0.4430.93 Safari/537.36'
        }
        response = requests.get(url_principal, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Encontrar todos os links que contenham as palavras-chave e o ano determinado
        links_encontrados = 0
        links_adicionados = 0

        # Abrir sessão de banco de dados
        db = SessionLocal()

        for a_tag in soup.find_all('a', href=True, string=True):
            texto_link = a_tag.string.lower()
            if any(keyword in texto_link for keyword in KEYWORDS) and str(selected_year) in texto_link:
                links_encontrados += 1
                titulo = a_tag.get_text(strip=True)
                link_absoluto = urljoin(url_principal, a_tag['href'])

                # Verificar se o edital já existe no banco de dados
                edital_existente = db.query(Edital).filter(Edital.link == link_absoluto).first()
                if not edital_existente:
                    edital = Edital(
                        titulo=titulo,
                        link=link_absoluto,
                        origem='FAPERJ',
                        ano=selected_year  # Preenche com o ano selecionado
                    )
                    db.add(edital)
                    db.commit()
                    links_adicionados += 1
                    logging.info(f"Adicionado edital da FAPERJ: {titulo} - {link_absoluto}")
                else:
                    logging.info(f"Edital já existe no banco de dados: {titulo} - {link_absoluto}")

        logging.info(f"Total de links encontrados na FAPERJ contendo palavras-chave e '{selected_year}': {links_encontrados}")
        logging.info(f"Total de editais adicionados da FAPERJ: {links_adicionados}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao acessar {url_principal}: {e}")
    finally:
        db.close()
    return dados
