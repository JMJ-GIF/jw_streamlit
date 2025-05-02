def get_tabular_data(df):
    table_df = (
        df.groupby(["학년", "반", "학년-반","학년-반-번호","번호", "팀명", "이름", "성별"])
        .agg(
            {
                "수비성공": ["sum", "count"],
                "패스시도": "sum",
                "공격시도": "sum",
            }
        )
        .reset_index()
    )

    table_df.columns = ["_".join(col).strip("_") for col in table_df.columns.values]
    table_df = table_df.rename(
        columns={
            "수비성공_sum": "수비성공",
            "패스시도_sum": "패스시도",
            "공격시도_sum": "공격시도",
            "수비성공_count": "경기수",
        }
    )
    return table_df

def get_agg_df(personal_df, selected_col, match_agg_cols):
    NUMERIC_COLS = ["수비성공", "패스시도", "공격시도"]

    df = get_tabular_data(personal_df)
    grouped_a = df.groupby(selected_col)[NUMERIC_COLS].sum().reset_index()
    if selected_col != "성별":
        grouped_b = df.groupby(match_agg_cols)["경기수"].max().reset_index()
        grouped_b = (
            grouped_b[[selected_col, "경기수"]].groupby(selected_col).sum().reset_index()
        )
    grouped_c = (
        df.groupby(selected_col)["학년-반-번호"].nunique().reset_index(name="학생수")
    )

    grouped = grouped_a.merge(grouped_c, on=selected_col)
    if selected_col != "성별":
        grouped = grouped.merge(grouped_b, on=selected_col)

    return grouped