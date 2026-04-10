import asyncio
from playwright.async_api import async_playwright
import json
import os
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot
import logging
import time
import threading

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

async def get_basis_date():
    """Playwright를 사용해 KOFIA 페이지에서 기준일자 추출"""
    try:
        logger.info("Playwright로 KOFIA 페이지 로딩 중...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            logger.info(f"페이지 이동: {KOFIA_URL}")
            await page.goto(KOFIA_URL, wait_until='networkidle', timeout=30000)
            
            # 페이지가 로드될 때까지 대기
            await page.wait_for_load_state('networkidle')
            
            # JavaScript 실행으로 기준일자 추출
            basis_date = await page.evaluate("""
                () => {
                    const dateInput = document.getElementById('nextDate_input');
                    if (dateInput && dateInput.value) {
                        return dateInput.value;
                    }
                    return null;
                }
            """)
            
            await browser.close()
            
            if basis_date:
                logger.info(f"기준일자 추출 성공: {basis_date}")
                return basis_date
            else:
                logger.warning("기준일자를 찾을 수 없습니다")
                return None
                
    except Exception as e:
        logger.error(f"기준일자 추출 실패: {str(e)}")
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

def is_korean_business_day(date_obj):
    """한국 영업일 확인 (주말 제외)"""
    # 0=월, 1=화, 2=수, 3=목, 4=금, 5=토, 6=일
    return date_obj.weekday() < 5

def get_next_business_day(date_obj):
    """다음 영업일 구하기"""
    next_day = date_obj + timedelta(days=1)
    while not is_korean_business_day(next_day):
        next_day += timedelta(days=1)
    return next_day

def check_fund_basis_date_sync():
    """펀드 기준일자 확인 및 모니터링 (동기 래퍼)"""
    logger.info("=" * 50)
    logger.info("펀드 기준일자 모니터링 시작")
    
    current_state = get_last_state()
    current_date = datetime.now(TZ)
    
    # 비동기 함수를 동기적으로 실행
    basis_date = asyncio.run(get_basis_date())
    
    if not basis_date:
        logger.error("기준일자를 가져올 수 없습니다")
        return
    
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
        
        # 상태 저장 - 기준일자가 변경되었으므로 다음 영업일 체크 스킵
        save_state(basis_date, current_date.strftime('%Y-%m-%d'))
        logger.info("상태 저장: 기준일자 변경됨 (다음 영업일 스킵)")
    else:
        logger.info("기준일자 변경 없음")
        # 상태만 업데이트
        save_state(basis_date, current_date.strftime('%Y-%m-%d'))
    
    logger.info("=" * 50)

def schedule_monitoring():
    """스케줄 설정: 매월 10일 + 다음 영업일"""
    scheduler = BackgroundScheduler(timezone=str(TZ))
    
    # 매월 10일 오전 9시에 실행
    scheduler.add_job(
        check_fund_basis_date_sync,
        'cron',
        day=10,
        hour=9,
        minute=0,
        id='monthly_10th'
    )
    
    # 매월 11일 오전 9시에 실행 (10일 다음 영업일)
    scheduler.add_job(
        check_fund_basis_date_sync,
        'cron',
        day=11,
        hour=9,
        minute=0,
        id='monthly_11th'
    )
    
    scheduler.start()
    logger.info("스케줄러 시작: 매월 10일 + 11일 오전 9시 모니터링")
    
    try:
        # 스케줄러가 계속 실행되도록
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("모니터링 중단")
        scheduler.shutdown()

def test_mode():
    """테스트 모드: 즉시 실행"""
    logger.info("테스트 모드 시작")
    check_fund_basis_date_sync()
    logger.info("테스트 모드 완료")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        # 테스트 모드
        test_mode()
    else:
        # 정상 모드 (스케줄러 실행)
        schedule_monitoring()