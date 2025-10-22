import time, re
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
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, JavascriptException, UnexpectedAlertPresentException

URL_R = "https://meet.sports.or.kr/national/schedule/scheduleR.do"

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

def accept_all_alerts(driver, tries=6, wait_each=2):
    accepted_any = False
    for _ in range(tries):
        if accept_alert_if_present(driver, timeout=wait_each):
            accepted_any = True
        else:
            break
    return accepted_any

def _normalize(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\xa0", " ").replace("　", " ")
    trans = str.maketrans("０１２３４５６７８９", "0123456789")
    s = re.sub(r"\s+", " ", s.translate(trans)).strip()
    return s

def _build_global_pk(sport, kind, subkind, matchtype):
    # 필요하면 슬래시 등 특수문자 치환을 넣어도 됨(현재는 normalize만)
    return f"{_normalize(sport)}_{_normalize(kind)}_{_normalize(subkind)}_{_normalize(matchtype)}"

def click_load_more_if_exists(driver, max_clicks=30, per_click_pause=0.8):
    wait_short = WebDriverWait(driver, 4)
    clicks = 0
    while clicks < max_clicks:
        try:
            more = wait_short.until(EC.element_to_be_clickable((
                By.XPATH, "//button[normalize-space()='더보기' or contains(.,'더보기')] | //a[normalize-space()='더보기' or contains(.,'더보기')]"
            )))
            driver.execute_script("arguments[0].click();", more)
            time.sleep(per_click_pause)  # ✅ 클릭마다 대기 시간 조절
            clicks += 1
        except Exception:
            break
    return clicks

def wait_tables(driver, timeout=45):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if driver.find_elements(By.XPATH, "//table[.//caption[contains(normalize-space(),'시·도 토너먼트 경기일정')]]"):
                return True
        except UnexpectedAlertPresentException:
            accept_all_alerts(driver)
        time.sleep(0.5)
    return False

def wait_search_results(driver, appear_timeout=40, settle_pause=0.5):
    """
    1) 결과 표가 나타날 때까지 대기
    2) 표가 뜬 뒤 약간 더 대기(애니메이션/DOM 정착)
    """
    ok = wait_tables(driver, timeout=appear_timeout)
    if not ok:
        return False
    if settle_pause and settle_pause > 0:
        time.sleep(settle_pause)
    return True


# ================= 사이드(기록경기 2번째 표) =================
def wait_record_panel_and_table(driver, open_timeout=15, table_timeout=20, poll=0.25):
    """
    1) 사이드 패널(scoreTop) 등장 대기
    2) '기록경기' 두 번째 표가 생길 때까지 폴링
    성공 시 해당 <table> BeautifulSoup 노드 반환, 실패 시 None
    """
    try:
        WebDriverWait(driver, open_timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.record-match-area .scoreTop, div.record .scoreTop"))
        )
    except Exception:
        return None

    end = time.time() + table_timeout
    while time.time() < end:
        try:
            target = _pick_second_record_table_fast(driver)
            if target is not None:
                return target
        except UnexpectedAlertPresentException:
            accept_all_alerts(driver)
        time.sleep(poll)
    return None


def _cell_content(td):
    span = td.find("span", class_="tablesaw-cell-content")
    txt = span.get_text(" ", strip=True) if span else td.get_text(" ", strip=True)
    return _normalize(txt)

def _cell_text_el(td_el):
    try:
        span = td_el.find_element(By.CSS_SELECTOR, "span.tablesaw-cell-content")
        return _normalize(span.text)
    except Exception:
        return _normalize(td_el.text)

def _get_sport_label_for(table):
    h5 = table.find_previous("h5", id="classNm")
    if not h5:
        h5 = table.find_previous("h5", class_="subTit") or table.find_previous("h5")
    return (h5.get_text(" ", strip=True) if h5 else "").strip()

# ================= 초기 진입/필터 =================
def open_jeonnam_only(driver):
    print("[INIT] 페이지 오픈 및 전남 선택")
    wait = WebDriverWait(driver, 20)
    driver.get(URL_R)

    # 시도 버튼 열기
    try:
        sido_btn = wait.until(EC.element_to_be_clickable((By.ID, "sidoCdBtn")))
        driver.execute_script("arguments[0].click();", sido_btn)
    except Exception:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'search-cities-provinces')]")))
        driver.execute_script("arguments[0].click();", btn)

    # '전남' 클릭 → 일자 리스트 채워짐
    try:
        jeonnam_li = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//ul[@id='sidoCdList']//li[contains(@onclick, \"getGmDtList('13','전남')\")]"
        )))
        driver.execute_script("arguments[0].click();", jeonnam_li)
    except Exception:
        jeonnam_li = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//ul[@id='sidoCdList']//li/a[normalize-space()='전남']/parent::li"
        )))
        driver.execute_script("arguments[0].click();", jeonnam_li)

    accept_all_alerts(driver)
    print("  - 전남 선택 완료 (아직 '검색' 안 누름)")

def list_dates(driver):
    btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "gmDtBtn")))
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(0.2)
    soup = BeautifulSoup(driver.page_source, "lxml")
    out = []
    for li in soup.select("#gmDtList > li"):
        if "all" in (li.get("class") or []):
            continue
        txt = li.get_text(" ", strip=True)
        if txt and txt != "전체":
            out.append(txt)
    print(f"[DATES] {len(out)}개 발견: {', '.join(out)}")
    return out

def select_date(driver, date_str):
    print(f"\n=== 날짜 선택: {date_str} ===")
    try:
        driver.execute_script("getClassCdList(arguments[0], arguments[0]);", date_str)
    except JavascriptException:
        btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "gmDtBtn")))
        driver.execute_script("arguments[0].click();", btn)
        li = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((
            By.XPATH, f"//ul[@id='gmDtList']//li[a[normalize-space()='{date_str}']]"
        )))
        driver.execute_script("arguments[0].click();", li)
    time.sleep(0.4)

def list_sports_for_current_date(driver):
    btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "classCdBtn")))
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(0.2)

    soup = BeautifulSoup(driver.page_source, "lxml")
    items = []
    for li in soup.select("#classCdList > li"):
        if "all" in (li.get("class") or []):
            continue
        onclick = li.get("onclick") or ""
        m = re.search(r"selectClassCd\('([^']+)','([^']+)'\)", onclick)
        if m:
            code, name = m.group(1), m.group(2)
        else:
            code, name = "", li.get_text(" ", strip=True)
        items.append((code, name))
    print(f"[SPORTS] {len(items)}개 발견: {', '.join(n for _, n in items)}")
    return items

def select_sport(driver, code, name):
    if code:
        try:
            driver.execute_script("selectClassCd(arguments[0], arguments[1]);", code, name)
            return
        except JavascriptException:
            pass
    btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "classCdBtn")))
    driver.execute_script("arguments[0].click();", btn)
    li = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((
        By.XPATH, f"//ul[@id='classCdList']//li[a[normalize-space()='{name}']]"
    )))
    driver.execute_script("arguments[0].click();", li)

def click_search(driver):
    try:
        search_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((
            By.XPATH, "//button[contains(@class,'searchBtn') or @onclick='javascript:search();']"
        )))
        driver.execute_script("arguments[0].click();", search_btn)
    except Exception:
        pass
    accept_all_alerts(driver, tries=3, wait_each=1)

# ================= 스케줄 생성 =================
def parse_schedule_current_page(driver, start_seq, flt_date, flt_code, flt_name):
    soup = BeautifulSoup(driver.page_source, "lxml")
    seq = start_seq
    rows = []
    for table in soup.select("table.tablesaw.tablesaw-stack"):
        cap = table.select_one("caption")
        if not (cap and "시·도 토너먼트 경기일정" in cap.get_text(strip=True)):
            continue
        sport_label = _get_sport_label_for(table)
        tbody = table.find("tbody")
        if not tbody:
            continue
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 7:
                continue
            r = {
                "로컬 PK": seq,  # 기존 seq
                "종목정보": _normalize(sport_label),
                "종별": _cell_content(tds[0]),
                "세부종목": _cell_content(tds[1]),
                "경기구분": _cell_content(tds[2]),
                "상태": _cell_content(tds[3]),
                "일시": _cell_content(tds[4]),
                "경기장": _cell_content(tds[5]),
                "시도": _cell_content(tds[6]),
                "필터_일자": flt_date,
                "필터_종목코드": flt_code,
                "필터_종목명": flt_name,
            }
            r["글로벌 PK"] = _build_global_pk(r["종목정보"], r["종별"], r["세부종목"], r["경기구분"])
            rows.append(r)
            seq += 1
    return rows, seq

def build_schedule_csv(
    driver,
    out_csv="jeonnam_schedule_split.csv",
    limit_dates=None,
    limit_sports_each=None,
    # ✅ 추가된 파라미터들
    search_result_timeout=40,   # 검색 후 표 등장까지 최대 대기
    results_settle_pause=0.6,   # 표 등장 후 안정화 대기
    max_load_more_clicks=20,    # '더보기' 클릭 최대 횟수
    load_more_pause=0.8         # '더보기' 클릭 사이 간격
):
    open_jeonnam_only(driver)

    dates = list_dates(driver)
    if limit_dates:
        dates = dates[:limit_dates]

    all_sched = []
    seq = 1
    for d in dates:
        select_date(driver, d)
        sports = list_sports_for_current_date(driver)
        if not sports:
            print("  - (해당 일자 종목 없음) 계속 진행")
            continue
        if limit_sports_each:
            sports = sports[:limit_sports_each]

        for code, name in sports:
            print(f"\n[SEARCH] 일자={d} | 종목={name}({code}) → 검색 실행")
            select_sport(driver, code, name)
            click_search(driver)

            # ✅ 검색 결과 대기 (파라미터로 제어)
            if not wait_search_results(
                driver,
                appear_timeout=search_result_timeout,
                settle_pause=results_settle_pause
            ):
                print("  - 결과 표 없음(빈 결과일 수 있음)")
                continue

            # ✅ 더보기 클릭도 간격 제어
            click_load_more_if_exists(
                driver,
                max_clicks=max_load_more_clicks,
                per_click_pause=load_more_pause
            )

            sched_rows, next_seq = parse_schedule_current_page(driver, seq, d, code, name)
            n_matches = next_seq - seq
            print(f"  - 경기일정 {n_matches}건 파싱")
            all_sched.extend(sched_rows)
            seq = next_seq

    if all_sched:
        df_s = pd.DataFrame(all_sched)[[
            "로컬 PK","글로벌 PK","필터_일자","필터_종목코드","필터_종목명",
            "종목정보","종별","세부종목","경기구분","상태","일시","경기장","시도"
        ]]
        df_s.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"\n[저장] {out_csv} | {len(df_s)}행")
        return df_s
    else:
        print("\n[저장] 스케줄 없음")
        return pd.DataFrame(columns=[
            "로컬 PK","글로벌 PK","필터_일자","필터_종목코드","필터_종목명",
            "종목정보","종별","세부종목","경기구분","상태","일시","경기장","시도"
        ])


# ================= PK 메타(행→글로벌PK) =================
def _sport_label_from_tr(tr_el):
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

def _pk_meta_from_tr(tr_el):
    tds = tr_el.find_elements(By.TAG_NAME, "td")
    kind = _cell_text_el(tds[0]) if len(tds) >= 1 else ""
    subkind = _cell_text_el(tds[1]) if len(tds) >= 2 else ""
    matchtype = _cell_text_el(tds[2]) if len(tds) >= 3 else ""
    sport = _sport_label_from_tr(tr_el)
    return sport, kind, subkind, matchtype

# ================= 사이드(기록경기 2번째 표) =================
def _get_onclick_call(td_elem):
    try:
        call = td_elem.get_attribute("onclick")
        if call and "openSide" in call:
            return call.strip().rstrip(";")
    except Exception:
        pass
    return None

def _pick_second_record_table_fast(driver):
    try:
        side = driver.find_element(By.CSS_SELECTOR, "div.record-match-area, div.record")
        html = side.get_attribute("outerHTML")
    except Exception:
        return None
    side_soup = BeautifulSoup(html, "lxml")
    tables = []
    for t in side_soup.select("table.tablesaw.tablesaw-stack"):
        cap = t.select_one("caption")
        if cap and "기록경기" in cap.get_text(strip=True):
            tables.append(t)
    if not tables:
        return None
    return tables[1] if len(tables) >= 2 else tables[0]

def parse_one_match_by_row_index(
    driver,
    row_index,
    local_pk,
    meta,                   # dict: 필터_일자/필터_종목코드/필터_종목명/글로벌 PK
    click_pause=0.05,
    attempts=3,
    log=True,
    side_open_timeout=15,       # ✅ 추가
    record_table_timeout=25     # ✅ 추가
):
    row_xpath = "//table[.//caption[contains(normalize-space(),'시·도 토너먼트 경기일정')]]//tbody/tr"

    for attempt in range(1, attempts + 1):
        status, reason, title_txt, extracted = "FAIL", "", "", 0
        t0 = time.perf_counter()
        try:
            rows = driver.find_elements(By.XPATH, row_xpath)
            if row_index >= len(rows):
                click_load_more_if_exists(driver, max_clicks=3)
                rows = driver.find_elements(By.XPATH, row_xpath)
                if row_index >= len(rows):
                    reason = f"행 인덱스 {row_index}가 범위를 벗어남(len={len(rows)})"
                    if log:
                        print(f"[{local_pk:04d}] {status} | rows=0 | (attempt {attempt}/{attempts}) | {reason} | {time.perf_counter()-t0:.2f}s", flush=True)
                    continue

            tr = rows[row_index]
            td1 = tr.find_element(By.XPATH, "./td[1]")

            call = _get_onclick_call(td1)
            if call:
                try:
                    driver.execute_script(call)
                except JavascriptException:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", td1)
                    driver.execute_script("arguments[0].click();", td1)
            else:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", td1)
                driver.execute_script("arguments[0].click();", td1)

            # 클릭 후 약간 정지(스크롤/애니메이션 안정화)
            time.sleep(click_pause)

            # ✅ 사이드 패널/두번째 표를 '충분히' 기다림
            target = wait_record_panel_and_table(
                driver,
                open_timeout=side_open_timeout,
                table_timeout=record_table_timeout,
                poll=0.25
            )

            # (로깅용 제목)
            try:
                st = driver.find_element(By.CSS_SELECTOR, "div.record-match-area .scoreTop, div.record .scoreTop")
                title_txt = st.text.replace("\xa0"," ").strip()
            except Exception:
                title_txt = ""

            rows_out = []
            if target:
                tbody = target.find("tbody")
                if tbody:
                    for tr2 in tbody.find_all("tr"):
                        if tr2.find("td", class_="no-result"):
                            continue
                        tds = tr2.find_all("td")
                        if len(tds) < 7:
                            continue
                        row = {
                            "로컬 PK": local_pk,
                            "글로벌 PK": meta.get("글로벌 PK",""),
                            "필터_일자": meta.get("필터_일자",""),
                            "필터_종목코드": meta.get("필터_종목코드",""),
                            "필터_종목명": meta.get("필터_종목명",""),
                            "순위": _cell_content(tds[0]),
                            "시도": _cell_content(tds[1]),
                            "선수명": _cell_content(tds[2]),
                            "소속": _cell_content(tds[3]),
                            "학년": _cell_content(tds[4]),
                            "기록": _cell_content(tds[5]),
                            "신기록/비고": _cell_content(tds[6]),
                        }
                        rows_out.append(row)
                else:
                    reason = "기록경기 tbody 없음"
            else:
                reason = "기록경기 두 번째 표 로딩 시간 초과"

            # 닫기
            try:
                close_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'closeBtn')]"))
                )
                driver.execute_script("arguments[0].click();", close_btn)
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.record-match-area, div.record"))
                )
            except TimeoutException:
                pass

            extracted = len(rows_out)
            if extracted > 0:
                status = "OK"
                if log:
                    short = (title_txt[:80]+"…") if len(title_txt) > 80 else title_txt
                    print(f"[{local_pk:04d}] {status} | rows={extracted:>2} | {short} | {meta.get('필터_일자','')} / {meta.get('필터_종목명','')} | {time.perf_counter()-t0:.2f}s", flush=True)
                return rows_out, True
            else:
                if not reason:
                    reason = "표는 있었으나 데이터 행이 없음(미종료/빈값)"

        except TimeoutException:
            reason = "사이드 패널 대기 시간 초과"
        except StaleElementReferenceException:
            reason = "StaleElement(재렌더)"
        except Exception as e:
            reason = f"예외: {type(e).__name__}: {str(e)[:160]}"

        if log:
            print(f"[{local_pk:04d}] {status} | rows=0 | (attempt {attempt}/{attempts}) | {reason} | {time.perf_counter()-t0:.2f}s", flush=True)
        time.sleep(0.3)

    return [], False


# ================= 유틸: 누락 탐지/매핑 =================
def find_missing_ids(records_csv_path, total_max=906, col_name="로컬 PK"):
    df = pd.read_csv(records_csv_path)
    have = set(pd.to_numeric(df[col_name], errors="coerce").dropna().astype(int).unique())
    all_ids = set(range(1, total_max + 1))
    missing = sorted(all_ids - have)
    print(f"[MISSING] 총 {len(missing)}개 누락: {missing[:20]}{' ...' if len(missing) > 20 else ''}")
    return missing

def build_seq_to_page_index(schedule):
    """
    schedule: DataFrame 또는 CSV 경로
    반환: dict[로컬PK] -> {필터_일자, 필터_종목코드, 필터_종목명, 글로벌 PK, row_index_in_page}
    """
    if isinstance(schedule, str):
        s = pd.read_csv(schedule)
    else:
        s = schedule.copy()

    need = ["로컬 PK","필터_일자","필터_종목코드","필터_종목명"]
    for c in need:
        if c not in s.columns:
            raise ValueError("스케줄에 필요한 컬럼이 없습니다: " + ", ".join(need))

    if "글로벌 PK" not in s.columns:
        for col in ["종목정보","종별","세부종목","경기구분"]:
            if col not in s.columns:
                raise ValueError("글로벌 PK 생성에 필요한 스케줄 컬럼(종목정보/종별/세부종목/경기구분)이 없습니다.")
        s["글로벌 PK"] = s.apply(lambda r: _build_global_pk(r["종목정보"], r["종별"], r["세부종목"], r["경기구분"]), axis=1)

    s = s.sort_values(["필터_일자","필터_종목코드","필터_종목명","로컬 PK"]).reset_index(drop=True)
    s["row_index_in_page"] = s.groupby(["필터_일자","필터_종목코드","필터_종목명"]).cumcount()

    seq_map = s.set_index("로컬 PK")[["필터_일자","필터_종목코드","필터_종목명","글로벌 PK","row_index_in_page"]].to_dict(orient="index")
    return seq_map

def ensure_page_loaded_for(driver, date_str, code, name):
    select_date(driver, date_str)
    select_sport(driver, code, name)
    click_search(driver)
    ok = wait_tables(driver, timeout=40)
    if not ok:
        print("  - [WARN] 결과 표 없음(빈 결과일 수 있음)")
        return False
    click_load_more_if_exists(driver, max_clicks=20)
    return True

# ================= 백필(backfill) =================
def backfill_missing_records(
    driver,
    schedule,
    records_csv="jeonnam_records_split.csv",
    out_csv="jeonnam_records_backfill.csv",
    attempts_each=3,
    side_open_timeout=15,       # ✅ 추가
    record_table_timeout=25,    # ✅ 추가
    panel_settle_pause=0.10     # ✅ 추가 (클릭 직후 pause)
):
    # total_max는 필요 시 외부에서 주입하거나, 스케줄 DF 기준 max 로컬PK 사용 가능
    if isinstance(schedule, str):
        s = pd.read_csv(schedule)
    else:
        s = schedule.copy()
    total_max = int(s["로컬 PK"].max()) if not s.empty else 0

    missing_ids = find_missing_ids(records_csv, total_max=total_max, col_name="로컬 PK")
    if not missing_ids:
        print("[INFO] 누락 없음. 종료.")
        return

    seq_map = build_seq_to_page_index(s)

    from collections import defaultdict
    buckets = defaultdict(list)
    for seq_id in missing_ids:
        info = seq_map.get(seq_id)
        if not info:
            print(f"[WARN] schedule에 {seq_id} 매핑 없음 → 건너뜀")
            continue
        key = (info["필터_일자"], info["필터_종목코드"], info["필터_종목명"])
        buckets[key].append((seq_id, info))

    results = []
    for (d, code, name), items in buckets.items():
        print(f"\n=== 백필 화면 오픈: 일자={d} | 종목={name}({code}) | 대상 {len(items)}건 ===")
        if not ensure_page_loaded_for(driver, d, code, name):
            print("  - 화면 로딩 실패 → 스킵")
            continue

        items.sort(key=lambda x: x[1]["row_index_in_page"])
        for local_pk, info in items:
            meta = {
                "필터_일자": info["필터_일자"],
                "필터_종목코드": info["필터_종목코드"],
                "필터_종목명": info["필터_종목명"],
                "글로벌 PK": info["글로벌 PK"],
            }
            rows_out, success = parse_one_match_by_row_index(
                driver,
                row_index=info["row_index_in_page"],
                local_pk=local_pk,
                meta=meta,
                attempts=attempts_each,
                click_pause=panel_settle_pause,           # ✅ 전달
                side_open_timeout=side_open_timeout,      # ✅ 전달
                record_table_timeout=record_table_timeout # ✅ 전달
            )
            if success:
                results.extend(rows_out)
            else:
                print(f"[FAIL] 경기 {local_pk} 재수집 실패(최대 {attempts_each}회 시도)")

    if results:
        df = pd.DataFrame(results)[[
            "로컬 PK","글로벌 PK","필터_일자","필터_종목코드","필터_종목명",
            "순위","시도","선수명","소속","학년","기록","신기록/비고"
        ]]
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"\n[저장] backfill 결과: {out_csv} | {len(df)}행")
    else:
        print("\n[저장] backfill 결과 없음")

# ================= 전체 재수집(최초 실행 모드로 사용) =================
def recrawl_all_with_retry(
    driver,
    schedule,
    out_csv="jeonnam_records_rescrape.csv",
    attempts_each=2,
    side_open_timeout=15,       # ✅ 추가
    record_table_timeout=25,    # ✅ 추가
    panel_settle_pause=0.10     # ✅ 추가
):
    if isinstance(schedule, str):
        s = pd.read_csv(schedule)
    else:
        s = schedule.copy()

    if "글로벌 PK" not in s.columns:
        for col in ["종목정보","종별","세부종목","경기구분"]:
            if col not in s.columns:
                raise ValueError("글로벌 PK 생성에 필요한 스케줄 컬럼이 없습니다.")
        s["글로벌 PK"] = s.apply(lambda r: _build_global_pk(r["종목정보"], r["종별"], r["세부종목"], r["경기구분"]), axis=1)

    s = s.sort_values(["필터_일자","필터_종목코드","필터_종목명","로컬 PK"]).reset_index(drop=True)
    s["row_index_in_page"] = s.groupby(["필터_일자","필터_종목코드","필터_종목명"]).cumcount()

    results = []
    for (d, code, name), grp in s.groupby(["필터_일자","필터_종목코드","필터_종목명"], sort=False):
        print(f"\n=== 전체 재수집 화면: 일자={d} | 종목={name}({code}) | 경기 {len(grp)}건 ===")
        if not ensure_page_loaded_for(driver, d, code, name):
            print("  - 화면 로딩 실패 → 그룹 스킵")
            continue

        for _, r in grp.iterrows():
            local_pk = int(r["로컬 PK"])
            row_idx  = int(r["row_index_in_page"])
            meta = {
                "필터_일자": d,
                "필터_종목코드": code,
                "필터_종목명": name,
                "글로벌 PK": r["글로벌 PK"],
            }
            rows_out, success = parse_one_match_by_row_index(
                driver,
                row_index=row_idx,
                local_pk=local_pk,
                meta=meta,
                attempts=attempts_each,
                click_pause=panel_settle_pause,           # ✅ 전달
                side_open_timeout=side_open_timeout,      # ✅ 전달
                record_table_timeout=record_table_timeout # ✅ 전달
            )
            if success:
                results.extend(rows_out)
            else:
                print(f"[FAIL] 경기 {local_pk} 재수집 실패(최대 {attempts_each}회 시도)")

    if results:
        df = pd.DataFrame(results)[[
            "로컬 PK","글로벌 PK","필터_일자","필터_종목코드","필터_종목명",
            "순위","시도","선수명","소속","학년","기록","신기록/비고"
        ]]
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"\n[저장] 전체 재수집 결과: {out_csv} | {len(df)}행")
    else:
        print("\n[저장] 전체 재수집 결과 없음")

def backfill_bracket_matches(driver):
    # 전남만 선택(검색은 여기서 하지 않음)
    open_jeonnam_only(driver)

    # 스케줄/레코드 파일 경로를 문자열로 지정
    schedule_path = "jeonnam_schedule_matches.csv"   
    records_path  = "jeonnam_bracket_matches.csv" 
    backfill_path = "jeonnam_bracket_backfill.csv"  
    # 3) (옵션) 백필만 별도로 돌리고 싶으면 주석 해제
    backfill_missing_records(
        driver,
        schedule=schedule_path,
        records_csv=records_path,
        out_csv=backfill_path,
        attempts_each=3,
        side_open_timeout=20,       # ← 패널 등장 최대 20초
        record_table_timeout=45,    # ← 두번째 표 최대 45초
        panel_settle_pause=0.15     # ← 클릭 후 살짝 더 길게 쉼
    )
    split_df = pd.read_csv(records_path)
    backfill_df = pd.read_csv(backfill_path)
    df = (
        pd.concat([split_df, backfill_df])
        .sort_values(by="로컬 PK")
        .reset_index(drop=True)
    )
    df.to_csv(records_path, index=False)

# ================= 실행부 =================
if __name__ == "__main__":
    driver = setup_driver(headless=True)
    try:
        # 1) 스케줄 생성(로컬 PK/글로벌 PK 포함)
        schedule_df = build_schedule_csv(
            driver,
            out_csv="jeonnam_schedule_matches.csv",
            search_result_timeout=60,   # 표 등장 최대 60초
            results_settle_pause=1.2,   # 표 뜬 뒤 1.2초 더 대기
            max_load_more_clicks=40,    # 더보기 최대 40회
            load_more_pause=1.0         # 더보기 사이 1초 간격
        )

        # 2) 최초 실행 모드: 방금 생성한 스케줄로 전체 재수집
        recrawl_all_with_retry(
            driver,
            schedule=schedule_df,       # DF 또는 CSV 경로 사용 가능
            out_csv="jeonnam_bracket_matches.csv",
            attempts_each=3,            
            side_open_timeout=20,       # ← 패널 등장 최대 20초
            record_table_timeout=45,    # ← 두번째 표 최대 45초
            panel_settle_pause=0.15     # ← 클릭 후 살짝 더 길게 쉼
        )

        # backfill_bracket_matches(driver)

        
    finally:
        driver.quit()
