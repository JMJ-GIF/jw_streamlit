import pandas as pd
import streamlit as st
from load_data import get_dataframe_from_gs, clean_dataframe

LEVEL = ['학년', '반', '이름', '성별']
NUMERIC_COLS = ['수비 성공', '패스 시도', '공격 시도']

st.set_page_config(page_title="JFLH 츄크볼", layout="wide")

st.title("🏐 2025. JFLH 츄크볼 리그전 누가기록")

# --- 세션 상태 초기화 ---
if 'df' not in st.session_state:
    st.session_state.df = None

# --- 데이터 불러오기 버튼 ---
if st.button("📥 데이터 가져오기"):
    try:
        df = get_dataframe_from_gs()
        df = clean_dataframe(df)
        st.session_state.df = df  # 세션에 저장
        st.success("데이터를 성공적으로 불러왔습니다.")
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")

# --- 데이터 로딩 여부 확인 ---
df = st.session_state.df
if df is not None:

    # --- LEVEL 선택 ---
    st.sidebar.header("📊 통계 기준 선택")
    level = st.sidebar.selectbox("통계 기준을 선택하세요", LEVEL)

    # --- 날짜 컬럼 자동 감지 ---
    date_col = None
    for col in df.columns:
        if '날짜' in col or 'date' in col.lower():
            try:
                df[col] = pd.to_datetime(df[col])
                date_col = col
                break
            except:
                pass

    # --- 그룹별 통계 ---
    group_df = df.groupby(level)[NUMERIC_COLS].sum().reset_index()
    
    st.subheader(f"🔍 {level}별 통계 요약")
    st.dataframe(group_df)

    for col in NUMERIC_COLS:
        st.markdown(f"### 📈 {level}별 `{col}` 시각화")
        st.bar_chart(group_df.set_index(level)[col])

    # --- 시계열 차트 ---
    if date_col:
        st.subheader("⏳ 날짜별 시계열 통계")
        for col in NUMERIC_COLS:
            st.markdown(f"#### `{col}` 일별 추이")
            time_df = df.groupby(date_col)[col].sum().reset_index()
            st.line_chart(time_df.set_index(date_col))
