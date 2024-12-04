# scrapers/capes.py
import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin
from .config import KEYWORDS  # Importando as palavras-chave globais
import re
from datetime import datetime
from database import SessionLocal, Edital  # Import ORM

def obter_subpagina_resultados_capes(url_principal, selected_year):
    """
    Determina a subpágina de resultados da CAPES com base no ano selecionado.

    Args:
        url_principal (str): URL principal da CAPES.
        selected_year (int): Ano dos resultados a serem obtidos.

    Returns:
        str or None: URL da subpágina de resultados ou None se não encontrada.
    """
    try:
        logging.info(f"Obtendo subpágina de resultados da CAPES para o ano {selected_year} a partir de: {url_principal}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/90.0.4430.93 Safari/537.36'
        }
        response = requests.get(url_principal, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Encontre todos os links cuja URL contenha 'resultados-<selected_year>'
        subpagina_links = []
        for a_tag in soup.find_all('a', href=True, string=True):
            href = a_tag['href'].lower()
            if f"resultados-{selected_year}" in href:
                subpagina_links.append(urljoin(url_principal, a_tag['href']))
                logging.info(f"Subpágina de resultados encontrada: {href}")

        if not subpagina_links:
            # Tentar buscar na seção "resultados anteriores"
            resultados_anteriores_link = soup.find('a', href=True, string=lambda text: text and 'resultados anteriores' in text.lower())
            if resultados_anteriores_link:
                resultados_anteriores_url = urljoin(url_principal, resultados_anteriores_link['href'])
                logging.info(f"Buscando em 'resultados anteriores': {resultados_anteriores_url}")
                response_anteriores = requests.get(resultados_anteriores_url, headers=headers, timeout=10)
                response_anteriores.raise_for_status()
                soup_anteriores = BeautifulSoup(response_anteriores.text, 'html.parser')
                for a_tag in soup_anteriores.find_all('a', href=True, string=True):
                    href = a_tag['href'].lower()
                    if f"resultados-{selected_year}" in href:
                        subpagina_links.append(urljoin(url_principal, a_tag['href']))
                        logging.info(f"Subpágina de resultados encontrada em 'resultados anteriores': {href}")

        if not subpagina_links:
            logging.warning(f"Nenhuma subpágina de resultados encontrada para o ano {selected_year} na página principal da CAPES.")
            return None

        # Retorna a primeira subpágina encontrada
        return subpagina_links[0]

    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao acessar a página principal da CAPES: {e}")
        return None

def extrair_dados_capes(url_principal, selected_year):
    """
    Extrai dados de editais da CAPES com base no ano selecionado.
    Insere os dados diretamente no banco de dados.
    """
    dados = []
    subpagina = obter_subpagina_resultados_capes(url_principal, selected_year)
    if not subpagina:
        logging.warning("Nenhuma subpágina de resultados encontrada para a CAPES.")
        return dados

    logging.info(f"Extraindo dados da subpágina CAPES: {subpagina}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/90.0.4430.93 Safari/537.36'
        }
        session = requests.Session()
        response = session.get(subpagina, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Encontrar todos os links dentro de <li> que contenham 'a' com href
        eventos = soup.find_all('li')
        logging.info(f"Encontrados {len(eventos)} eventos na subpágina CAPES.")

        # Abrir sessão de banco de dados
        db = SessionLocal()

        for evento in eventos:
            link_tag = evento.find('a', href=True)
            if link_tag:
                titulo_completo = link_tag.get_text(separator=' ', strip=True)
                href = link_tag['href']
                link_absoluto = urljoin(url_principal, href)

                # Extrair a data de publicação do texto do link
                # Exemplo de texto:
                # "Resultado final do Edital Nº 10/2023 - Programa XYZ, formato, pdf, 59kb - em 28/12/2023"
                data_pub_match = re.search(r'- em (\d{2})/(\d{2})/(\d{4})$', titulo_completo)
                if data_pub_match:
                    dia, mes, ano = data_pub_match.groups()
                    try:
                        data_pub = datetime.strptime(f"{dia}/{mes}/{ano}", '%d/%m/%Y')
                    except ValueError:
                        logging.error(f"Formato de data inválido: {dia}/{mes}/{ano} no evento: {titulo_completo}")
                        continue

                    if data_pub.year != selected_year:
                        logging.info(f"Evento '{titulo_completo}' publicado em {data_pub.year}, não corresponde ao ano selecionado.")
                        continue  # Ignorar este evento
                else:
                    logging.warning(f"Data de publicação não encontrada no texto do link: {titulo_completo}")
                    continue  # Ignorar se a data de publicação não for encontrada

                # Verificar se o texto do edital contém alguma das palavras-chave
                if not contains_keyword(titulo_completo):
                    logging.info(f"Evento '{titulo_completo}' não contém nenhuma das palavras-chave definidas.")
                    continue  # Ignorar este evento

                # Verificar se o edital já existe no banco de dados
                edital_existente = db.query(Edital).filter(Edital.link == link_absoluto).first()
                if not edital_existente:
                    edital = Edital(
                        titulo=titulo_completo,
                        link=link_absoluto,
                        origem='CAPES',
                        ano=selected_year
                    )
                    db.add(edital)
                    db.commit()
                    logging.info(f"Adicionado edital da CAPES: {titulo_completo} - {link_absoluto}")
                else:
                    logging.info(f"Edital já existe no banco de dados: {titulo_completo} - {link_absoluto}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao acessar {subpagina}: {e}")
    finally:
        db.close()

    return dados

def contains_keyword(text):
    """
    Verifica se o texto contém alguma das palavras-chave definidas.

    Args:
        text (str): Texto a ser verificado.

    Returns:
        bool: True se alguma palavra-chave for encontrada, False caso contrário.
    """
    text = text.lower()
    return any(keyword in text for keyword in KEYWORDS)

def parse_date(date_str):
    """
    Converte uma string de data no formato DD/MM/YYYY para um objeto datetime.

    Args:
        date_str (str): String da data.

    Returns:
        datetime: Objeto datetime correspondente.
    """
    try:
        return datetime.strptime(date_str, '%d/%m/%Y')
    except ValueError:
        logging.error(f"Formato de data inválido: {date_str}")
        return datetime.min  # Retorna uma data mínima em caso de erro
