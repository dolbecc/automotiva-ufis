import os
import re
import time
import random
import pandas as pd
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# CONFIGURAÇÕES E ARQUIVO DE ENTRADA
# ==========================================
# Nome da planilha (suporta .xlsx ou .csv)
PLANILHA_PATH = "leads.xlsx"  # Altere para "leads.csv" se necessário

# Nome da pasta para salvar a sessão do WhatsApp Web (evita escnear QR Code toda vez)
CHROME_PROFILE_DIR = os.path.join(os.getcwd(), "whatsapp_session")

# ==========================================
# FUNÇÕES AUXILIARES DE TRATAMENTO DE DADOS
# ==========================================
def limpar_numero(numero):
    """
    Remove caracteres não numéricos do telefone e garante o prefixo do Brasil (+55).
    Retorna apenas dígitos (ex: 5511999998888).
    """
    if pd.isna(numero):
        return None
    
    # Converte para string e remove todos os caracteres que não forem dígitos
    apenas_digitos = re.sub(r"\D", "", str(numero))
    
    if not apenas_digitos:
        return None
    
    # Se o número não começar com o DDI do Brasil (55), adiciona 55 no início
    if not apenas_digitos.startswith("55"):
        apenas_digitos = "55" + apenas_digitos
        
    return apenas_digitos


def classificar_lead(row):
    """
    Avalia a coluna 'site' do lead:
    - Retorna ('A', None) se o site for nulo/vazio.
    - Retorna ('B', None) se o site contiver 'facebook' ou 'instagram'.
    - Retorna (None, 'Dominio Real') se possuir um domínio próprio (deve ser pulado).
    """
    site = str(row.get("site", "")).strip().lower()
    
    # Se for vazio, nulo ou NaN
    if pd.isna(row.get("site")) or site == "" or site == "nan" or site == "none":
        return "A", "Sem site"
    
    # Se contiver rede social
    if "facebook" in site or "instagram" in site:
        return "B", "Usa rede social"
    
    # Se tiver domínio real (ex: .com, .com.br, etc.)
    if "." in site or site.startswith("http") or site.startswith("www"):
        return None, f"Domínio real detectado: {site}"
    
    # Fallback para vazios sem pontuação
    return "A", "Sem site"


# ==========================================
# CONFIGURAÇÃO DO SELENIUM WEBDRIVER
# ==========================================
def iniciar_driver():
    """
    Inicializa o navegador Chrome com perfil persistente para salvar o login do WhatsApp.
    """
    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    
    # Usa webdriver-manager para baixar/atualizar o chromedriver automaticamente
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def enviar_mensagem_whatsapp(driver, wait, texto):
    """
    Localiza a caixa de texto do WhatsApp Web, digita a mensagem e envia.
    """
    # XPaths comuns para a caixa de mensagem do WhatsApp Web
    xpath_caixa_texto = '//footer//div[@contenteditable="true"]'
    
    caixa_texto = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_caixa_texto)))
    caixa_texto.click()
    
    # Para lidar com quebras de linha e emojis sem falhas, dividimos por linhas
    linhas = texto.split("\n")
    for idx, linha in enumerate(linhas):
        caixa_texto.send_keys(linha)
        if idx < len(linhas) - 1:
            caixa_texto.send_keys(Keys.SHIFT + Keys.ENTER)
            
    time.sleep(0.5)
    caixa_texto.send_keys(Keys.ENTER)


# ==========================================
# FLUXO PRINCIPAL
# ==========================================
def main():
    # 1. Leitura da planilha
    print("📋 Lendo planilha de leads...")
    if not os.path.exists(PLANILHA_PATH):
        print(f"❌ Erro: O arquivo '{PLANILHA_PATH}' não foi encontrado no diretório atual.")
        print("Por favor, garanta que o arquivo existe e atualize a variável PLANILHA_PATH se necessário.")
        return

    try:
        if PLANILHA_PATH.endswith(".csv"):
            df = pd.read_csv(PLANILHA_PATH)
        else:
            df = pd.read_excel(PLANILHA_PATH)
    except Exception as e:
        print(f"❌ Erro ao ler a planilha: {e}")
        return

    # Validar colunas requeridas
    colunas_necessarias = {"nome", "numero", "site"}
    if not colunas_necessarias.issubset(set(df.columns)):
        print(f"❌ Erro: A planilha deve conter as colunas: {colunas_necessarias}")
        print(f"Colunas encontradas: {list(df.columns)}")
        return

    print(f"✅ Planilha carregada com sucesso! Total de linhas: {len(df)}")

    # 2. Inicializar Selenium
    print("🚀 Inicializando navegador Chrome...")
    driver = iniciar_driver()
    wait = WebDriverWait(driver, 30)

    try:
        print("🌐 Abrindo WhatsApp Web...")
        driver.get("https://web.whatsapp.com")
        print("⏳ Por favor, faça o login via QR Code no celular se ainda não estiver conectado.")
        
        # Aguarda a tela principal do WhatsApp carregar (painel lateral de conversas)
        wait.until(EC.presence_of_element_located((By.XPATH, '//div[@id="pane-side"]')))
        print("✅ Login confirmado no WhatsApp Web! Iniciando disparos...\n")
        time.sleep(3)

        # 3. Loop pelos leads da planilha
        for idx, row in df.iterrows():
            nome = str(row.get("nome", "")).strip()
            numero_bruto = row.get("numero")
            
            numero_limpo = limpar_numero(numero_bruto)
            cenario, motivo = classificar_lead(row)

            # Filtro: Se o lead não for válido (possuir domínio próprio)
            if cenario is None:
                print(f"⏭️  [Linha {idx + 1}] Pulando '{nome}': {motivo}")
                continue

            # Filtro: Se número for inválido/nulo
            if not numero_limpo:
                print(f"⚠️  [Linha {idx + 1}] Pulando '{nome}': Número de telefone inválido.")
                continue

            print(f"--------------------------------------------------")
            print(f"📱 [Linha {idx + 1}] Processando Lead: {nome}")
            print(f"   Número: +{numero_limpo} | Cenário: {cenario} ({motivo})")

            # Montagem das mensagens
            msg1 = "Olá! Boa tarde, tudo bem? Me chamo Ian Victor, muito prazer!"

            if cenario == "A":
                msg2 = f"Estava pesquisando algumas marmorarias da região, encontrei a {nome} e achei o trabalho bem bacana 👏. Porém, notei que vocês ainda não possuem um site próprio oficial."
            else:  # Cenário B
                msg2 = f"Estava pesquisando algumas marmorarias da região, encontrei a {nome} e achei o trabalho bem bacana 👏. Vi que vocês usam as redes sociais, mas notei que ainda não possuem um site próprio oficial."

            msg3 = "Hoje, a maioria das pessoas pesquisa no Google antes de pedir um orçamento, e um site estruturado ajuda muito a transmitir confiança e captar esses clientes que estão pesquisando agora."

            msg4 = "Trabalho com desenvolvimento de sites justamente para esse setor. Eu montei um exemplo em vídeo para te mostrar como um site profissional pode trazer mais orçamentos para vocês. Posso te enviar rapidinho para você dar uma olhada? (E se não for com você, poderia me indicar o responsável, por gentileza?)"

            try:
                # Navega diretamente para o chat do número
                link_whatsapp = f"https://web.whatsapp.com/send?phone={numero_limpo}"
                driver.get(link_whatsapp)

                # Aguarda o chat carregar ou modal de número inválido aparecer
                time.sleep(3)
                
                # Verifica se apareceu alerta de número inexistente/inválido
                try:
                    alerta_invalido = driver.find_elements(By.XPATH, '//div[contains(text(), "inválido") or contains(text(), "invalid")]')
                    if alerta_invalido and len(alerta_invalido) > 0 and alerta_invalido[0].is_displayed():
                        print(f"❌ Número +{numero_limpo} não possui WhatsApp ou é inválido. Pulando...")
                        continue
                except NoSuchElementException:
                    pass

                # Aguarda a caixa de texto ficar clicável
                wait_chat = WebDriverWait(driver, 20)
                wait_chat.until(EC.element_to_be_clickable((By.XPATH, '//footer//div[@contenteditable="true"]')))

                # --- MENSAGEM 1 (Envio imediato) ---
                print("   ➡️  Enviando Mensagem 1...")
                enviar_mensagem_whatsapp(driver, wait_chat, msg1)

                delay1 = random.uniform(3, 5)
                print(f"   ⏳ Aguardando {delay1:.1f}s...")
                time.sleep(delay1)

                # --- MENSAGEM 2 (Condicional) ---
                print("   ➡️  Enviando Mensagem 2...")
                enviar_mensagem_whatsapp(driver, wait_chat, msg2)

                delay2 = random.uniform(5, 8)
                print(f"   ⏳ Aguardando {delay2:.1f}s...")
                time.sleep(delay2)

                # --- MENSAGEM 3 ---
                print("   ➡️  Enviando Mensagem 3...")
                enviar_mensagem_whatsapp(driver, wait_chat, msg3)

                delay3 = random.uniform(5, 8)
                print(f"   ⏳ Aguardando {delay3:.1f}s...")
                time.sleep(delay3)

                # --- MENSAGEM 4 ---
                print("   ➡️  Enviando Mensagem 4...")
                enviar_mensagem_whatsapp(driver, wait_chat, msg4)

                print(f"✅ Disparo concluído com sucesso para: {nome}")

                # --- ANTI-SPAM DELAY ENTRE LEADS ---
                delay_anti_spam = random.uniform(20, 45)
                print(f"🛡️  Pausa Anti-Spam: aguardando {delay_anti_spam:.1f}s antes do próximo contato...")
                time.sleep(delay_anti_spam)

            except Exception as e:
                print(f"⚠️ Erro ao enviar mensagem para +{numero_limpo} ({nome}): {e}")
                print("Continuando para a próxima linha da planilha...")
                time.sleep(5)

        print("\n🎉 Processo de prospecção finalizado com sucesso!")

    finally:
        input("\nPressione ENTER no terminal para fechar o navegador...")
        driver.quit()


if __name__ == "__main__":
    main()
