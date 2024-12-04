# app.py
from flask import Flask, render_template, request, flash, jsonify
import pandas as pd
import os
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from database import SessionLocal, Edital, Base, engine
from scrapers.faperj import extrair_dados_faperj
from scrapers.capes import extrair_dados_capes
from scrapers.finep import extrair_dados_finep
from scrapers.config import KEYWORDS

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import pytz

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'sua_chave_secreta')  # Recomendado usar variável de ambiente

# Configuração do logging
LOG_FILE = 'app.log'  # Caminho relativo para o arquivo de log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# Configuração do acesso à API do Google Sheets (opcional, manter ou remover)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]

# Caminho direto para o arquivo de credenciais do Google Sheets
CREDENTIALS_FILE = os.path.join('apisheet', 'apisheet-440914-f225e8c0f1d8.json')

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    # Acesse a planilha pelo nome ou ID
    SPREADSHEET_NAME = "WebScraper_Editais"  # Substitua pelo nome da sua planilha
    spreadsheet = client.open(SPREADSHEET_NAME)
    sheet = spreadsheet.sheet1  # A primeira aba da planilha
    logging.info("Conectado ao Google Sheets com sucesso.")
except Exception as e:
    logging.error(f"Erro ao conectar ao Google Sheets: {e}")

# Definição das fontes de scraping
SOURCES = {
    'FAPERJ': {
        'urls': [
            "https://www.faperj.br/?id=28.5.7",
            # Adicione outras URLs da FAPERJ se necessário
        ],
        'function': extrair_dados_faperj
    },
    'CAPES': {
        'urls': [
            "https://www.gov.br/capes/pt-br/assuntos/editais-e-resultados-capes",
            # Adicione outras URLs da CAPES se necessário
        ],
        'function': extrair_dados_capes
    },
    'FINEP': {  # Adição da FINEP
        'urls': [
            "https://www.finep.gov.br/chamadas-publicas/chamadaspublicas?situacao=aberta",  # URL principal ajustada
            # Adicione outras URLs da FINEP se necessário
        ],
        'function': extrair_dados_finep
    },
    # Adicione mais fontes aqui conforme você cria os scrapers
}

# Função para inicializar o banco de dados
def init_database():
    Base.metadata.create_all(bind=engine)
    logging.info("Banco de dados inicializado.")

# Função para realizar o scraping de todas as fontes para um ano específico
def coletar_todos_editais(selected_year):
    logging.info(f"Iniciando coleta de editais para o ano {selected_year}.")
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_source = {}
        for source_name, source_info in SOURCES.items():
            for url in source_info['urls']:
                future = executor.submit(source_info['function'], url, selected_year)
                future_to_source[future] = f"{source_name} - {url}"
        
        for future in as_completed(future_to_source):
            source = future_to_source[future]
            try:
                future.result()
                logging.info(f"Dados coletados com sucesso de: {source}")
            except Exception as exc:
                logging.error(f"Erro ao coletar dados de {source}: {exc}")
    logging.info("Coleta de editais concluída.")

# Função para atualizar os editais (chamada pelo scheduler)
def atualizar_editais():
    logging.info("Iniciando atualização de editais.")
    selected_years = range(datetime.now().year - 10, datetime.now().year + 1)  # Últimos 10 anos até o ano atual
    for year in selected_years:
        coletar_todos_editais(year)
    atualizar_google_sheets(selected_years)
    logging.info("Atualização de editais concluída.")

# Função para atualizar o Google Sheets com os dados do banco de dados
def atualizar_google_sheets(selected_years):
    try:
        db = SessionLocal()
        editais = db.query(Edital).filter(Edital.ano.in_(selected_years)).all()
        all_dados = [{
            'Título': edital.titulo,
            'Link': edital.link,
            'Origem': edital.origem,
            'Ano': edital.ano
        } for edital in editais]
        db.close()

        df_combined = pd.DataFrame(all_dados)
        if not df_combined.empty:
            # Limpa os dados anteriores da planilha
            sheet.clear()

            # Atualiza a planilha com os novos dados
            sheet.update([df_combined.columns.values.tolist()] + df_combined.values.tolist())
            logging.info("Dados salvos com sucesso no Google Sheets.")
    except Exception as e:
        logging.error(f"Erro ao atualizar o Google Sheets: {e}")

# Inicializar o banco de dados
init_database()

# Verificar se o banco de dados está vazio e realizar o scraping inicial para múltiplos anos
def verificar_e_inicializar():
    db = SessionLocal()
    try:
        count = db.query(Edital).count()
        if count == 0:
            logging.info("Banco de dados vazio. Executando scraping inicial para múltiplos anos.")
            selected_years = range(datetime.now().year - 10, datetime.now().year + 1)  # Últimos 10 anos até o ano atual
            for year in selected_years:
                coletar_todos_editais(year)
            atualizar_google_sheets(selected_years)
        else:
            logging.info(f"Banco de dados já possui {count} editais. Não é necessário executar scraping inicial.")
    except Exception as e:
        logging.error(f"Erro ao verificar o banco de dados: {e}")
    finally:
        db.close()

verificar_e_inicializar()

# Configurar o APScheduler
def configurar_scheduler():
    scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Sao_Paulo'))
    trigger = CronTrigger(day_of_week='sun', hour=3, minute=0)
    scheduler.add_job(func=atualizar_editais, trigger=trigger, id='atualizacao_editais', replace_existing=True)
    scheduler.start()
    logging.info("Scheduler iniciado para atualizar os editais todos os domingos às 03h00 (Horário de Brasília).")
    return scheduler

scheduler = configurar_scheduler()

# Garantir que o scheduler seja desligado ao encerrar o aplicativo
atexit.register(lambda: scheduler.shutdown())

@app.route('/api/get_data', methods=['GET'])
def api_get_data():
    """
    Endpoint de API para obter dados com base no ano selecionado.
    Espera um parâmetro 'ano' via query string.
    Retorna os dados em formato JSON.
    """
    selected_year = request.args.get('ano')
    if not selected_year:
        return jsonify({'error': 'Ano não fornecido.'}), 400

    try:
        selected_year = int(selected_year)
    except ValueError:
        return jsonify({'error': 'Ano inválido.'}), 400

    try:
        db = SessionLocal()
        editais = db.query(Edital).filter(Edital.ano == selected_year).all()
        all_dados = [{
            'Título': edital.titulo,
            'Link': edital.link,
            'Origem': edital.origem,
            'Ano': edital.ano
        } for edital in editais]
    except Exception as e:
        logging.error(f"Erro ao consultar o banco de dados: {e}")
        return jsonify({'error': 'Erro interno do servidor.'}), 500
    finally:
        db.close()

    return jsonify(all_dados), 200

@app.route('/', methods=['GET'])
def index():
    # Adicionando logs para depuração
    templates_path = os.path.abspath(app.template_folder)
    logging.info(f"Pasta de templates: {templates_path}")
    index_exists = os.path.isfile(os.path.join(templates_path, 'index.html'))
    logging.info(f"Existência do index.html: {index_exists}")
    
    # Obter a lista de anos disponíveis (por exemplo, dos últimos 10 anos)
    current_year = datetime.now().year
    anos = list(range(current_year, current_year - 10, -1))  # Últimos 10 anos
    return render_template('index.html', anos=anos, selected_year=None)

if __name__ == '__main__':
    app.run(debug=True)
