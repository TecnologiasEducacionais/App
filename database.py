# database.py
from sqlalchemy import create_engine, Column, String, Integer, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Define a URL do banco de dados (SQLite)
DATABASE_URL = 'sqlite:///editais.db'  # Para SQLite

# Cria o engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})  # Necessário para SQLite

# Cria uma classe de sessão
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base declarativa
Base = declarative_base()

# Modelo de dados para Editais
class Edital(Base):
    __tablename__ = 'editais'
    
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, nullable=False)
    link = Column(String, nullable=False, unique=True)
    origem = Column(String, nullable=False)
    ano = Column(Integer, nullable=False)
    
    __table_args__ = (UniqueConstraint('link', name='uix_link'),)
    
def init_db():
    Base.metadata.create_all(bind=engine)