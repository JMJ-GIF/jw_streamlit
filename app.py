import pandas as pd
import streamlit as st
from load_data import get_target_sheets_combined_df, clean_dataframe
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
import plotly.express as px

LEVEL = ['학년', '반', '팀', '성별', '개인']
NUMERIC_COLS = ['수비성공', '패스시도', '공격시도']

st.set_page_config(page_title="JFLH 츄크볼", layout="wide")
st.title("🏐 2025. JFLH 츄크볼 리그전 누가기록")

# --- 세션 상태 초기화 ---
if 'df' not in st.session_state:
    st.session_state.df = None

# --- 데이터 불러오기 버튼 ---
if st.button("📥 데이터 가져오기"):
    try:
        df = get_target_sheets_combined_df()  # 구글 스프레드시트에서 불러오기
        df = clean_dataframe(df)      # 전처리
        st.session_state.df = df      # 세션에 저장
        st.success("데이터를 성공적으로 불러왔습니다.")
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")

df = st.session_state.df

# --- 날짜컬럼 자동 감지 ---
date_col = None
if df is not None:
    for col in df.columns:
        if '날짜' in col or 'date' in col.lower():
            try:
                df[col] = pd.to_datetime(df[col])
                date_col = col
                break
            except:
                pass

if df is not None:
    # 탭 대신 라디오 버튼으로 대체 (탭 유지 방지)
    selected_tab = st.radio("📌 통계 기준 선택", LEVEL, horizontal=True)
 
    if selected_tab != '개인':
        if selected_tab in df.columns:
            
            # --- 집계 ---
            if selected_tab == '반':
                # 새로운 컬럼 생성: 예) '1 - 1'
                df['학년 - 반'] = df['학년'].astype(str) + ' - ' + df['반'].astype(str)
                grouped = df.groupby('학년 - 반')[NUMERIC_COLS].sum().reset_index()
                grouped[NUMERIC_COLS] = grouped[NUMERIC_COLS].astype(int)
            else:
                grouped = df.groupby(selected_tab)[NUMERIC_COLS].sum().reset_index()
                grouped[NUMERIC_COLS] = grouped[NUMERIC_COLS].astype(int)


            # --- AgGrid 스타일 빌더 ---
            gb = GridOptionsBuilder.from_dataframe(grouped)

            # 헤더 CSS
            header_css = JsCode("""
            function(params) {
                return {
                    'fontWeight': 'bold',
                    'textAlign': 'center'
                }
            }
            """)

            # 셀 가운데 정렬
            cell_center = {'textAlign': 'center'}

            # 첫 번째 컬럼 스타일 (배경색 + bold)
            first_col_style = {
                'backgroundColor': '#f5f5f5',
                'fontWeight': 'bold',
                'textAlign': 'center'
            }

            # 컬럼별 스타일 적용
            for idx, col in enumerate(grouped.columns):
                is_numeric = col in NUMERIC_COLS

                gb.configure_column(
                    col,
                    headerStyle=header_css,
                    headerName=col,
                    valueFormatter="x.toLocaleString()" if is_numeric else None,
                    cellStyle=first_col_style if idx == 0 else cell_center,
                    type=["numericColumn"] if is_numeric else [],
                )

            # 기타 옵션
            gb.configure_grid_options(domLayout='autoHeight')

            # --- 출력 ---
            st.subheader(f"📊 {selected_tab} 기준 집계표")
            AgGrid(
                grouped,
                gridOptions=gb.build(),
                height=400,
                fit_columns_on_grid_load=True,
                theme="balham",
                allow_unsafe_jscode=True
            )

        else:
            st.warning(f"'{selected_tab}' 열이 데이터프레임에 존재하지 않습니다.")

    else:
        st.subheader("개인별 통계")

        # '이름', '학년', '반', '번호' 컬럼이 모두 있는지 확인
        required_cols = ['이름', '학년', '반', '번호']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            st.warning(f"다음 컬럼이 없어 개인별 식별이 어렵습니다: {missing_cols}")    
        else:
            # 동명이인 구분을 위해 '이름 (학년반번호)' 형태의 표시명을 생성
            # 예: 학년=1, 반=1, 번호=3 → '1103'
            def make_student_id(row):
                # 번호를 2자리로 zero-padding(원하는 대로 조정 가능)
                return f"{row['학년']}{row['반']}{int(row['번호']):02d}"

            # 고유 식별자 + 이름으로 새로운 컬럼을 만든 뒤, selectbox에서 사용
            df['학년반번호'] = df.apply(make_student_id, axis=1)

            # 중복 제거를 위해 필요한 컬럼만 추출
            unique_players = df[['이름', '학년', '반', '번호', '학년반번호']].drop_duplicates()

            # 예: "홍길동 (1103)"
            unique_players['display_name'] = unique_players.apply(
                lambda x: f"{x['이름']} ({x['학년반번호']})", axis=1
            )

            # 개인 선택
            selected_name = st.selectbox("개인 선택", unique_players['display_name'])

            # 선택된 행(이름, 학년, 반, 번호)
            sel_row = unique_players[unique_players['display_name'] == selected_name].iloc[0]

            # 해당 행과 일치하는 전체 기록 추출
            mask = (
                (df['이름'] == sel_row['이름']) &
                (df['학년'] == sel_row['학년']) &
                (df['반'] == sel_row['반']) &
                (df['번호'] == sel_row['번호'])
            )
            player_df = df[mask].copy()

            if date_col:
                player_df.sort_values(by=date_col, inplace=True)

            if date_col and not player_df.empty:
                fig = px.line(
                    player_df, 
                    x=date_col, 
                    y=NUMERIC_COLS, 
                    markers=True,
                    title=f"{selected_name} - 날짜별 통계 추이"
                )
                fig.update_xaxes(dtick="D1", tickformat="%Y-%m-%d")
                fig.update_layout(font=dict(family="Malgun Gothic"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("해당 플레이어에 대한 시계열 데이터를 표시할 수 없습니다.")