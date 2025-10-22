import re, time
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    UnexpectedAlertPresentException,
    JavascriptException,
)
from webdriver_manager.chrome import ChromeDriverManager

URL_PLAYER = "https://meet.sports.or.kr/national/search/player.do"


# ===== 공통 =====
def setup_driver(headless=True):
    opt = Options()
    if headless:
        opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1400,2400")
    opt.set_capability("unhandledPromptBehavior", "accept")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opt
    )


def accept_alert_if_present(driver, timeout=2):
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        Alert(driver).accept()
        return True
    except Exception:
        return False


def _normalize(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\xa0", " ").replace("　", " ")
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return re.sub(r"\s+", " ", s).strip()


def _click_js(driver, el):
    driver.execute_script("arguments[0].click();", el)


# ===== 페이지 진입 =====
def open_player_search(driver):
    driver.get(URL_PLAYER)
    accept_alert_if_present(driver, 2)
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.searchBox01"))
    )
    time.sleep(0.2)


# ===== 시/도 = 전남 전용 선택기 (단순·고속) =====
def _get_visible_selects(driver):
    return driver.execute_script(
        """
        const boxes = Array.from(document.querySelectorAll('div.search-select'));
        return boxes.filter(el => {
            const st = getComputedStyle(el);
            return st.display !== 'none' && el.offsetWidth > 0 && el.offsetHeight > 0 && st.opacity !== '0';
        });
    """
    )


def select_sido_jeonnam(driver, open_timeout=6, close_timeout=4):
    # 1) 시도 버튼 열기
    btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "sidoCdBtn"))
    )
    _click_js(driver, btn)

    # 2) 보이는 select 박스 찾기
    box = None
    end = time.time() + open_timeout
    while time.time() < end:
        boxes = _get_visible_selects(driver)
        if boxes:
            box = boxes[0]
            break
        time.sleep(0.1)
    if box is None:
        return False

    # 3) '전남' 항목 클릭 (텍스트/onclick 폴백)
    want = _normalize("전남")
    lis = box.find_elements(By.CSS_SELECTOR, "ul > li")
    target = None
    for li in lis:
        try:
            a = li.find_element(By.TAG_NAME, "a")
            if _normalize(a.text) == want:
                target = li
                break
        except Exception:
            pass
    if target is None:
        for li in lis:
            oc = li.get_attribute("onclick") or ""
            if "전남" in oc:
                target = li
                break
    if target is None:
        return False

    _click_js(driver, target)

    # 4) 닫힘(비가시) 대기
    end2 = time.time() + close_timeout
    while time.time() < end2:
        if not _get_visible_selects(driver):
            break
        time.sleep(0.1)
    return True


def ensure_sido_is_jeonnam(driver):
    try:
        btn = driver.find_element(By.ID, "sidoCdBtn")
        cur = _normalize(btn.text)
        if cur == _normalize("전남"):
            return True
    except Exception:
        pass
    return select_sido_jeonnam(driver)


# ===== 입력/검색 =====
def set_name_input(driver, name):
    nm = driver.find_element(By.ID, "searchKorNm")
    nm.clear()
    nm.send_keys(name or "")


def click_search(driver):
    for xp in [
        "//button[normalize-space()='검색']",
        "//a[normalize-space()='검색']",
        "//button[contains(@onclick,'search') or contains(@onclick,'get') or contains(@onclick,'fn')]",
    ]:
        btns = driver.find_elements(By.XPATH, xp)
        if btns:
            _click_js(driver, btns[0])
            break
    accept_alert_if_present(driver, 3)


# ===== 결과 대기/판독 =====
def wait_result_table_soup(driver, open_timeout=8, table_timeout=15, poll=0.2):
    try:
        WebDriverWait(driver, open_timeout).until(
            EC.presence_of_element_located((By.ID, "printDiv"))
        )
    except TimeoutException:
        return None
    end = time.time() + table_timeout
    while time.time() < end:
        try:
            box = driver.find_element(By.ID, "printDiv")
            html = box.get_attribute("outerHTML")
            soup = BeautifulSoup(html, "lxml")
            if soup.select("table.tablesaw.tablesaw-stack tbody tr"):
                return soup
        except UnexpectedAlertPresentException:
            accept_alert_if_present(driver, 2)
        time.sleep(poll)
    return None


def _td_content_soup(td):
    """<td>에서 span.tablesaw-cell-content만 안전하게 추출"""
    sp = td.find("span", class_="tablesaw-cell-content")
    return _normalize(
        sp.get_text(" ", strip=True) if sp else td.get_text(" ", strip=True)
    )


def _find_player_result_table(soup):
    """캡션이 '선수명 검색 결과'인 테이블만 선택"""
    for t in soup.select("table.tablesaw.tablesaw-stack"):
        cap = t.find("caption")
        if cap and "선수명 검색 결과" in cap.get_text(" ", strip=True):
            return t
    return None


def any_row_matches_by_skn(soup, sport, kind, name):
    """표에서 (종목/종별/선수명) 완전일치 1건 이상 여부"""
    sport = _normalize(sport)
    kind = _normalize(kind)
    name = _normalize(name)

    table = _find_player_result_table(soup)
    if table is None:
        return False

    rows = table.select("tbody > tr")
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue

        # ✳️ 라벨(b.tablesaw-cell-label)은 무시하고 content span만 사용
        td_sport = _td_content_soup(tds[0])  # 종목
        td_kind = _td_content_soup(tds[1])  # 종별
        td_name = _td_content_soup(tds[4])  # 선수명

        if td_sport == sport and td_kind == kind and td_name == name:
            return True
    return False


# ===== 메인: 진위확인(전남+성명만으로 검색) =====
def attach_truth_flag_fast(
    df,
    sport_col="경기부문",
    kind_col="종별",
    name_col="성명",
    headless=True,
    open_timeout=8,
    table_timeout=15,
    poll=0.2,
    log=True,
):
    """
    시도=전남만 선택하고 성명만 입력해서 검색 → 결과표에서 (종목/종별/성명) 일치 여부 확인.
    '진위확인' 0/1 컬럼 추가해 반환.
    """
    driver = setup_driver(headless=headless)
    try:
        open_player_search(driver)
        # 최초 1회 전남 세팅
        if not ensure_sido_is_jeonnam(driver):
            raise RuntimeError("시/도 '전남' 선택 실패")

        truth = []
        n = len(df)

        for idx, row in df.iterrows():
            sport = row[sport_col]
            kind = row[kind_col]
            name = row[name_col]

            # --- 로그 프리픽스
            if log:
                print(
                    f"[{idx+1:>4}/{n}] 조회요청 | 종목={sport} | 종별={kind} | 성명={name} … ",
                    end="",
                    flush=True,
                )

            try:
                # 혹시 페이지 리셋되면 전남 다시 확인
                ensure_sido_is_jeonnam(driver)

                set_name_input(driver, name)
                click_search(driver)

                soup = wait_result_table_soup(
                    driver,
                    open_timeout=open_timeout,
                    table_timeout=table_timeout,
                    poll=poll,
                )
                if soup is None:
                    truth.append(0)
                    if log:
                        print("FAIL (결과표 미등장/타임아웃)")
                    continue

                ok = any_row_matches_by_skn(soup, sport, kind, name)
                truth.append(1 if ok else 0)
                if log:
                    print("OK" if ok else "NO MATCH")

            except JavascriptException as e:
                truth.append(0)
                if log:
                    print(f"FAIL (JS 예외: {str(e)[:120]})")
            except TimeoutException as e:
                truth.append(0)
                if log:
                    print(f"FAIL (대기 타임아웃: {str(e)[:120]})")
            except Exception as e:
                truth.append(0)
                if log:
                    print(f"FAIL (예외: {type(e).__name__}: {str(e)[:120]})")

        out = df.copy()
        out["진위확인"] = truth
        return out
    finally:
        driver.quit()

if __name__ == "__main__":
    df = pd.read_excel(
        "선수참가현황검증.xlsx",
        sheet_name="학생선수 참가 명단",
        header=2,  # 0-based index → 2면 엑셀의 3번째 행이 컬럼명
    )

    # (옵션) 'Unnamed'로 시작하는 열들 정리
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    # df는 최소 ['경기부문','종별','성명'] 포함
    checked = attach_truth_flag_fast(
        df,
        sport_col="경기부문",
        kind_col="종별",
        name_col="성명",
        headless=True,
        open_timeout=8,
        table_timeout=15,
        poll=0.2,  # 필요하면 늘리면 됨
        log=True,
    )
    checked.to_excel("전남_성명검증_결과.xlsx", index=False)