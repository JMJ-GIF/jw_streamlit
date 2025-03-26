import os


import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


def get_dataframe_from_gs():
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    SHEET_KEY = '1UiUtEfS8yzPanipxC1J1ux2tWzqrjYo3zeuCF0JEuMk'
    SHEET_NAME = 'stat_final'

    if "google" in st.secrets:
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file('secret.json', scopes=SCOPES)
    
    # gspread 클라이언트 생성
    client = gspread.authorize(creds)

    # 시트 열기
    spreadsheet = client.open_by_url(f'https://docs.google.com/spreadsheets/d/{SHEET_KEY}/edit')
    worksheet = spreadsheet.worksheet(SHEET_NAME)

    # 전체 데이터 가져오기
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)

    return df


def clean_dataframe(df):
    
    if '날짜' in df.columns:
        df['날짜'] = pd.to_datetime(df['날짜'], format="%Y.%m.%d")

    # 제외할 열 목록
    exclude_cols = ["날짜", "학년", "반", "번호", "이름", "성별"]

    # 가공 대상 컬럼들만 선택
    target_cols = [col for col in df.columns if col not in exclude_cols]

    # NaN 또는 빈 문자열을 0으로 채우기
    df[target_cols] = df[target_cols].replace('', 0).fillna(0)

    # int로 변환 (혹시 object로 되어 있을 수 있으니)
    df[target_cols] = df[target_cols].astype(int)

    return df

if __name__ == '__main__':
    df = get_dataframe_from_gs()
    df_cleaned = clean_dataframe(df)
    print(df_cleaned.info())  
    print(df_cleaned.columns.tolist())  
    group_df = df_cleaned.groupby('성별')[['수비 성공', '패스 시도', '공격 시도']].sum().reset_index() 
    print(group_df)