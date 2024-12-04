# scrapers/finep.py
import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin
from .config import KEYWORDS
import re
from datetime import datetime
import time
from database import SessionLocal, Edital  # Import ORM

def extrair_dados_finep(url_principal, selected_year):
    """
    Extrai dados de editais da FINEP com base no ano selecionado, percorrendo todas as páginas de resultados.
    Insere os dados diretamente no banco de dados.
    """
    try:
        logging.info(f"Iniciando extração de dados da FINEP para o ano {selected_year} a partir de: {url_principal}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/90.0.4430.93 Safari/537.36'
        }
        session = requests.Session()
        response = session.get(url_principal, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Identificar a seção de paginação para determinar o número total de páginas
        pagination_div = soup.find('div', class_='pagination')
        if not pagination_div:
            logging.warning("Div 'pagination' não encontrada. Supondo que há apenas uma página.")
            total_pages = 1
        else:
            # Extrair o número total de páginas a partir do texto 'Pagina 1 de 13'
            counter_p = pagination_div.find('p', class_='counter')
            if counter_p:
                counter_text = counter_p.get_text(strip=True)
                match = re.search(r'Pagina\s+\d+\s+de\s+(\d+)', counter_text, re.IGNORECASE)
                if match:
                    total_pages = int(match.group(1))
                else:
                    # Caso não encontre o padrão esperado, contar o número de links de página
                    page_links = pagination_div.find_all('a', class_='pagenav')
                    # Excluir 'Inicio', 'Fim', 'Próx' e 'Ant' se presentes
                    page_numbers = [link for link in page_links if link.get_text().isdigit()]
                    total_pages = len(page_numbers)
            else:
                logging.warning("Texto 'Pagina x de y' não encontrado. Supondo que há apenas uma página.")
                total_pages = 1

        logging.info(f"Total de páginas a serem raspadas na FINEP: {total_pages}")

        # Abrir sessão de banco de dados
        db = SessionLocal()

        # Iterar por todas as páginas
        for page in range(1, total_pages + 1):
            if page == 1:
                page_url = url_principal
            else:
                # Construir a URL da página com base no parâmetro 'start'
                start = (page - 1) * 10  # Supondo que cada página incrementa 'start' em 10
                if '?' in url_principal:
                    page_url = f"{url_principal}&start={start}"
                else:
                    page_url = f"{url_principal}?start={start}"
            
            logging.info(f"Raspando página {page} de {total_pages}: {page_url}")
            try:
                response_page = session.get(page_url, headers=headers, timeout=10)
                response_page.raise_for_status()
                soup_page = BeautifulSoup(response_page.text, 'html.parser')

                # Encontrar todos os títulos de eventos dentro de <h3>
                h3_tags = soup_page.find_all('h3')
                logging.info(f"Encontrados {len(h3_tags)} eventos na página {page}.")

                for h3 in h3_tags:
                    titulo = h3.get_text(strip=True)
                    link_tag = h3.find('a', href=True)
                    if link_tag:
                        evento_url = urljoin(url_principal, link_tag['href'])
                        logging.info(f"Acessando detalhes do evento: {titulo} - {evento_url}")
                        try:
                            response_evento = session.get(evento_url, headers=headers, timeout=10)
                            response_evento.raise_for_status()
                            soup_evento = BeautifulSoup(response_evento.text, 'html.parser')

                            # Encontrar a tabela "document"
                            tabela_documentos = soup_evento.find('table', class_='document')
                            if not tabela_documentos:
                                logging.warning(f"Tabela 'document' não encontrada para o evento: {titulo}")
                                continue  # Ignorar se a tabela não for encontrada

                            # Iterar sobre cada linha da tabela
                            tbody = tabela_documentos.find('tbody')
                            if not tbody:
                                logging.warning(f"Tag <tbody> não encontrada na tabela 'document' para o evento: {titulo}")
                                continue

                            tr_tags = tbody.find_all('tr')
                            logging.info(f"Encontrados {len(tr_tags)} documentos na tabela para o evento: {titulo}")

                            for tr in tr_tags:
                                td_tags = tr.find_all('td')
                                if len(td_tags) >= 3:
                                    # Extrair a data de publicação da primeira coluna
                                    data_pub_str = td_tags[0].get_text(strip=True)
                                    try:
                                        data_pub = datetime.strptime(data_pub_str, '%d/%m/%Y')
                                    except ValueError:
                                        logging.error(f"Formato de data inválido: {data_pub_str} no evento: {titulo}")
                                        continue  # Ignorar este documento se a data for inválida

                                    if data_pub.year != selected_year:
                                        logging.info(f"Documento '{titulo}' publicado em {data_pub.year}, não corresponde ao ano selecionado.")
                                        continue  # Ignorar este documento

                                    # Extrair o link do PDF na coluna "Formatos proprietários" (3ª coluna, índice 2)
                                    formatos_proprietarios_td = td_tags[2]
                                    link_pdf_tag = formatos_proprietarios_td.find('a', href=True)
                                    if link_pdf_tag:
                                        pdf_href = link_pdf_tag['href']
                                        pdf_url = urljoin(url_principal, pdf_href)
                                        
                                        # Verificar se o link termina com '.pdf'
                                        if pdf_url.lower().endswith('.pdf'):
                                            # Verificar se o nome do documento contém alguma das palavras-chave
                                            nome_documento = td_tags[1].get_text(strip=True).lower()
                                            if any(keyword in nome_documento for keyword in KEYWORDS):
                                                # Verificar se o edital já existe no banco de dados
                                                edital_existente = db.query(Edital).filter(Edital.link == pdf_url).first()
                                                if not edital_existente:
                                                    edital = Edital(
                                                        titulo=titulo,
                                                        link=pdf_url,
                                                        origem='FINEP',
                                                        ano=selected_year
                                                    )
                                                    db.add(edital)
                                                    db.commit()
                                                    logging.info(f"Adicionado edital da FINEP: {titulo} - {pdf_url}")
                                                else:
                                                    logging.info(f"Edital já existe no banco de dados: {titulo} - {pdf_url}")
                                        else:
                                            logging.warning(f"Link não é um PDF: {pdf_url} para o evento: {titulo}")
                                    else:
                                        logging.warning(f"Link do PDF não encontrado na coluna 'Formatos proprietários' para o evento: {titulo}")

                        except requests.exceptions.RequestException as e:
                            logging.error(f"Erro ao acessar detalhes do evento '{titulo}': {e}")

            except requests.exceptions.RequestException as e:
                logging.error(f"Erro ao acessar a página {page_url}: {e}")

            # Adicionar um pequeno atraso entre as requisições para evitar sobrecarga no servidor
            time.sleep(1)

    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao acessar {url_principal}: {e}")
    finally:
        db.close()
    return
