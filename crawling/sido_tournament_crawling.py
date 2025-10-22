import re
import time
import logging
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, UnexpectedAlertPresentException, JavascriptException

URL = "https://meet.sports.or.kr/national/schedule/scheduleT.do"
log = logging.getLogger("meet-sports")


# ================= 공통 =================
def setup_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,2400")
    options.set_capability("unhandledPromptBehavior", "accept")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

def accept_alert_if_present(driver, timeout=2):
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        Alert(driver).accept()
        return True
    except Exception:
        return False

def wait_ignoring_alerts(driver, condition, timeout=20, retries=2):
    for _ in range(retries + 1):
        try:
            return WebDriverWait(driver, timeout).until(condition)
        except UnexpectedAlertPresentException:
            accepted = accept_alert_if_present(driver, timeout=2)
            if not accepted:
                raise
    return WebDriverWait(driver, timeout).until(condition)

def click_load_more_if_exists(driver, max_clicks=30):
    wait_short = WebDriverWait(driver, 4)
    clicks = 0
    while clicks < max_clicks:
        try:
            more = wait_short.until(EC.element_to_be_clickable((
                By.XPATH, "//button[normalize-space()='더보기' or contains(.,'더보기')] | //a[normalize-space()='더보기' or contains(.,'더보기')]"
            )))
            driver.execute_script("arguments[0].click();", more)
            time.sleep(1.0)
            clicks += 1
        except Exception:
            break
    return clicks

def _normalize(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\xa0", " ").replace("　", " ")
    trans = str.maketrans("０１２３４５６７８９", "0123456789")
    return re.sub(r"\s+", " ", s.translate(trans)).strip()

def _dedupe_consecutive_words(s: str) -> str:
    """
    (공백 기준) 연속으로 같은 단어가 반복되면 한 번만 남긴다.
    예: '단체전 단체전' -> '단체전'
    """
    s = _normalize(s)
    if not s:
        return s
    tokens = s.split()
    out = []
    for t in tokens:
        if not out or out[-1] != t:
            out.append(t)
    s2 = " ".join(out)

    # 공백 없이 붙은 반복(예: '단체전단체전')까지 방어
    for term in ("단체전", "개인전", "단식", "복식", "혼합복식"):
        s2 = re.sub(fr'(?:{re.escape(term)})\s*(?:{re.escape(term)})+', term, s2)
    return s2


def _clean_subkind(value: str, logger=None) -> str:
    before = _normalize(value)
    after = _dedupe_consecutive_words(before)
    if logger and before != after:
        logger.debug(f"[세부종목 정제] '{before}' -> '{after}'")
    return after


def _cell_text_bs(td):
    span = td.find("span", class_="tablesaw-cell-content")
    txt = span.get_text(" ", strip=True) if span else td.get_text(" ", strip=True)
    return _normalize(txt)

def _cell_text_el(td_el):
    # 우선 content span의 textContent(숨김 포함) → 비면 td 자체의 textContent → 마지막 폴백 .text
    try:
        span = td_el.find_element(By.CSS_SELECTOR, "span.tablesaw-cell-content")
        txt = span.get_attribute("textContent")
        if not _normalize(txt):
            txt = td_el.get_attribute("textContent")
        return _normalize(txt)
    except Exception:
        try:
            return _normalize(td_el.get_attribute("textContent"))
        except Exception:
            return _normalize(td_el.text)

def _build_global_pk(sport, kind, subkind, matchtype):
    # 필요시 슬러그화 규칙 추가 가능(지금은 정규화만)
    return f"{_normalize(sport)}_{_normalize(kind)}_{_normalize(subkind)}_{_normalize(matchtype)}"

# ================= 참가선수 파싱 도우미 =================
def _parse_checkbox_cell(td_soup):
    img = td_soup.find("img")
    if not img or not img.get("src"):
        return ""
    src = img["src"]
    return "Y" if any(k in src for k in ["check", "on", "checked"]) else "N"

def _get_pc_header_map(team_li):
    header_map = {}
    thead = team_li.select_one("div.boardTable01 table.pcView thead")
    if not thead:
        return header_map
    ths = thead.select("tr > th")
    for idx, th in enumerate(ths):
        label = _normalize(th.get_text(" ", strip=True))
        if "출전" in label:
            header_map["출전"] = idx
        elif "선수" in label:
            header_map["선수명"] = idx
        elif "소속" in label:
            header_map["소속[학년]"] = idx
        elif "포지션" in label or "포지" in label:
            header_map["포지션"] = idx
    return header_map

def _build_match_title(side_soup):
    st = side_soup.select_one("div.record .scoreTop")
    if not st:
        return ""
    spans = st.find_all("span")
    if not spans:
        return _normalize(st.get_text(" ", strip=True))
    parts = []
    first = _normalize(spans[0].get_text(" ", strip=True))
    parts += [p.strip() for p in first.split(">") if p.strip()]
    last = _normalize(spans[-1].get_text(" ", strip=True))
    if last:
        parts.append(last)
    return ">".join(parts)

# === 선수 리스트(모바일 뷰) ===
def _parse_team_mob_list(team_li, team_name, match_title, local_pk, global_pk):
    rows = []
    lis = team_li.select("div.mobView ul.box-list > li")
    if not lis:
        return rows

    def flush_current(cur):
        if cur.get("선수명") or cur.get("소속[학년]") or cur.get("포지션"):
            rows.append({
                "로컬 PK": local_pk,
                "글로벌 PK": global_pk,
                "경기 제목": match_title,
                "팀 구분": _normalize(team_name),
                "출전": cur.get("출전", ""),
                "선수명": cur.get("선수명", ""),
                "소속[학년]": cur.get("소속[학년]", ""),
                "포지션": cur.get("포지션", ""),
            })

    current = {"출전": "", "선수명": "", "소속[학년]": "", "포지션": ""}

    for li in lis:
        strong = li.find("strong")
        if not strong:
            continue
        key = _normalize(strong.get_text(" ", strip=True))
        span = li.find("span")

        if "출전" in key:
            val = ""
            if span:
                img = span.find("img")
                if img and img.get("src"):
                    src = img["src"]
                    val = "Y" if any(k in src for k in ["check", "on", "checked"]) else "N"
            current["출전"] = val

        elif "선수" in key:
            if current.get("선수명"):
                flush_current(current)
                current = {"출전": "", "선수명": "", "소속[학년]": "", "포지션": ""}
            current["선수명"] = _normalize(span.get_text(" ", strip=True)) if span else ""

        elif "소속" in key:
            current["소속[학년]"] = _normalize(span.get_text(" ", strip=True)) if span else ""

        elif "포지션" in key or "포지" in key:
            current["포지션"] = _normalize(span.get_text(" ", strip=True)) if span else ""
            flush_current(current)
            current = {"출전": "", "선수명": "", "소속[학년]": "", "포지션": ""}

    flush_current(current)
    return rows

# === 선수 리스트(PC 뷰) ===
def _parse_team_pc_table(team_li, team_name, match_title, local_pk, global_pk):
    rows = []
    table = team_li.select_one("div.boardTable01 table.pcView")
    if not table:
        return rows

    header_map = _get_pc_header_map(team_li)
    tbody = table.select_one("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        out_val = name_val = aff_val = pos_val = ""

        if header_map:
            if "출전" in header_map and header_map["출전"] < len(tds):
                out_val = _parse_checkbox_cell(tds[header_map["출전"]])
            if "선수명" in header_map and header_map["선수명"] < len(tds):
                name_val = _normalize(tds[header_map["선수명"]].get_text(" ", strip=True))
            if "소속[학년]" in header_map and header_map["소속[학년]"] < len(tds):
                aff_val = _normalize(tds[header_map["소속[학년]"]].get_text(" ", strip=True))
            if "포지션" in header_map and header_map["포지션"] < len(tds):
                pos_val = _normalize(tds[header_map["포지션"]].get_text(" ", strip=True))
        else:
            if len(tds) == 4:
                out_val = _parse_checkbox_cell(tds[0])
                name_val = _normalize(tds[1].get_text(" ", strip=True))
                aff_val  = _normalize(tds[2].get_text(" ", strip=True))
                pos_val  = _normalize(tds[3].get_text(" ", strip=True))
            elif len(tds) == 3:
                out_val = ""
                name_val = _normalize(tds[0].get_text(" ", strip=True))
                aff_val  = _normalize(tds[1].get_text(" ", strip=True))
                pos_val  = _normalize(tds[2].get_text(" ", strip=True))
            else:
                continue

        if not (name_val or aff_val or pos_val):
            continue

        rows.append({
            "로컬 PK": local_pk,
            "글로벌 PK": global_pk,
            "경기 제목": match_title,
            "팀 구분": _normalize(team_name),
            "출전": out_val,
            "선수명": name_val,
            "소속[학년]": aff_val,
            "포지션": pos_val,
        })
    return rows

# ================= 페이지 조작/목록 =================
def open_and_select_jeonnam_all_dates(driver):
    wait = WebDriverWait(driver, 20)
    driver.get(URL)

    try:
        sido_btn = wait.until(EC.element_to_be_clickable((By.ID, "sidoCdBtn")))
        sido_btn.click()
    except Exception:
        sido_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[contains(@class,'search-cities-provinces') and contains(.,'전남')]"
        )))
        sido_btn.click()

    try:
        jeonnam_li = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//ul[@id='sidoCdList']//li[contains(@onclick, \"getGmDtList('13','전남')\")]"
        )))
        jeonnam_li.click()
    except Exception:
        jeonnam_li = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//ul[@id='sidoCdList']//li/a[normalize-space()='전남']/parent::li"
        )))
        jeonnam_li.click()

    accept_alert_if_present(driver, timeout=3)

    try:
        search_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[contains(@class,'searchBtn') or @onclick='javascript:search();']"
        )))
        search_btn.click()
    except Exception:
        pass

    accept_alert_if_present(driver, timeout=2)

    wait_ignoring_alerts(
        driver,
        EC.presence_of_element_located((By.CSS_SELECTOR, "table.tablesaw.tablesaw-stack")),
        timeout=20,
        retries=2
    )
    time.sleep(1.0)

def _row_map_by_label_bs(tr):
    """
    tbody > tr 안의 각 td에서 <b.tablesaw-cell-label> 라벨을 키로,
    <span.tablesaw-cell-content> 값을 밸류로 하는 dict를 만들어 반환.
    """
    m = {}
    for td in tr.find_all("td", recursive=False):
        label_el = td.find("b", class_="tablesaw-cell-label")
        if not label_el:
            continue
        label = _normalize(label_el.get_text(" ", strip=True))
        val = _cell_text_bs(td)
        m[label] = val
    return m

def parse_all_tables(driver):
    soup = BeautifulSoup(driver.page_source, "lxml")
    results = []
    seq = 1

    def get_sport_label_for(table):
        h5 = table.find_previous("h5", id="classNm")
        if not h5:
            h5 = table.find_previous("h5", class_="subTit") or table.find_previous("h5")
        return (h5.get_text(" ", strip=True) if h5 else "").strip()

    for table in soup.select("table.tablesaw.tablesaw-stack"):
        cap = table.select_one("caption")
        if cap and "시·도 토너먼트 경기일정" not in cap.get_text(strip=True):
            continue

        sport_label = get_sport_label_for(table)
        tbody = table.find("tbody")
        if not tbody:
            continue

        last_kind = ""  # rowspan으로 비는 '종별' carry-forward

        for tr in tbody.find_all("tr", recursive=False):
            rowmap = _row_map_by_label_bs(tr)
            # 라벨 없는 행(예: 광고성/빈행) 방지
            if not rowmap:
                continue

            kind      = rowmap.get("종별") or last_kind
            subkind_raw = rowmap.get("세부종목", "")
            subkind = _clean_subkind(subkind_raw, log)
            matchtype = rowmap.get("경기구분", "")
            status    = rowmap.get("상태", "")
            when      = rowmap.get("일시", "")
            venue     = rowmap.get("경기장", "")
            region    = rowmap.get("시도", "")

            if rowmap.get("종별"):
                last_kind = kind  # 새로 나타난 값이면 갱신

            row = {
                "로컬 PK": seq,
                "종목정보": _normalize(sport_label),
                "종별": _normalize(kind),
                "세부종목": _normalize(subkind),
                "경기구분": _normalize(matchtype),
                "상태": _normalize(status),
                "일시": _normalize(when),
                "경기장": _normalize(venue),
                "시도": _normalize(region),
            }
            row["글로벌 PK"] = _build_global_pk(row["종목정보"], row["종별"], row["세부종목"], row["경기구분"])

            results.append(row)
            seq += 1

    return results


# =============== (클릭용) tr에서 PK 구성에 필요한 메타 추출 ===============
def _sport_label_from_tr(tr_el):
    # 해당 tr 소속 table의 바로 앞쪽 h5 텍스트를 우선 시도
    # 1) id='classNm' 또는 class='subTit'가 가장 신뢰도 높음
    for xp in [
        "ancestor::table/preceding::h5[@id='classNm' or contains(@class,'subTit')][1]",
        "ancestor::table/preceding::h5[1]"
    ]:
        try:
            h5 = tr_el.find_element(By.XPATH, xp)
            return _normalize(h5.text)
        except Exception:
            continue
    return ""

def _row_map_by_label_el(tr_el):
    m = {}
    for td in tr_el.find_elements(By.TAG_NAME, "td"):
        try:
            label_el = td.find_element(By.CSS_SELECTOR, "b.tablesaw-cell-label")
        except Exception:
            continue
        # 라벨도 .text가 아니라 textContent로! (PC뷰에서 숨겨져 있어도 읽힘)
        label = _normalize(label_el.get_attribute("textContent"))
        if not label:   # 빈 라벨은 스킵
            continue
        val = _cell_text_el(td)
        m[label] = val
    return m

def _pk_meta_from_tr(tr_el, last_kind=None):
    m = _row_map_by_label_el(tr_el)
    kind      = m.get("종별") or (last_kind or "")
    subkind   = _clean_subkind(m.get("세부종목", ""), log)  # <-- 정제 적용
    matchtype = m.get("경기구분", "")
    sport     = _sport_label_from_tr(tr_el)
    return sport, kind, subkind, matchtype



# =============== 선수명단(대진표) 파싱 (PK 포함) ===============
def parse_bracket_for_all_matches(
    driver,
    start_seq=1,
    max_rows=None,
    click_pause=0.2,
    sidebar_wait=1.0,      # 사이드바 열리고 안정화 대기(초)
    wait_timeout=12,       # WebDriverWait 타임아웃
    retries=1,             # 행 단위 재시도 횟수
    logger=None,
):
    """
    목록의 모든 경기(tr)에 대해 사이드바 '대진표' 정보를 수집한다.
    상세 로깅 포함: 어떤 종목/종별/세부종목/경기구분을 처리 중인지, 성공/실패 및 실패 사유를 출력.
    """
    logger = logger or log
    bracket_rows = []
    row_xpath = ("//table[.//caption[contains(normalize-space(),'시·도 토너먼트 경기일정')]]//tbody/tr")
    seq = start_seq
    idx = 0
    last_kind = ""  # rowspan carry

    def _close_sidebar_safely():
        try:
            close_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'closeBtn')]"))
            )
            driver.execute_script("arguments[0].click();", close_btn)
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.record"))
            )
            return True, None
        except TimeoutException as e:
            return False, f"사이드 닫기 타임아웃: {e}"
        except Exception as e:
            return False, f"사이드 닫기 예외: {type(e).__name__}: {e}"

    while True:
        rows = driver.find_elements(By.XPATH, row_xpath)
        if idx >= len(rows):
            logger.info(f"대진표 파싱 종료: 총 {seq - start_seq}개 행 시도")
            break
        if max_rows and (seq - start_seq) >= max_rows:
            logger.info(f"대진표 파싱 종료(최대 {max_rows}개): 총 {seq - start_seq}개 행 시도")
            break

        tr = rows[idx]
        # 메타 추출(클릭 전) + 종별 carry
        try:
            sport, kind, subkind, matchtype = _pk_meta_from_tr(tr, last_kind)
            if kind:
                last_kind = kind
            global_pk = _build_global_pk(sport, kind, subkind, matchtype)
            logger.info(f"[#{seq}] 대상: 종목='{sport}', 종별='{kind}', 세부종목='{subkind}', 경기구분='{matchtype}', PK='{global_pk}'")
        except Exception as e:
            logger.error(f"[#{seq}] 메타 추출 실패: {type(e).__name__}: {e}")
            # 실패해도 다음 행으로 이동
            seq += 1
            idx += 1
            continue

        # 행 처리 (재시도 포함)
        attempt = 0
        success_for_this_row = False
        fail_reason = None
        local_pk = seq

        while attempt <= retries and not success_for_this_row:
            try:
                # 클릭 타겟 결정
                try:
                    td_click = tr.find_element(By.XPATH, ".//td[contains(@onclick,'openSide')][1]")
                except Exception:
                    td_click = tr.find_element(By.XPATH, "./td[1]")

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", td_click)
                call = td_click.get_attribute("onclick")

                # 사이드 열기
                if call and "openSide" in call:
                    try:
                        driver.execute_script(call.strip().rstrip(";"))
                    except JavascriptException:
                        driver.execute_script("arguments[0].click();", td_click)
                else:
                    driver.execute_script("arguments[0].click();", td_click)

                # 사이드 가시성/콘텐츠 대기
                WebDriverWait(driver, wait_timeout).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.record"))
                )
                WebDriverWait(driver, wait_timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.record .scoreTop"))
                )
                # 참가선수 블록(있다면)도 기다려봄
                try:
                    WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.participating-players > ul"))
                    )
                except TimeoutException:
                    pass  # 없어도 진행

                # 추가 안정화 대기(요청사항 반영)
                time.sleep(sidebar_wait)

                # 파싱
                side_soup = BeautifulSoup(driver.page_source, "lxml")
                title = _build_match_title(side_soup) or "(제목없음)"

                extracted = 0
                part = side_soup.select_one("div.participating-players > ul")
                if part:
                    for team_li in part.find_all("li", recursive=False):
                        h6 = team_li.find("h6")
                        if not h6:
                            continue
                        m = re.search(r"\((.*?)\)", _normalize(h6.get_text(" ", strip=True)))
                        team_name = m.group(1) if m else _normalize(h6.get_text(" ", strip=True))

                        rows_pc = _parse_team_pc_table(team_li, team_name, title, local_pk, global_pk)
                        if rows_pc:
                            bracket_rows.extend(rows_pc)
                            extracted += len(rows_pc)
                        else:
                            mob_rows = _parse_team_mob_list(team_li, team_name, title, local_pk, global_pk)
                            bracket_rows.extend(mob_rows)
                            extracted += len(mob_rows)
                else:
                    fail_reason = "참가선수 섹션 없음(div.participating-players > ul 미존재)"

                # 사이드 닫기
                closed, close_reason = _close_sidebar_safely()
                if not closed:
                    logger.warning(f"[#{seq}] 사이드 닫기 경고: {close_reason}")

                if extracted > 0:
                    logger.info(f"[#{seq}] 성공: '{title}' 선수 {extracted}명 추출 완료")
                    success_for_this_row = True
                else:
                    if not fail_reason:
                        fail_reason = "선수 테이블 파싱 결과 0건"
                    logger.warning(f"[#{seq}] 실패: '{title}' — {fail_reason}")
                    # 재시도 여부 결정
                    if attempt < retries:
                        logger.info(f"[#{seq}] 재시도({attempt+1}/{retries}) 대기 후 진행")
                        time.sleep(0.8)
                    else:
                        break

            except UnexpectedAlertPresentException:
                accepted = accept_alert_if_present(driver, timeout=2)
                if accepted:
                    logger.warning(f"[#{seq}] 경고창 감지 → 확인 처리 후 재시도")
                else:
                    fail_reason = "경고창 처리 실패"
                    logger.error(f"[#{seq}] {fail_reason}")
                    break
            except TimeoutException as e:
                fail_reason = f"타임아웃: {e}"
                logger.error(f"[#{seq}] {fail_reason}")
                if attempt < retries:
                    logger.info(f"[#{seq}] 재시도({attempt+1}/{retries})")
                else:
                    break
            except StaleElementReferenceException as e:
                fail_reason = f"StaleElement: {e}"
                logger.warning(f"[#{seq}] {fail_reason}")
                # 목록 다시 찾아 새 tr로 교체 시도
                try:
                    rows = driver.find_elements(By.XPATH, row_xpath)
                    if idx < len(rows):
                        tr = rows[idx]
                except Exception:
                    pass
                if attempt < retries:
                    logger.info(f"[#{seq}] 재시도({attempt+1}/{retries})")
                else:
                    break
            except JavascriptException as e:
                fail_reason = f"JS 실행 오류: {e}"
                logger.error(f"[#{seq}] {fail_reason}")
                if attempt < retries:
                    logger.info(f"[#{seq}] 재시도({attempt+1}/{retries})")
                else:
                    break
            except Exception as e:
                fail_reason = f"미처리 예외 {type(e).__name__}: {e}"
                logger.error(f"[#{seq}] {fail_reason}")
                break
            finally:
                attempt += 1

        # 다음 행으로 이동
        seq += 1
        idx += 1

    return bracket_rows



# ================= 실행부 =================
if __name__ == "__main__":
    # 로깅 설정: INFO 이상만 보려면 level=logging.INFO, 디버깅까지 보려면 DEBUG
    logging.basicConfig(
        level=logging.INFO,  # 필요시 DEBUG 로 올려도 됨
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    driver = setup_driver(headless=True)
    try:
        open_and_select_jeonnam_all_dates(driver)
        click_load_more_if_exists(driver, max_clicks=40)

        # 스케줄 수집 (PK 포함)
        rows = parse_all_tables(driver)
        df = pd.DataFrame(rows)
        print(f"총 스케줄 행 수: {len(df)}")
        if not df.empty:
            # 저장 컬럼 순서
            cols_sched = ["로컬 PK","글로벌 PK","종목정보","종별","세부종목","경기구분","상태","일시","경기장","시도"]
            df = df[cols_sched]
            df.to_csv("jeonnam_schedule_tournament.csv", index=False, encoding="utf-8-sig")
            print("저장 완료: jeonnam_schedule_tournament.csv")
        else:
            print("스케줄 수집 결과가 비었습니다. 흐름/셀렉터 점검 필요")

        # 선수명단 수집 (PK 포함)
        bracket_rows = parse_bracket_for_all_matches(driver, start_seq=1)
        df_bracket = pd.DataFrame(bracket_rows)
        if not df_bracket.empty:
            cols_bracket = ["로컬 PK","글로벌 PK","경기 제목","팀 구분","출전","선수명","소속[학년]","포지션"]
            df_bracket = df_bracket[cols_bracket]
            df_bracket.to_csv("jeonnam_bracket_tournament.csv", index=False, encoding="utf-8-sig")
            print("저장 완료: jeonnam_bracket_tournament.csv", len(df_bracket))
        else:
            print("선수명단 수집 결과가 비었습니다.")

    finally:
        driver.quit()
