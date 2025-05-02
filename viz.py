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