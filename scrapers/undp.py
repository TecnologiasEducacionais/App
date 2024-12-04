# scrapers/undp.py
import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin
from datetime import datetime
import time
from .config import KEYWORDS  # Importando as palavras-chave do config.py
from database import SessionLocal, Edital  # Import ORM

def extrair_dados_undp(url_principal, selected_year):
    """
    Extrai dados de publicações da UNDP Brasil com base no ano selecionado, percorrendo todas as páginas de resultados.
    Insere os dados diretamente no banco de dados.
    """
    dados = []
    try:
        logging.info(f"Iniciando extração de dados da UNDP Brasil para o ano {selected_year} a partir de: {url_principal}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/90.0.4430.93 Safari/537.36'
        }
        session = requests.Session()
        page = 1
        total_results = None
        loaded_results = 0

        # Abrir sessão de banco de dados
        db = SessionLocal()

        while True:
            # Construir a URL da página
            if '?' in url_principal:
                page_url = f"{url_principal}&page={page}"
            else:
                page_url = f"{url_principal}?page={page}"
            
            logging.info(f"Raspando página {page}: {page_url}")
            response = session.get(page_url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Encontrar todos os cartões de publicação
            publication_cards = soup.find_all('div', class_='content-card')
            logging.info(f"Encontrados {len(publication_cards)} publicações na página {page}.")

            if not publication_cards:
                logging.info("Nenhuma publicação encontrada na página atual. Encerrando raspagem.")
                break

            for card in publication_cards:
                # Extrair o título
                titulo_tag = card.find('h5')
                if not titulo_tag:
                    logging.warning("Título não encontrado. Pulando publicação.")
                    continue
                titulo = titulo_tag.get_text(strip=True)

                # Verificar se o título contém alguma das palavras-chave
                if not any(keyword.lower() in titulo.lower() for keyword in KEYWORDS):
                    logging.info(f"Publicação '{titulo}' não contém nenhuma das palavras-chave. Ignorando.")
                    continue

                # Extrair o link da publicação
                link_tag = card.find('a', href=True)
                if not link_tag:
                    logging.warning(f"Link da publicação '{titulo}' não encontrado. Pulando publicação.")
                    continue
                publicacao_url = urljoin(url_principal, link_tag['href'])

                # Acessar a página da publicação para obter o link de download
                try:
                    logging.info(f"Acessando detalhes da publicação: {titulo} - {publicacao_url}")
                    response_publicacao = session.get(publicacao_url, headers=headers, timeout=10)
                    response_publicacao.raise_for_status()
                    soup_publicacao = BeautifulSoup(response_publicacao.text, 'html.parser')

                    # Encontrar a div do modal
                    modal_div = soup_publicacao.find('div', id='downloadModal')
                    if not modal_div:
                        logging.warning(f"Div do modal 'downloadModal' não encontrada para a publicação: {titulo}")
                        continue

                    # Encontrar o link de download dentro do modal
                    # Atualize os seletores conforme a estrutura real do modal
                    download_link_tag = modal_div.find('a', attrs={'download': True, 'href': True})
                    if not download_link_tag:
                        logging.warning(f"Link de download não encontrado dentro do modal para a publicação: {titulo}")
                        continue
                    download_url = urljoin(publicacao_url, download_link_tag['href'])

                    # Verificar se o link de download possui uma extensão permitida
                    allowed_extensions = ['.pdf', '.epub', '.docx', '.xlsx', '.zip', '.txt', '.pptx']  # Adicione mais extensões se necessário
                    if not any(download_url.lower().endswith(ext) for ext in allowed_extensions):
                        logging.warning(f"Link de download não possui extensão permitida: {download_url} para a publicação: {titulo}")
                        continue

                    # Extrair a data da publicação, se disponível
                    # Atualize os seletores conforme a estrutura real da página
                    # Exemplo: <span class="publication-date">15/08/2023</span>
                    data_pub_tag = soup_publicacao.find('span', class_='publication-date')
                    if data_pub_tag:
                        data_pub_str = data_pub_tag.get_text(strip=True)
                        try:
                            data_pub = datetime.strptime(data_pub_str, '%d/%m/%Y')
                            ano_pub = data_pub.year
                            logging.info(f"Data de publicação extraída: {data_pub_str} ({ano_pub})")
                        except ValueError:
                            logging.error(f"Formato de data inválido: {data_pub_str} para a publicação: {titulo}")
                            ano_pub = None
                    else:
                        logging.warning(f"Data de publicação não encontrada para a publicação: {titulo}. Usando ano selecionado.")
                        ano_pub = selected_year  # Usar ano selecionado se data não estiver disponível

                    if ano_pub != selected_year:
                        logging.info(f"Publicação '{titulo}' publicada em {ano_pub}, não corresponde ao ano selecionado.")
                        continue  # Ignorar esta publicação

                    # Verificar se o edital já existe no banco de dados
                    edital_existente = db.query(Edital).filter(Edital.link == download_url).first()
                    if not edital_existente:
                        edital = Edital(
                            titulo=titulo,
                            link=download_url,
                            origem='UNDP',
                            ano=ano_pub
                        )
                        db.add(edital)
                        db.commit()
                        logging.info(f"Adicionado publicação da UNDP: {titulo} - {download_url}")
                    else:
                        logging.info(f"Publicação já existe no banco de dados: {titulo} - {download_url}")

                except requests.exceptions.RequestException as e:
                    logging.error(f"Erro ao acessar detalhes da publicação '{titulo}': {e}")
                    continue

            # Atualizar o contador de resultados
            loaded_results += len(publication_cards)

            # Verificar se todos os resultados foram carregados
            if total_results is None:
                # Encontrar o total de resultados, se disponível
                # Atualize o seletor conforme a estrutura real da página
                # Exemplo: <span class="total-results">136</span>
                total_results_tag = soup.find('span', class_='total-results')
                if total_results_tag:
                    try:
                        total_results = int(total_results_tag.get_text(strip=True))
                        logging.info(f"Total de resultados a serem raspados: {total_results}")
                    except ValueError:
                        logging.warning("Não foi possível determinar o total de resultados. Continuando raspagem até não haver mais publicações.")
                        total_results = None

            if total_results and loaded_results >= total_results:
                logging.info("Todos os resultados foram raspados.")
                break

            # Incrementar o número da página
            page += 1

            # Adicionar um delay para evitar sobrecarga no servidor
            time.sleep(1)

    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao acessar {url_principal}: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado: {e}")
    finally:
        db.close()
    return
