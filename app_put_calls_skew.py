import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="Options Skew & Max Pain",
    page_icon="📈",
    layout="wide",
)

OPTION_MULTIPLIER = 100
MIN_IV = 0.01
MAX_IV = 2.50


@st.cache_data(ttl=300, show_spinner=False)
def load_stock(symbol):
    ticker = yf.Ticker(symbol)

    try:
        expirations = list(ticker.options)
    except Exception:
        expirations = []

    price = None

    try:
        price = ticker.fast_info.get("last_price")
        if price is not None:
            price = float(price)
    except Exception:
        price = None

    if price is None or not np.isfinite(price) or price <= 0:
        try:
            hist = ticker.history(period="1d", auto_adjust=False)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        except Exception:
            price = None

    return expirations, price


@st.cache_data(ttl=300, show_spinner=False)
def load_option_chain(symbol, expiration):
    ticker = yf.Ticker(symbol)
    chain = ticker.option_chain(expiration)
    return chain.calls.copy(), chain.puts.copy()


def clean_options(df):
    df = df.copy()

    numeric = [
        "strike",
        "lastPrice",
        "bid",
        "ask",
        "volume",
        "openInterest",
        "impliedVolatility",
    ]

    for col in numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "openInterest" not in df.columns:
        df["openInterest"] = 0.0

    if "impliedVolatility" not in df.columns:
        df["impliedVolatility"] = np.nan

    df["openInterest"] = df["openInterest"].fillna(0).clip(lower=0)
    return df


def calculate_max_pain(calls, puts):
    calls = calls.dropna(subset=["strike"]).copy()
    puts = puts.dropna(subset=["strike"]).copy()

    call_oi = calls.groupby("strike")["openInterest"].sum().to_dict()
    put_oi = puts.groupby("strike")["openInterest"].sum().to_dict()

    strikes = sorted(set(call_oi) | set(put_oi))

    if not strikes:
        return pd.DataFrame(), None

    rows = []

    for expiration_price in strikes:
        call_payout = sum(
            max(expiration_price - strike, 0.0) * oi
            for strike, oi in call_oi.items()
        )

        put_payout = sum(
            max(strike - expiration_price, 0.0) * oi
            for strike, oi in put_oi.items()
        )

        total = (call_payout + put_payout) * OPTION_MULTIPLIER

        rows.append(
            {
                "expiration_price": expiration_price,
                "call_payout": call_payout * OPTION_MULTIPLIER,
                "put_payout": put_payout * OPTION_MULTIPLIER,
                "total_payout": total,
            }
        )

    result = pd.DataFrame(rows)
    max_pain = float(
        result.loc[result["total_payout"].idxmin(), "expiration_price"]
    )

    return result, max_pain


def prepare_skew(df, spot, low_pct, high_pct):
    result = df.copy()

    low_strike = spot * low_pct / 100
    high_strike = spot * high_pct / 100

    result = result[
        result["strike"].between(low_strike, high_strike)
    ].copy()

    result = result[
        result["impliedVolatility"].between(MIN_IV, MAX_IV)
    ].copy()

    result["moneyness"] = result["strike"] / spot * 100
    return result.sort_values("strike")


st.title("📈 Options Skew & Max Pain Dashboard")

st.sidebar.header("Settings")

symbol = st.sidebar.text_input(
    "Ticker",
    value="GOOGL",
).strip().upper()

if not symbol:
    st.warning("Enter a ticker symbol.")
    st.stop()

expirations, spot = load_stock(symbol)

if not expirations:
    st.error(
        f"No listed option expirations were found for {symbol}."
    )
    st.stop()

if spot is None or spot <= 0:
    st.error(f"Could not determine a valid price for {symbol}.")
    st.stop()

expiration = st.sidebar.selectbox(
    "Expiration",
    expirations,
)

skew_range = st.sidebar.slider(
    "IV Skew Range (% of Spot)",
    min_value=50,
    max_value=150,
    value=(65, 135),
    step=5,
)

x_axis = st.sidebar.radio(
    "Skew X-axis",
    ["Moneyness (%)", "Strike Price ($)"],
)

try:
    calls_raw, puts_raw = load_option_chain(symbol, expiration)
except Exception as exc:
    st.error(f"Unable to load option chain: {exc}")
    st.stop()

calls_raw = clean_options(calls_raw)
puts_raw = clean_options(puts_raw)

if calls_raw.empty and puts_raw.empty:
    st.error("The selected expiration contains no option contracts.")
    st.stop()

# Max Pain uses the COMPLETE available chain.
max_pain_df, max_pain = calculate_max_pain(calls_raw, puts_raw)

if max_pain is None:
    st.error("Unable to calculate Max Pain.")
    st.stop()

distance = max_pain - spot
distance_pct = distance / spot * 100

# IV skew uses separate, filtered data.
calls_skew = prepare_skew(
    calls_raw, spot, skew_range[0], skew_range[1]
)
puts_skew = prepare_skew(
    puts_raw, spot, skew_range[0], skew_range[1]
)

total_call_oi = calls_raw["openInterest"].sum()
total_put_oi = puts_raw["openInterest"].sum()
pc_ratio = (
    total_put_oi / total_call_oi
    if total_call_oi > 0
    else np.nan
)

c1, c2, c3, c4, c5 = st.columns(5)

c1.metric("Ticker", symbol)
c2.metric("Spot", f"${spot:,.2f}")
c3.metric("Expiration", expiration)
c4.metric(
    "Max Pain",
    f"${max_pain:,.2f}",
    delta=f"{distance:+,.2f} ({distance_pct:+.2f}%)",
)
c5.metric(
    "Put/Call OI",
    f"{pc_ratio:.2f}" if np.isfinite(pc_ratio) else "N/A",
)

tab_skew, tab_pain, tab_oi, tab_chain = st.tabs(
    ["📊 IV Skew", "🎯 Max Pain", "📈 Open Interest", "📑 Option Chain"]
)

with tab_skew:
    st.subheader(f"IV Skew — {symbol} — {expiration}")

    if calls_skew.empty and puts_skew.empty:
        st.warning("No valid IV observations are available in the selected range.")
    else:
        fig = go.Figure()

        if x_axis == "Moneyness (%)":
            call_x = calls_skew["moneyness"]
            put_x = puts_skew["moneyness"]
            x_title = "Moneyness (% of Spot)"
            spot_x = 100
        else:
            call_x = calls_skew["strike"]
            put_x = puts_skew["strike"]
            x_title = "Strike Price ($)"
            spot_x = spot

        if not calls_skew.empty:
            fig.add_trace(
                go.Scatter(
                    x=call_x,
                    y=calls_skew["impliedVolatility"] * 100,
                    mode="lines+markers",
                    name="Call IV",
                    customdata=np.column_stack(
                        [
                            calls_skew["strike"],
                            calls_skew["openInterest"],
                            calls_skew["volume"].fillna(0),
                        ]
                    ),
                    hovertemplate=(
                        "Strike: $%{customdata[0]:.2f}"
                        "<br>IV: %{y:.2f}%"
                        "<br>OI: %{customdata[1]:,.0f}"
                        "<br>Volume: %{customdata[2]:,.0f}"
                        "<extra>Call</extra>"
                    ),
                )
            )

        if not puts_skew.empty:
            fig.add_trace(
                go.Scatter(
                    x=put_x,
                    y=puts_skew["impliedVolatility"] * 100,
                    mode="lines+markers",
                    name="Put IV",
                    customdata=np.column_stack(
                        [
                            puts_skew["strike"],
                            puts_skew["openInterest"],
                            puts_skew["volume"].fillna(0),
                        ]
                    ),
                    hovertemplate=(
                        "Strike: $%{customdata[0]:.2f}"
                        "<br>IV: %{y:.2f}%"
                        "<br>OI: %{customdata[1]:,.0f}"
                        "<br>Volume: %{customdata[2]:,.0f}"
                        "<extra>Put</extra>"
                    ),
                )
            )

        fig.add_vline(
            x=spot_x,
            line_dash="dash",
            annotation_text=f"Spot ${spot:,.2f}",
        )

        fig.update_layout(
            xaxis_title=x_title,
            yaxis_title="Implied Volatility (%)",
            height=550,
            hovermode="x unified",
        )

        st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"Skew chart range: {skew_range[0]}%–{skew_range[1]}% of spot. "
        f"IV filter: {MIN_IV:.0%}–{MAX_IV:.0%}. "
        "These filters do not affect Max Pain."
    )

with tab_pain:
    st.subheader(f"Max Pain — {symbol} — {expiration}")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=max_pain_df["expiration_price"],
            y=max_pain_df["total_payout"] / 1_000_000,
            mode="lines+markers",
            name="Aggregate Option Payout",
            hovertemplate=(
                "Expiration Price: $%{x:.2f}"
                "<br>Total Payout: $%{y:,.2f}M"
                "<extra></extra>"
            ),
        )
    )

    fig.add_vline(
        x=max_pain,
        line_dash="solid",
        annotation_text=f"Max Pain ${max_pain:,.2f}",
    )

    fig.add_vline(
        x=spot,
        line_dash="dash",
        annotation_text=f"Spot ${spot:,.2f}",
    )

    fig.update_layout(
        xaxis_title="Stock Price at Expiration ($)",
        yaxis_title="Aggregate Option Payout ($M)",
        height=550,
    )

    st.plotly_chart(fig, use_container_width=True)

    st.info(
        "Max Pain is calculated from available Open Interest and intrinsic "
        "option value. It does not identify actual dealer positioning."
    )

with tab_oi:
    st.subheader(f"Open Interest — {symbol} — {expiration}")

    strikes = sorted(
        set(calls_raw["strike"].dropna())
        | set(puts_raw["strike"].dropna())
    )

    oi_df = pd.DataFrame({"strike": strikes})

    call_by_strike = (
        calls_raw.groupby("strike")["openInterest"].sum()
    )
    put_by_strike = (
        puts_raw.groupby("strike")["openInterest"].sum()
    )

    oi_df["Call OI"] = oi_df["strike"].map(call_by_strike).fillna(0)
    oi_df["Put OI"] = oi_df["strike"].map(put_by_strike).fillna(0)

    fig = go.Figure()

    fig.add_bar(
        x=oi_df["strike"],
        y=oi_df["Call OI"],
        name="Call OI",
    )

    fig.add_bar(
        x=oi_df["strike"],
        y=-oi_df["Put OI"],
        name="Put OI",
    )

    fig.add_vline(
        x=spot,
        line_dash="dash",
        annotation_text=f"Spot ${spot:,.2f}",
    )

    fig.add_vline(
        x=max_pain,
        line_dash="solid",
        annotation_text=f"Max Pain ${max_pain:,.2f}",
    )

    fig.update_layout(
        barmode="relative",
        xaxis_title="Strike ($)",
        yaxis_title="Open Interest",
        height=550,
    )

    st.plotly_chart(fig, use_container_width=True)

    o1, o2, o3 = st.columns(3)
    o1.metric("Total Call OI", f"{total_call_oi:,.0f}")
    o2.metric("Total Put OI", f"{total_put_oi:,.0f}")
    o3.metric(
        "Put/Call OI",
        f"{pc_ratio:.2f}" if np.isfinite(pc_ratio) else "N/A",
    )

with tab_chain:
    st.subheader(f"Option Chain — {symbol} — {expiration}")

    left, right = st.columns(2)

    display_columns = [
        "contractSymbol",
        "strike",
        "lastPrice",
        "bid",
        "ask",
        "volume",
        "openInterest",
        "impliedVolatility",
    ]

    with left:
        st.markdown("### Calls")

        call_cols = [
            col for col in display_columns
            if col in calls_raw.columns
        ]

        calls_display = calls_raw[call_cols].copy()

        if "impliedVolatility" in calls_display.columns:
            calls_display["impliedVolatility"] *= 100
            calls_display = calls_display.rename(
                columns={"impliedVolatility": "IV (%)"}
            )

        st.dataframe(
            calls_display,
            use_container_width=True,
            hide_index=True,
        )

    with right:
        st.markdown("### Puts")

        put_cols = [
            col for col in display_columns
            if col in puts_raw.columns
        ]

        puts_display = puts_raw[put_cols].copy()

        if "impliedVolatility" in puts_display.columns:
            puts_display["impliedVolatility"] *= 100
            puts_display = puts_display.rename(
                columns={"impliedVolatility": "IV (%)"}
            )

        st.dataframe(
            puts_display,
            use_container_width=True,
            hide_index=True,
        )

st.markdown("---")
st.caption(
    "Data source: Yahoo Finance via yfinance. "
    "Market data may be delayed or incomplete. "
    "Max Pain is an OI-based intrinsic-value calculation and is not a "
    "direct measure of dealer positioning."
)
