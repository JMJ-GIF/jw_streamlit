import json
import numpy as np
import pandas as pd


def split_affil_and_grade(df, col="소속[학년]"):
    # 소속(아무 문자) + 선택적으로 [학년숫자] 캡처 (전각/반각 숫자 모두)
    pat = r"^\s*(?P<소속>.*?)\s*(?:\[(?P<학년>[0-9０-９]+)\])?\s*$"
    tmp = df[col].astype(str).str.extract(pat)

    # 소속: 대괄호가 없던 행은 원본 문자열을 그대로 사용
    df["소속"] = tmp["소속"].where(tmp["소속"].notna(), df[col])

    # 학년: 전각숫자 -> 반각으로 치환
    trans = str.maketrans("０１２３４５６７８９", "0123456789")
    df["학년"] = tmp["학년"].str.translate(trans)

    # 원본 컬럼을 유지할지 제거할지 선택
    # df.drop(columns=[col], inplace=True)  # 원하면 주석 해제해서 원본 삭제

    return df


def players_per_match(df, pk_col="글로벌 PK"):
    need = [pk_col, "선수명", "소속", "학년"]
    df = df[need].copy()
    df = df.dropna(subset=[pk_col])

    # 학년 숫자화
    df["학년"] = pd.to_numeric(df["학년"], errors="coerce")

    # 경기별 선수 리스트(기존) + 줄바꿈 문자열(신규)
    out = (
        df.groupby(pk_col, sort=False)
        .apply(
            lambda g: [
                {
                    "선수명": r["선수명"],
                    "소속": r["소속"],
                    "학년": (int(r["학년"]) if pd.notna(r["학년"]) else None),
                }
                for _, r in g[["선수명", "소속", "학년"]].iterrows()
            ]
        )
        .reset_index(name="선수목록")
    )

    # "소속/학년/선수명" 줄바꿈 포맷
    def _format_lines(players):
        lines = []
        for p in players:
            parts = [p["소속"]]
            if p["학년"] is not None:
                parts.append(str(p["학년"]))
            parts.append(p["선수명"])
            lines.append("/".join(parts))
        return "\n".join(lines)

    out["선수목록_줄바꿈"] = out["선수목록"].apply(_format_lines)
    return out


def stadium_and_date_handling(df):
    df["일자"] = df["일시"].str.split(" ").str[0]
    df["시간"] = df["일시"].str.split(" ", n=1).str[1]

    # 원하는 형식의 '경기장 및 시간' 컬럼 생성
    df["경기장 및 시간"] = df["시간"] + " " + df["경기장"]

    # 기존 컬럼 정리
    df = df.drop(["일시", "시간"], axis=1)

    return df

import re
import numpy as np
import pandas as pd

def _norm(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    return re.sub(r"\s+", " ", str(s).replace("\xa0"," ").strip())

def _parse_time_place(s: str):
    """'경기장 및 시간'에서 시간(단일/구간)과 장소를 분리"""
    raw = _norm(s)
    # 시간: HH:MM 또는 "HH:MM ~ HH:MM"
    m = re.search(r"(\d{1,2}:\d{2}(?:\s*[~\-]\s*\d{1,2}:\d{2})?)", raw)
    if m:
        time_str = m.group(1).strip()
        # 시간 부분 제거하고 나머지를 장소로
        place = (raw[:m.start()] + raw[m.end():]).strip(" -–~")
        place = _norm(place)
    else:
        # 시간 패턴이 없으면 전부를 장소로 처리
        time_str = ""
        place = raw
    return time_str, place

def _extract_opponent(sido: str, our_team: str = "전남"):
    """
    '시도' 문자열(예: '전남 : 세종', '경북 : 전남', ': 전남', '전남 :')에서
    전남이 아닌 쪽을 상대팀으로 추출. 없으면 None.
    """
    t = _norm(sido).replace("：", ":")
    if not t:
        return None

    if ":" in t:
        left, right = [p.strip() for p in t.split(":", 1)]
        if our_team in left:
            opp = right
        elif our_team in right:
            opp = left
        else:
            # 전남이 명시 안되어 있으면 추출 불가
            return None
        opp = _norm(opp)
        return opp or None

    # 예외적으로 'A vs B', 'A 대 B' 형태 처리
    m = re.split(r"\s*(?:vs|VS|Vs|대)\s*", t)
    if len(m) == 2:
        a, b = m[0].strip(), m[1].strip()
        if our_team in a:
            return _norm(b) or None
        if our_team in b:
            return _norm(a) or None

    return None

def _format_cell_value(time_place: str, sido: str, our_team: str = "전남"):
    time_str, place = _parse_time_place(time_place)
    opp = _extract_opponent(sido, our_team=our_team)

    lines = []
    if time_str:
        lines.append(f"- {time_str}")
    if place:
        lines.append(f"- {place}")
    if opp:
        lines.append(f"- {opp}")
    return "\n".join(lines)

def add_structured_date_columns(
    df: pd.DataFrame,
    date_col: str = "일자",
    schedule_col: str = "경기장 및 시간",
    sido_col: str = "시도",
    our_team: str = "전남",
    fill_if_not_match=np.nan,
    prefix: str = ""
):
    """
    '일자'의 유니크 값마다 새 컬럼을 만들고,
    해당 행에는 '- 시간\\n- 장소\\n- 상대팀' 포맷을 채운다(상대팀 없으면 시간/장소만).
    기존 컬럼은 변경하지 않는다.
    """
    for col in (date_col, schedule_col, sido_col):
        if col not in df.columns:
            raise KeyError(f"필수 컬럼 누락: {col}")

    dates = df[date_col].astype(str).fillna("")
    uniques = list(dict.fromkeys(dates))  # 순서 유지

    # 행별 준비된 콘텐츠(시간/장소/상대팀)
    contents = [
        _format_cell_value(tp, sd, our_team=our_team)
        for tp, sd in zip(df[schedule_col], df[sido_col])
    ]

    new_cols = []
    for raw_name in uniques:
        base = f"{prefix}{raw_name}"
        name = base
        k = 2
        while name in df.columns or name in new_cols:
            name = f"{base}_{k}"
            k += 1
        df[name] = np.where(dates == raw_name, contents, fill_if_not_match)
        new_cols.append(name)

    return df, new_cols




if __name__ == "__main__":
    # 스케줄
    schedule_cols = [
        "글로벌 PK",
        "종목정보",
        "종별",
        "세부종목",
        "경기구분",
        "상태",
        "일시",
        "경기장",
        "시도",
    ]
    schedule_tournament = pd.read_csv("jeonnam_schedule_tournament.csv")
    schedule_matches = pd.read_csv("jeonnam_schedule_matches.csv")

    schedule_df = pd.concat(
        [schedule_tournament[schedule_cols], schedule_matches[schedule_cols]]
    ).reset_index(drop=True)
    schedule_df = stadium_and_date_handling(schedule_df)

    # 선수목록
    bracket_cols = ["글로벌 PK", "선수명", "소속", "학년", "시도"]
    bracket_tournament = split_affil_and_grade(
        pd.read_csv("jeonnam_bracket_tournament.csv")
    ).rename(columns={"팀 구분": "시도"})
    bracket_matches = pd.read_csv("jeonnam_bracket_matches.csv")
    bracket_df = pd.concat(
        [bracket_tournament[bracket_cols], bracket_matches[bracket_cols]]
    ).reset_index(drop=True)
    bracket_df = bracket_df[bracket_df["시도"] == "전남"]
    bracket_json_df = players_per_match(bracket_df)

    # 조인
    db_data = pd.merge(schedule_df, bracket_json_df, on="글로벌 PK", how='left')
    db_data, added_cols = add_structured_date_columns(
        db_data,
        date_col="일자",
        schedule_col="경기장 및 시간",
        sido_col="시도",
        our_team="전남",
        fill_if_not_match=""   # 빈칸으로 두고 싶으면 "", 아니면 np.nan
    )

    # 컬럼이름 변경
    db_data = db_data.rename(
        columns={
            "종목정보": "부문",
            "종별": "종별",
            "세부종목": "세부종목",
            "경기구분": "라운드히트",
            "경기장": "경기장",
            "시도": "상대 시도",
            "일자": "시작일",
        }
    )

    # 포맷변경
    db_data["시작일"] = pd.to_datetime(db_data["시작일"], errors="coerce").dt.strftime("%Y-%m-%d")

    # 이름열 추가
    db_data["이름"] = db_data["부문"] + "-" + db_data["종별"] + "-" + db_data["세부종목"]

    # 시간 추출 (단일 시간 또는 "HH:MM ~ HH:MM")
    time_any_pattern = r'(\d{1,2}:\d{2}(?:\s*~\s*\d{1,2}:\d{2})?)'
    db_data["경기 시간"] = db_data["경기장 및 시간"].str.extract(time_any_pattern)
    db_data["경기 시간"] = db_data["경기 시간"].str.replace(r"\s*~\s*", "-", regex=True)

    # 시작/종료시간 개별 추출
    db_data[["시작시간", "종료시간"]] = db_data["경기장 및 시간"].str.extract(
        r'(\d{1,2}:\d{2})\s*~\s*(\d{1,2}:\d{2})?'
    )

    # 종료일 컬럼 
    db_data["종료일"] = np.nan

    # 메달 여부
    cond = db_data["라운드히트"].astype("string").str.contains("결승", na=False)
    db_data["메달 여부"] = pd.Series(pd.NA, index=db_data.index, dtype="string")
    db_data.loc[cond, "메달 여부"] = "메달발생"

    df = db_data[
        [
            "이름",
            "경기 시간",
            "부문",
            "종별",
            "세부종목",
            "라운드히트",
            "시작일",
            "시작시간",
            "종료일",
            "종료시간",
            "메달 여부",
            "경기장",
            "상대 시도",
            "선수목록_줄바꿈",
        ]
    ]


    db_data.to_csv("sido_crawling_db_data.csv", index=False)
    db_data.to_excel("sido_crawling_db_data.xlsx", index=False)
