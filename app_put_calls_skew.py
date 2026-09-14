import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# Page Configuration
st.set_page_config(
    page_title="Options Skew & Max Pain Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📈 Options Volatility Skew & Max Pain Dashboard")
st.markdown(
    "Analyze dealer positioning, Implied Volatility (IV) skew across strike prices, and calculate **Max Pain**."
)

# Sidebar Ticker Input
st.sidebar.header("Configuration")
ticker_symbol = (
    st.sidebar.text_input("Enter Ticker Symbol", value="GOOGL").upper().strip()
)


@st.cache_data(ttl=300)
def load_stock_info(symbol: str):
    """Fetch available expirations and latest close price."""
    try:
        stock = yf.Ticker(symbol)
        expirations = list(stock.options)
        hist = stock.history(period="1d")
        current_price = (
            float(hist["Close"].iloc[-1]) if not hist.empty else None
        )
        return expirations, current_price
    except Exception:
        return [], None


expirations, current_price = load_stock_info(ticker_symbol)

if not expirations or not current_price:
    st.error(
        f"❌ Could not fetch options data for **{ticker_symbol}**. "
        "Please verify the symbol or try again during market hours."
    )
    st.stop()

# Expiration Selector
selected_exp = st.sidebar.selectbox("Select Expiration Date", expirations)


@st.cache_data(ttl=300)
def fetch_option_chain(symbol: str, exp: str):
    """Fetch calls and puts dataframes for the given expiration."""
    stk = yf.Ticker(symbol)
    opt = stk.option_chain(exp)
    return opt.calls, opt.puts


calls, puts = fetch_option_chain(ticker_symbol, selected_exp)

# --- DATA CLEANING & FILTERING ---
# Filter strikes to a realistic band (+/- 35% of stock price) to eliminate dead/illiquid strikes
min_strike = current_price * 0.65
max_strike = current_price * 1.35

calls_clean = calls[
    (calls["strike"] >= min_strike) & (calls["strike"] <= max_strike)
].copy()
puts_clean = puts[
    (puts["strike"] >= min_strike) & (puts["strike"] <= max_strike)
].copy()

# Clean IV Data (Ignore bad pricing models with IV > 250% or IV < 1%)
calls_clean = calls_clean[
    (calls_clean["impliedVolatility"] > 0.01)
    & (calls_clean["impliedVolatility"] < 2.5)
]
puts_clean = puts_clean[
    (puts_clean["impliedVolatility"] > 0.01)
    & (puts_clean["impliedVolatility"] < 2.5)
]

# --- MAX PAIN CALCULATION (RELEVANT STRIKES ONLY) ---
strikes = sorted(
    list(
        set(calls_clean["strike"].dropna()).union(
            set(puts_clean["strike"].dropna())
        )
    )
)
call_oi = calls_clean.set_index("strike")["openInterest"].fillna(0).to_dict()
put_oi = puts_clean.set_index("strike")["openInterest"].fillna(0).to_dict()

payouts = []
for strike_price in strikes:
    call_payout = sum(
        max(0.0, strike_price - k) * oi
        for k, oi in call_oi.items()
        if strike_price > k
    )
    put_payout = sum(
        max(0.0, k - strike_price) * oi
        for k, oi in put_oi.items()
        if strike_price < k
    )
    total_loss = (call_payout + put_payout) * 100.0
    payouts.append(total_loss)

if payouts:
    max_pain_idx = int(np.argmin(payouts))
    max_pain_strike = strikes[max_pain_idx]
    price_diff = max_pain_strike - current_price
else:
    max_pain_strike = current_price
    price_diff = 0.0

# Top Summary KPI Cards
col1, col2, col3, col4 = st.columns(4)
col1.metric(label="Ticker", value=ticker_symbol)
col2.metric(label="Current Price", value=f"${current_price:.2f}")
col3.metric(label="Selected Expiration", value=selected_exp)
col4.metric(
    label="Max Pain Strike",
    value=f"${max_pain_strike:.2f}",
    delta=f"{price_diff:+.2f} from price",
)

st.markdown("---")

# Main Interface Tabs
tab1, tab2, tab3 = st.tabs(
    [
        "📊 Volatility Skew",
        "🎯 Max Pain & Open Interest",
        "📑 Option Chain Tables",
    ]
)

# TAB 1: IV SKEW
with tab1:
    st.subheader(f"Implied Volatility (IV) Skew — {ticker_symbol} ({selected_exp})")
    st.caption(
        "Cleaned IV curve (filtered for active, liquid strikes near current stock price)."
    )

    fig_skew = go.Figure()
    fig_skew.add_trace(
        go.Scatter(
            x=calls_clean["strike"],
            y=calls_clean["impliedVolatility"] * 100,
            mode="lines+markers",
            name="Call IV",
            line=dict(color="#22c55e", width=2.5),
        )
    )
    fig_skew.add_trace(
        go.Scatter(
            x=puts_clean["strike"],
            y=puts_clean["impliedVolatility"] * 100,
            mode="lines+markers",
            name="Put IV",
            line=dict(color="#ef4444", width=2.5),
        )
    )

    fig_skew.add_vline(
        x=current_price,
        line_dash="dash",
        line_color="#3b82f6",
        annotation_text=f"Stock Price: ${current_price:.2f}",
        annotation_position="top right",
    )

    fig_skew.update_layout(
        xaxis_title="Strike Price ($)",
        yaxis_title="Implied Volatility (%)",
        template="plotly_dark",
        height=520,
        hovermode="x unified",
    )
    st.plotly_chart(fig_skew, use_container_width=True)

# TAB 2: MAX PAIN & OPEN INTEREST
with tab2:
    st.subheader(f"Open Interest & Dealer Payout — {ticker_symbol}")

    df_oi = pd.DataFrame({"strike": strikes})
    df_oi["Call_OI"] = df_oi["strike"].map(call_oi).fillna(0)
    df_oi["Put_OI"] = df_oi["strike"].map(put_oi).fillna(0)

    fig_oi = go.Figure()
    fig_oi.add_trace(
        go.Bar(
            x=df_oi["strike"],
            y=df_oi["Call_OI"],
            name="Call Open Interest",
            marker_color="#22c55e",
        )
    )
    fig_oi.add_trace(
        go.Bar(
            x=df_oi["strike"],
            y=-df_oi["Put_OI"],
            name="Put Open Interest",
            marker_color="#ef4444",
        )
    )

    fig_oi.add_vline(
        x=max_pain_strike,
        line_dash="solid",
        line_color="#f59e0b",
        annotation_text=f"Max Pain: ${max_pain_strike:.2f}",
        annotation_position="top left",
    )

    fig_oi.add_vline(
        x=current_price,
        line_dash="dash",
        line_color="#3b82f6",
        annotation_text=f"Current: ${current_price:.2f}",
        annotation_position="bottom right",
    )

    fig_oi.update_layout(
        title="Open Interest by Strike (Calls Above / Puts Below Zero)",
        xaxis_title="Strike Price ($)",
        yaxis_title="Open Interest (Contracts)",
        barmode="relative",
        template="plotly_dark",
        height=450,
    )
    st.plotly_chart(fig_oi, use_container_width=True)

    # Dealer Payout Curve
    fig_payout = go.Figure()
    fig_payout.add_trace(
        go.Scatter(
            x=strikes,
            y=[p / 1e6 for p in payouts],
            mode="lines",
            name="Dealer Payout ($M)",
            line=dict(color="#a855f7", width=3),
        )
    )
    fig_payout.add_vline(
        x=max_pain_strike,
        line_dash="solid",
        line_color="#f59e0b",
        annotation_text=f"Min Dealer Payout: ${max_pain_strike:.2f}",
    )

    fig_payout.update_layout(
        title="Dealer Dollar Payout at Expiry (Lowest Point = Max Pain)",
        xaxis_title="Stock Price at Expiration ($)",
        yaxis_title="Total Payout to Buyers ($ Millions)",
        template="plotly_dark",
        height=400,
    )
    st.plotly_chart(fig_payout, use_container_width=True)

# TAB 3: RAW DATA TABLES
with tab3:
    col_call, col_put = st.columns(2)
    with col_call:
        st.subheader("Calls Option Chain (Filtered)")
        st.dataframe(
            calls_clean[
                [
                    "strike",
                    "lastPrice",
                    "bid",
                    "ask",
                    "openInterest",
                    "impliedVolatility",
                ]
            ],
            use_container_width=True,
        )
    with col_put:
        st.subheader("Puts Option Chain (Filtered)")
        st.dataframe(
            puts_clean[
                [
                    "strike",
                    "lastPrice",
                    "bid",
                    "ask",
                    "openInterest",
                    "impliedVolatility",
                ]
            ],
            use_container_width=True,
        )
