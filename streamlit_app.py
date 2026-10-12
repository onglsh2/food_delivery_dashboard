"""
7주차 1번 수업: 시작 코드(필터 없음)
6주차 시각화 리포트와 같은 형태입니다. 오늘 여기에 필터를 붙여 대시보드로 만듭니다.
"""
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="사용자 행동 탐색 대시보드", layout="wide")
st.title("사용자 행동 탐색 대시보드")
st.caption("주별 세션 퍼널 | 플랫폼 · 유입 경로별 | 2025.07 ~ 2026.06")

# ------------------------------------------------------------
# 0. 필요한 데이터만 추출 — 쓸 테이블과 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 처음 한 번만 만듦
# ------------------------------------------------------------
DATA_DIR = "data"                          # 원본 CSV를 넣어 둔 폴더
NEEDED = {                                 # 이번 대시보드에 필요한 테이블과 컬럼
    "app_events": ["event_id", "event_datetime", "customer_id", "session_id",
                   "event_name", "platform", "traffic_source"],
}

@st.cache_resource
def get_db():                              # 필요한 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 만듦 (처음 한 번만)
    con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, cols in NEEDED.items():
       
        pd.read_csv(f"{DATA_DIR}/{name}.csv", usecols=cols).to_sql(name, con, index=False)
    # 5주차 제외 규칙: QA 계정 제외 · 중복 이벤트 제거
    con.execute("""
        CREATE TABLE events AS
        SELECT event_id, event_datetime, customer_id, session_id, event_name, platform, traffic_source
          FROM (SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY session_id, event_datetime, event_name
                                          ORDER BY event_id) AS dup
                  FROM app_events
                 WHERE customer_id NOT LIKE 'QA%')
         WHERE dup = 1
    """)
    # 세션별로 묶는 집계가 빨라지도록 session_id에 인덱스를 붙임 (없으면 첫 실행이 몇 분 걸릴 수 있음)
    con.execute("CREATE INDEX idx_events_session ON events(session_id)")
    return con

# ------------------------------------------------------------
# 1. 데이터 준비 — 정제된 events 테이블을 SQL로 집계
# ------------------------------------------------------------
@st.cache_data
def query(sql):                            # SQL을 실행해 표로 돌려줌
    return pd.read_sql(sql, get_db())

# 주 × 플랫폼 × 유입 경로별 세션 퍼널
SQL_WEEKLY_FUNNEL = """
WITH s AS (                                 -- 세션의 첫 이벤트로 플랫폼 · 유입 경로 · 주 정하기
    SELECT session_id, platform, traffic_source,
           DATE(MIN(event_datetime), 'weekday 0', '-6 days') AS 주시작일
      FROM events
     GROUP BY session_id
)
SELECT s.주시작일,
       s.platform       AS 플랫폼,
       s.traffic_source AS 유입경로,
       COUNT(DISTINCT e.session_id)                                                       AS 세션수,
       COUNT(DISTINCT CASE WHEN e.event_name = 'view_restaurant' THEN e.session_id END)   AS 조회세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'add_to_cart'     THEN e.session_id END)   AS 장바구니세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'begin_checkout'  THEN e.session_id END)   AS 결제시작세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'order_complete'  THEN e.session_id END)   AS 주문세션,
       SUM(CASE WHEN e.event_name = 'payment_fail' THEN 1 ELSE 0 END)                     AS 결제실패
  FROM events e
  JOIN s ON e.session_id = s.session_id
 WHERE s.주시작일 < '2026-06-29'            -- 이틀치뿐인 마지막 주 제외
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3
"""

@st.cache_data
def load_data():
    data = query(SQL_WEEKLY_FUNNEL)
    data["주시작일"] = pd.to_datetime(data["주시작일"]).dt.date
    return data

df = load_data()                           # 주 × 플랫폼 × 유입 경로별 세션 퍼널

# ------------------------------------------------------------
# 사이드바 필터 추가
# ------------------------------------------------------------
st.sidebar.header("필터")

# 1. 주시작일 목록 추출 및 정렬
weeks = sorted(df["주시작일"].unique())

# 2. 기간 선택 슬라이더 (첫 주, 마지막 주 기본값)
selected_weeks = st.sidebar.select_slider(
    "기간",
    options=weeks,
    value=(weeks[0], weeks[-1])
)

# 3. 플랫폼 멀티셀렉트 (기본값 전체 선택)
platforms = sorted(df["플랫폼"].unique())
selected_platforms = st.sidebar.multiselect(
    "플랫폼",
    options=platforms,
    default=platforms
)

# 4. 유입 경로 멀티셀렉트 (기본값 전체 선택)
traffic_sources = sorted(df["유입경로"].unique())
selected_traffic_sources = st.sidebar.multiselect(
    "유입 경로",
    options=traffic_sources,
    default=traffic_sources
)

# ------------------------------------------------------------
# 필터 연결 및 빈 데이터 예외 처리
# ------------------------------------------------------------
f = df[
    (df["주시작일"] >= selected_weeks[0]) & 
    (df["주시작일"] <= selected_weeks[1]) & 
    (df["플랫폼"].isin(selected_platforms)) & 
    (df["유입경로"].isin(selected_traffic_sources))
]

if f.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다. 필터를 바꿔 주세요.")
    st.stop()

# ------------------------------------------------------------
# 2. KPI 카드 (df 대신 f 사용)
# ------------------------------------------------------------
def rate(a, b):
    return a / b * 100 if b else 0

t = f[["세션수", "결제시작세션", "주문세션"]].sum()
c1, c2, c3 = st.columns(3)
c1.metric("세션 수", f"{t['세션수']:,}개")
c2.metric("주문 전환율 (방문 → 주문)", f"{rate(t['주문세션'], t['세션수']):.1f}%")
c3.metric("결제 전환율 (결제 시작 → 주문)", f"{rate(t['주문세션'], t['결제시작세션']):.1f}%")

st.divider()

# ------------------------------------------------------------
# 3. 차트 (df 대신 f 사용)
# ------------------------------------------------------------
left, right = st.columns(2)

# 3-1. 주별 결제 전환율 (플랫폼별)
wp = f.groupby(["주시작일", "플랫폼"])[["결제시작세션", "주문세션"]].sum().reset_index()
wp["결제전환율"] = (wp["주문세션"] / wp["결제시작세션"] * 100).round(1)
fig1 = px.line(wp, x="주시작일", y="결제전환율", color="플랫폼", markers=True,
               title="주별 결제 전환율 (플랫폼별)")
fig1.update_layout(yaxis_title="결제 전환율 (%)", xaxis_title="")
left.plotly_chart(fig1, width="stretch")

# 3-2. 세션 퍼널
steps = {"1.방문": "세션수", "2.식당조회": "조회세션", "3.장바구니": "장바구니세션",
         "4.결제시작": "결제시작세션", "5.주문완료": "주문세션"}
fun = pd.DataFrame({"단계": list(steps), "세션수": [f[c].sum() for c in steps.values()]})
fig2 = px.funnel(fun, x="세션수", y="단계", title="세션 퍼널")
right.plotly_chart(fig2, width="stretch")

# 3-3. 유입 경로별 주문 전환율
ws = f.groupby("유입경로")[["세션수", "주문세션"]].sum().reset_index()
ws["주문전환율"] = (ws["주문세션"] / ws["세션수"] * 100).round(1)
ws = ws.sort_values("주문전환율")
fig3 = px.bar(ws, x="주문전환율", y="유입경로", orientation="h", text_auto=".1f",
              hover_data=["세션수"], title="유입 경로별 주문 전환율")
if not ws.empty and ws["주문전환율"].max() > 0:
    fig3.update_xaxes(range=[0, ws["주문전환율"].max() * 1.2])
fig3.update_layout(xaxis_title="주문 전환율 (%)", yaxis_title="")
st.plotly_chart(fig3, width="stretch")

# ------------------------------------------------------------
# 4. 집단 비교 영역
# ------------------------------------------------------------
st.divider()
st.subheader("집단 비교")

# 비교 기준 선택 (가로 배치)
comparison_type = st.radio(
    "비교 기준",
    ["플랫폼", "유입경로"],
    horizontal=True
)

group_col = comparison_type

# 집단별 5단계 퍼널 지표 집계
agg_df = f.groupby(group_col)[["세션수", "조회세션", "장바구니세션", "결제시작세션", "주문세션"]].sum().reset_index()

# 세션 수가 500개 미만인 집단이 있는지 확인 후 안내 메시지 출력
low_session_groups = agg_df[agg_df["세션수"] < 500][group_col].tolist()
if low_session_groups:
    st.caption("값이 크게 흔들릴 수 있다")

left_comp, right_comp = st.columns(2)

# 4-1. 왼쪽: 누적 전환율(첫 단계 대비 %) 퍼널 (집단별 색 구분)
funnel_list = []
step_cols = [
    ("1.방문", "세션수"), 
    ("2.식당조회", "조회세션"), 
    ("3.장바구니", "장바구니세션"), 
    ("4.결제시작", "결제시작세션"), 
    ("5.주문완료", "주문세션")
]

for _, row in agg_df.iterrows():
    g_name = row[group_col]
    base_sessions = row["세션수"]
    for step_name, col_name in step_cols:
        val = row[col_name]
        cum_rate = (val / base_sessions * 100) if base_sessions > 0 else 0
        funnel_list.append({
            group_col: g_name,
            "단계": step_name,
            "누적전환율": round(cum_rate, 1),
            "세션수": val
        })

df_funnel = pd.DataFrame(funnel_list)
fig_cum_funnel = px.funnel(
    df_funnel,
    x="누적전환율",
    y="단계",
    color=group_col,
    title="누적 전환율 퍼널 (첫 단계 대비 %)",
    hover_data=["세션수"]
)
fig_cum_funnel.update_layout(xaxis_title="누적 전환율 (%)", yaxis_title="")
left_comp.plotly_chart(fig_cum_funnel, width="stretch")

# 4-2. 오른쪽: 단계 전환율(직전 단계 대비 %) 막대, 집단별로 나란히 (barmode="group")
step_pairs = [
    ("방문 → 조회", "세션수", "조회세션"),
    ("조회 → 장바구니", "조회세션", "장바구니세션"),
    ("장바구니 → 결제시작", "장바구니세션", "결제시작세션"),
    ("결제시작 → 주문완료", "결제시작세션", "주문세션")
]

step_conv_list = []
for _, row in agg_df.iterrows():
    g_name = row[group_col]
    for step_name, prev_col, curr_col in step_pairs:
        prev_val = row[prev_col]
        curr_val = row[curr_col]
        rate_val = (curr_val / prev_val * 100) if prev_val > 0 else 0
        step_conv_list.append({
            group_col: g_name,
            "단계전환": step_name,
            "단계전환율": round(rate_val, 1),
            "기준세션": prev_val,
            "해당세션": curr_val
        })

df_step_conv = pd.DataFrame(step_conv_list)
fig_step_bar = px.bar(
    df_step_conv,
    x="단계전환율",
    y="단계전환",
    color=group_col,
    barmode="group",
    orientation="h",
    text_auto=".1f",
    hover_data=["기준세션", "해당세션"],
    title="단계별 전환율 (직전 단계 대비 %)"
)
fig_step_bar.update_layout(xaxis_title="전환율 (%)", yaxis_title="")
right_comp.plotly_chart(fig_step_bar, width="stretch")