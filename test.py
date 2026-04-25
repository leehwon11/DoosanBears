from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

try:
    driver.get("https://www.koreabaseball.com/Futures/Player/Education.aspx")
    time.sleep(3)
    print("타이틀:", driver.title)
    print("현재 URL:", driver.current_url)
    print("페이지 앞 500자:", driver.page_source[:500])
finally:
    driver.quit()