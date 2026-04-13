from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import json
import os
from datetime import datetime
import pytz
from telegram import Bot
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fund_monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 설정 파일 읽기
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

BOT_TOKEN = config['telegram_bot_token']
CHAT_IDS = config['telegram_chat_ids']
KOFIA_URL = config['kofia_url']
TZ = pytz.timezone(config['timezone'])

# 기준일자 저장 파일
STATE_FILE = 'fund_state.json'

def get_last_state():
    """마지막 상태 읽기"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'last_date': None, 'last_check_date': None}

def save_state(last_date, last_check_date):
    """상태 저장"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'last_date': last_date, 'last_check_date': last_check_date}, f)

def get_basis_date():
    """Selenium을 사용해 KOFIA 페이지에서 기준일자 추출"""
    try:
        logger.info("Selenium으로 KOFIA 페이지 로딩 중...")
        
        # Chrome 옵션 설정
        options = webdriver.ChromeOptions()
        options.add_argument('--start-maximized')
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        # GitHub Actions 환경 감지
        if os.environ.get('GITHUB_ACTIONS'):
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            logger.info("GitHub Actions 환경 감지됨 - headless 모드 실행")
        
        # Chrome 드라이버 설정
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        
        logger.info(f"페이지 이동: {KOFIA_URL}")
        driver.get(KOFIA_URL)
        
        # 페이지 로드 대기 (최대 30초)
        wait = WebDriverWait(driver, 30)
        date_input = wait.until(
            EC.presence_of_element_located((By.ID, 'nextDate_input'))
        )
        
        # 기준일자 추출
        basis_date = date_input.get_attribute('value')
        
        driver.quit()
        
        if basis_date:
            logger.info(f"기준일자 추출 성공: {basis_date}")
            return basis_date
        else:
            logger.warning("기준일자 값이 비어있습니다")
            return None
            
    except Exception as e:
        logger.error(f"기준일자 추출 실패: {str(e)}")
        try:
            driver.quit()
        except:
            pass
        return None

def send_telegram_message(message):
    """Telegram으로 메시지 발송"""
    try:
        bot = Bot(token=BOT_TOKEN)
        for chat_id in CHAT_IDS:
            bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"Telegram 메시지 발송 성공: {chat_id}")
    except Exception as e:
        logger.error(f"Telegram 메시지 발송 실패: {str(e)}")

def check_fund_basis_date():
    """펀드 기준일자 확인 및 모니터링"""
    logger.info("=" * 50)
    logger.info("펀드 기준일자 모니터링 시작")
    
    current_state = get_last_state()
    current_date = datetime.now(TZ)
    
    basis_date = get_basis_date()
    
    if not basis_date:
        logger.error("기준일자를 가져올 수 없습니다")
        return False
    
    last_date = current_state.get('last_date')
    last_check_date = current_state.get('last_check_date')
    
    logger.info(f"현재 기준일자: {basis_date}")
    logger.info(f"이전 기준일자: {last_date}")
    logger.info(f"마지막 확인일: {last_check_date}")
    
    # 기준일자가 변경되었는지 확인
    if basis_date != last_date:
        logger.info(f"🔔 기준일자 변경 감지!")
        
        message = f"""🔔 <b>[펀드 기준일자 변경]</b>

이전 기준일자: {last_date or 'N/A'}
변경 기준일자: {basis_date}

확인 시간: {current_date.strftime('%Y년 %m월 %d일 %H:%M:%S')}"""
        
        send_telegram_message(message)
        
        save_state(basis_date, current_date.strftime('%Y-%m-%d'))
        logger.info("상태 저장: 기준일자 변경됨")
        return True
    else:
        logger.info("기준일자 변경 없음")
        save_state(basis_date, current_date.strftime('%Y-%m-%d'))
        return False
    
    logger.info("=" * 50)

def main():
    """메인 실행 함수"""
    logger.info("프로그램 시작")
    check_fund_basis_date()
    logger.info("프로그램 종료")

if __name__ == '__main__':
    main()