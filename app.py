import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import io
import requests

st.set_page_config(
    page_title="Nifty 500 Momentum Scanner",
    page_icon="📈",
    layout="wide"
)

st.title("📈 NIFTY 500 MOMENTUM SCANNER")
st.caption("Momentum Ranking + SuperTrend")

@st.cache_data(ttl=86400)
def get_stocks():
    url = (
        "https://www.niftyindices.com/"
        "IndexConstituent/ind_nifty500list.csv"
    )
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    return df["Symbol"].dropna().unique().tolist()

def supertrend(df, period=10, multiplier=3):
    h = df["High"]
    l = df["Low"]
    c = df["Close"]

    tr = pd.concat([
        h-l,
        (h-c.shift()).abs(),
        (l-c.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(
        alpha=1/period,
        adjust=False,
        min_periods=period
    ).mean()

    upper = ((h+l)/2 + multiplier*atr).to_numpy().copy()
    lower = ((h+l)/2 - multiplier*atr).to_numpy().copy()
    close = c.to_numpy()
    trend = np.ones(len(df), dtype=int)

    for i in range(period, len(df)):
        if not (
            upper[i] < upper[i-1]
            or close[i-1] > upper[i-1]
        ):
            upper[i] = upper[i-1]

        if not (
            lower[i] > lower[i-1]
            or close[i-1] < lower[i-1]
        ):
            lower[i] = lower[i-1]

        if close[i] > upper[i]:
            trend[i] = 1
        elif close[i] < lower[i]:
            trend[i] = -1
        else:
            trend[i] = trend[i-1]

    return "BUY" if trend[-1] == 1 else "SELL"

st.sidebar.header("Strategy Settings")

w6 = st.sidebar.slider("6 Month Weight", 0, 100, 50)
w3 = st.sidebar.slider("3 Month Weight", 0, 100, 30)
w1 = st.sidebar.slider("1 Month Weight", 0, 100, 20)

period = st.sidebar.number_input(
    "SuperTrend Period", 2, 50, 10
)

multiplier = st.sidebar.number_input(
    "SuperTrend Multiplier", 1.0, 10.0, 3.0
)

top_n = st.sidebar.slider(
    "Top Stocks", 5, 100, 25
)

buy_only = st.sidebar.checkbox(
    "SuperTrend BUY Only", True
)

capital = st.sidebar.number_input(
    "Investment Capital (INR)",
    min_value=1000,
    value=100000,
    step=1000
)

st.info("Momentum = 50% × 6M + 30% × 3M + 20% × 1M (default)")

@st.cache_data(ttl=3600, show_spinner=False)
def download_prices(symbols):
    return yf.download(
        symbols,
        period="1y",
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True
    )

if st.button("🚀 Scan Nifty 500", type="primary"):

    if w6+w3+w1 != 100:
        st.error("Total weight must be 100%")
        st.stop()

    try:
        stocks = get_stocks()
    except Exception:
        st.error("Unable to download Nifty 500 list. Try again later.")
        st.stop()

    results = []
    failed = []
    progress = st.progress(0)
    status = st.empty()

    for start in range(0, len(stocks), 40):
        batch = stocks[start:start+40]
        tickers = [s+".NS" for s in batch]

        try:
            data = download_prices(tickers)
        except Exception:
            failed.extend(batch)
            continue

        for symbol in batch:
            try:
                ticker = symbol+".NS"

                if isinstance(data.columns, pd.MultiIndex):
                    df = data[ticker].copy()
                else:
                    df = data.copy()

                df = df.dropna(
                    subset=["Close", "High", "Low"]
                ).sort_index()

                if len(df) < 127:
                    failed.append(symbol)
                    continue

                close = df["Close"]
                price = float(close.iloc[-1])

                m1 = (price/close.iloc[-22]-1)*100
                m3 = (price/close.iloc[-64]-1)*100
                m6 = (price/close.iloc[-127]-1)*100

                score = (
                    m6*w6 + m3*w3 + m1*w1
                )/100

                trend = supertrend(
                    df, period, multiplier
                )

                results.append({
                    "Stock": symbol,
                    "Price": round(price, 2),
                    "1M %": round(m1, 2),
                    "3M %": round(m3, 2),
                    "6M %": round(m6, 2),
                    "Momentum": score,
                    "SuperTrend": trend,
                    "Data Date": str(df.index[-1].date())
                })

            except Exception:
                failed.append(symbol)

        done = min(start+40, len(stocks))
        progress.progress(done/len(stocks))
        status.write(f"Processed {done}/{len(stocks)}")

    if not results:
        st.error("No valid market data received.")
        st.stop()

    all_df = pd.DataFrame(results)

    all_df = all_df.sort_values(
        "Momentum", ascending=False
    ).reset_index(drop=True)

    all_df.insert(
        0, "Rank", range(1, len(all_df)+1)
    )

    all_df["Momentum"] = all_df["Momentum"].round(2)

    ranked = all_df.copy()

    if buy_only:
        ranked = ranked[
            ranked["SuperTrend"] == "BUY"
        ]

    selected = ranked.head(top_n).copy()

    if len(selected):
        allocation = capital/len(selected)

        selected["Allocation"] = round(allocation, 2)

        selected["Quantity"] = (
            allocation/selected["Price"]
        ).astype(int)

        selected["Investment"] = (
            selected["Quantity"]*selected["Price"]
        ).round(2)

    st.session_state["all"] = all_df
    st.session_state["selected"] = selected
    st.session_state["failed"] = failed
    st.session_state["universe"] = len(stocks)

if "selected" in st.session_state:

    selected = st.session_state["selected"]
    all_df = st.session_state["all"]
    failed = st.session_state["failed"]

    c1, c2, c3 = st.columns(3)

    c1.metric("Stocks Scanned", len(all_df))
    c2.metric("Selected", len(selected))
    c3.metric("Missing Data", len(failed))

    if failed:
        st.warning(
            "Some stocks could not be scanned. "
            "Ranking may be incomplete."
        )

    st.subheader("🏆 Top Momentum Stocks")

    st.dataframe(
        selected,
        use_container_width=True,
        hide_index=True
    )

    if not selected.empty:
        st.bar_chart(
            selected.set_index("Stock")["Momentum"]
        )

    st.subheader("Complete Stock Ranking")

    st.dataframe(
        all_df,
        use_container_width=True,
        hide_index=True
    )

    output = io.BytesIO()

    with pd.ExcelWriter(
        output, engine="openpyxl"
    ) as writer:

        selected.to_excel(
            writer,
            sheet_name="Top Stocks",
            index=False
        )

        all_df.to_excel(
            writer,
            sheet_name="All Stocks",
            index=False
        )

        pd.DataFrame({
            "Missing Stock": failed
        }).to_excel(
            writer,
            sheet_name="Missing Data",
            index=False
        )

    st.download_button(
        "📥 Download Excel Report",
        data=output.getvalue(),
        file_name="Nifty_Momentum_Report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

st.caption(
    "Research only. Yahoo Finance data may be delayed "
    "or incomplete. Not investment advice."
      )
