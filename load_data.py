import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]
SHEET_KEY = '1ftwW7xwmiE3mWTzd6VPP45yGJBaZclerS7crCqVk24s'

class PersonalSheet:

    def __init__(self):
        pass

    def clean_dataframe(self, df):
    
        if '날짜' in df.columns:
            df['날짜'] = pd.to_datetime(df['날짜'], format="%Y.%m.%d")

        # 제외할 열 목록
        exclude_cols = ["날짜", "차시", "학년", "반", "번호", "이름", "성별", "팀명"]

        # 가공 대상 컬럼들만 선택
        target_cols = [col for col in df.columns if col not in exclude_cols]

        # NaN 또는 빈 문자열을 0으로 채우기
        df[target_cols] = df[target_cols].replace('', 0).fillna(0)

        # int로 변환 (혹시 object로 되어 있을 수 있으니)
        df[target_cols] = df[target_cols].astype(int)

        return df

    def fetch_df(self):
        
        if "google" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file('secret.json', scopes=SCOPES)
        
        target_sheets = [
            "(1-1)", "(1-2)", "(1-3)", "(1-4)", "(1-5)",
            "(2-1)", "(2-2)", "(2-3)", "(2-4)", "(2-5)"
        ]
        
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SHEET_KEY)

        combined_dfs = []

        for sheet_name in target_sheets:        
            ws = spreadsheet.worksheet(sheet_name)
            values = ws.get_all_values()

            # A~H (0~7): 2행 헤더, 3행부터 데이터
            header_normal = values[1][0:8]
            data_normal = [row[0:8] for row in values[2:] if len(row) >= 8]
            df_normal = pd.DataFrame(data_normal, columns=header_normal)

            # S (18): 수비성공
            defense_data = [row[18] for row in values[2:] if len(row) > 18]
            df_defense = pd.DataFrame(defense_data, columns=["수비성공"])

            # AD (29): 패스시도
            pass_attempt_1 = [row[29] for row in values[2:] if len(row) > 29]
            df_pass_1 = pd.DataFrame(pass_attempt_1, columns=["패스시도"])

            # AO (40): 패스시도
            pass_attempt_2 = [row[40] for row in values[2:] if len(row) > 40]
            df_pass_2 = pd.DataFrame(pass_attempt_2, columns=["공격시도"])

            # 시트명 포함
            df_sheet = pd.concat([df_normal, df_defense, df_pass_1, df_pass_2], axis=1)        

            combined_dfs.append(df_sheet)

        # 모든 시트 데이터 행 방향 결합
        final_df = pd.concat(combined_dfs, ignore_index=True)
        final_df = self.clean_dataframe(final_df)

        return final_df
    
class MatchSheet:

    def __init__(self):
        pass

    def fetch_df(self):
        
        if "google" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file('secret.json', scopes=SCOPES)

        target_sheet = '경기 결과'
        
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SHEET_KEY)

        ws = spreadsheet.worksheet(target_sheet)
        values = ws.get_all_values()

        # A~D 열
        header_normal = values[1][0:4]
        data_normal = [row[0:4] for row in values[2:] if len(row) >= 4]
        df_1 = pd.DataFrame(data_normal, columns=header_normal)

        # F~I 열
        header_normal = values[1][5:9]
        data_normal = [row[5:9] for row in values[2:] if len(row) >= 4]
        df_2 = pd.DataFrame(data_normal, columns=header_normal)

        df_sheet = pd.concat([df_1, df_2], axis=1)        
        
        return df_sheet


if __name__ == '__main__':
    df = MatchSheet().fetch_df()
    
    print(df)

    # df_cleaned = clean_dataframe(df)
    # print(df_cleaned.info())  
    # print(df_cleaned.columns.tolist())  
    # group_df = df_cleaned.groupby('성별')[['수비 성공', '패스 시도', '공격 시도']].sum().reset_index() 
    # print(group_df)