import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
})

init_resp = session.get("https://www.koreabaseball.com/Player/Register.aspx", timeout=15)
init_soup = BeautifulSoup(init_resp.text, "html.parser")

def get_val(name):
    tag = init_soup.find("input", {"name": name})
    return tag["value"] if tag else ""

viewstate = get_val("__VIEWSTATE")
vsg = get_val("__VIEWSTATEGENERATOR")
ev = get_val("__EVENTVALIDATION")
print("ViewState 있음:", bool(viewstate))

session.headers.update({
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "https://www.koreabaseball.com/Player/Register.aspx",
    "X-Requested-With": "XMLHttpRequest",
})

payload = {
    "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$ScriptManager1":
        "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$udpRecord|"
        "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$btnCalendarSelect",
    "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$hfSearchTeam": "OB",
    "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$hfSearchDate": "20260425",
    "__EVENTTARGET": "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$btnCalendarSelect",
    "__EVENTARGUMENT": "",
    "__VIEWSTATE": viewstate,
    "__VIEWSTATEGENERATOR": vsg,
    "__EVENTVALIDATION": ev,
    "__ASYNCPOST": "true",
}

resp = session.post("https://www.koreabaseball.com/Player/Register.aspx", data=payload, timeout=15)
print("Status:", resp.status_code)
print("두산 포함:", "두산" in resp.text)
print("응답 앞 500자:", resp.text[:500])