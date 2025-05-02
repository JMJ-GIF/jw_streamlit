import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from preprocess import get_agg_df
from load_data import MatchSheet, PersonalSheet
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

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
        personal_df = PersonalSheet().fetch_df()   
        personal_df['학년-반'] = personal_df['학년'].astype(str) + '_' + personal_df['반'].astype(str)  
        personal_df['학년-반-번호'] = personal_df['학년'].astype(str) + '-' + personal_df['반'].astype(str) + '-' + personal_df['번호'].astype(str)   
        st.session_state.df = personal_df      
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
 
    if selected_tab == '학년':
        selected_col = '학년'
        match_agg_cols = ['학년', '반', '팀명']
        grouped = get_agg_df(df, selected_col, match_agg_cols)      
        
        if grouped.empty:
            st.info("표시할 데이터가 없습니다.")
        else:
            # ───────────────────────────────            
            grouped['수비성공_경기당'] = grouped['수비성공'] / grouped['경기수']
            grouped['패스시도_경기당'] = grouped['패스시도'] / grouped['경기수']
            grouped['공격시도_경기당'] = grouped['공격시도'] / grouped['경기수']
            
            grouped['수비성공_인원당'] = grouped['수비성공'] / grouped['학생수']
            grouped['패스시도_인원당'] = grouped['패스시도'] / grouped['학생수']
            grouped['공격시도_인원당'] = grouped['공격시도'] / grouped['학생수']

            metrics = ['수비성공', '패스시도', '공격시도']

            def create_radar_chart(df, value_cols, title):
                fig = go.Figure()

                for _, row in df.iterrows():
                    values = [row[col] for col in value_cols]
                    fig.add_trace(go.Scatterpolar(
                        r=values + [values[0]],  # 닫힌 도형을 위해 첫 값 반복
                        theta=metrics + [metrics[0]],
                        fill='toself',
                        name=f"{row['학년']}학년"
                    ))

                fig.update_layout(
                    title=title,
                    polar=dict(
                        radialaxis=dict(visible=True),
                    ),
                    showlegend=True
                )
                return fig

            col1, col2 = st.columns(2)

            with col1:
                st.subheader("🎯 경기당 평균 지표 (학년별)")
                radar1 = create_radar_chart(
                    grouped,
                    ['수비성공_경기당', '패스시도_경기당', '공격시도_경기당'],
                    title="경기당 평균"
                )
                st.plotly_chart(radar1, use_container_width=True)

            with col2:
                st.subheader("👤 인원당 평균 지표 (학년별)")
                radar2 = create_radar_chart(
                    grouped,
                    ['수비성공_인원당', '패스시도_인원당', '공격시도_인원당'],
                    title="인원당 평균"
                )
                st.plotly_chart(radar2, use_container_width=True)

            st.subheader(f"📊 {selected_tab} 기준 집계표")        
            st.dataframe(grouped.drop(['수비성공_경기당', '패스시도_경기당', '공격시도_경기당','수비성공_인원당', '패스시도_인원당', '공격시도_인원당'], axis = 1))  

    elif selected_tab == '반':
        selected_col = '학년-반'
        match_agg_cols = ['학년-반', '팀명']
        grouped = get_agg_df(df, selected_col, match_agg_cols)

        st.subheader(f"📊 {selected_tab} 기준 집계표")

        if grouped.empty:
            st.info("표시할 데이터가 없습니다.")
        else:
            # ─── 계산 컬럼 추가 ───
            grouped['수비성공_경기당'] = grouped['수비성공'] / grouped['경기수']
            grouped['패스시도_경기당'] = grouped['패스시도'] / grouped['경기수']
            grouped['공격시도_경기당'] = grouped['공격시도'] / grouped['경기수']

            grouped['수비성공_인원당'] = grouped['수비성공'] / grouped['학생수']
            grouped['패스시도_인원당'] = grouped['패스시도'] / grouped['학생수']
            grouped['공격시도_인원당'] = grouped['공격시도'] / grouped['학생수']

            # ─── 그래프용 형태로 변환 ───
            def make_melted_df(df, cols, value_name):
                return df.melt(
                    id_vars=['학년-반'],
                    value_vars=cols,
                    var_name='지표',
                    value_name=value_name
                )

            # 1) 경기당
            game_avg_df = make_melted_df(
                grouped,
                ['수비성공_경기당', '패스시도_경기당', '공격시도_경기당'],
                value_name='경기당 평균'
            )
            game_avg_df['지표'] = game_avg_df['지표'].str.replace('_경기당', '')

            # 2) 인원당
            student_avg_df = make_melted_df(
                grouped,
                ['수비성공_인원당', '패스시도_인원당', '공격시도_인원당'],
                value_name='인원당 평균'
            )
            student_avg_df['지표'] = student_avg_df['지표'].str.replace('_인원당', '')

            # ─── 시각화: 2열 구성 ───
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("🎯 경기당 평균 (반별)")
                fig1 = px.bar(
                    game_avg_df,
                    x='학년-반',
                    y='경기당 평균',
                    color='지표',
                    barmode='group',
                    title='반별 경기당 평균 지표'
                )
                fig1.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig1, use_container_width=True)

            with col2:
                st.subheader("👤 인원당 평균 (반별)")
                fig2 = px.bar(
                    student_avg_df,
                    x='학년-반',
                    y='인원당 평균',
                    color='지표',
                    barmode='group',
                    title='반별 인원당 평균 지표'
                )
                fig2.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig2, use_container_width=True)

            # 마지막에 원래 표도 보여주기
            st.dataframe(grouped.drop(columns=[
                '수비성공_경기당', '패스시도_경기당', '공격시도_경기당',
                '수비성공_인원당', '패스시도_인원당', '공격시도_인원당'
            ]))

    
    elif selected_tab == '팀':
        selected_col = '팀명'
        match_agg_cols = ['학년-반', '팀명']
        grouped = get_agg_df(df, selected_col, match_agg_cols)

        st.subheader(f"📊 {selected_tab} 기준 집계표")
        if grouped.empty:
            st.info("표시할 데이터가 없습니다.")
        else:
            st.dataframe(grouped)

    elif selected_tab == '성별':
        selected_col = '성별'
        match_agg_cols = ['학년-반', '팀명']
        grouped = get_agg_df(df, selected_col, match_agg_cols)

        st.subheader(f"📊 {selected_tab} 기준 집계표")
        if grouped.empty:
            st.info("표시할 데이터가 없습니다.")
        else:
            st.dataframe(grouped)

    
    elif selected_tab == '개인':
        st.subheader("개인별 통계")

        required_cols = ['이름', '학년', '반', '번호', '팀명']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            st.warning(f"다음 컬럼이 없어 개인별 식별이 어렵습니다: {missing_cols}")    
        else:
            # 👉 1. 학년, 반, 팀 선택을 한 줄 3열로 배치
            col1, col2, col3 = st.columns(3)

            with col1:
                selected_grade = st.selectbox("학년 선택", sorted(df['학년'].dropna().unique()))

            filtered_by_grade = df[df['학년'] == selected_grade]

            with col2:
                selected_class = st.selectbox("반 선택", sorted(filtered_by_grade['반'].dropna().unique()))

            filtered_by_class = filtered_by_grade[filtered_by_grade['반'] == selected_class]

            with col3:
                selected_team = st.selectbox("팀 선택", sorted(filtered_by_class['팀명'].dropna().unique()))

            # 👉 2. 조건에 맞는 데이터 필터링
            filtered_df = filtered_by_class[filtered_by_class['팀명'] == selected_team]

            if filtered_df.empty:
                st.info("선택된 조건에 해당하는 학생이 없습니다.")
            else:
                # 학년반번호 생성
                filtered_df['학년반번호'] = filtered_df.apply(
                    lambda row: f"{row['학년']}{row['반']}{int(row['번호']):02d}", axis=1
                )

                unique_players = filtered_df[['이름', '번호', '학년반번호']].drop_duplicates()
                unique_players['display_name'] = unique_players.apply(
                    lambda x: f"{x['이름']} ({x['학년반번호']})", axis=1
                )

                # 👉 3. 개인 선택 및 시각화 부분을 1:5 비율의 2열로 나눔
                left_col, right_col = st.columns([1, 5])

                with left_col:
                    selected_name = st.selectbox("개인 선택", unique_players['display_name'])

                with right_col:
                    sel_row = unique_players[unique_players['display_name'] == selected_name].iloc[0]
                    mask = (
                        (filtered_df['이름'] == sel_row['이름']) &
                        (filtered_df['번호'] == sel_row['번호'])
                    )
                    player_df = filtered_df[mask].copy()

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
