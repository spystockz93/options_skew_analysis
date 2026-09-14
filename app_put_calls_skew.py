import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Options Skew & Max Pain Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CONSTANTS
# ============================================================

OPTION_MULTIPLIER = 100

DEFAULT_TICKER = "GOOGL"

MIN_IV = 0.01       # 1%
MAX_IV = 2.50       # 250%


# ============================================================
# PAGE TITLE
# ============================================================

st.title("📈 Options Volatility Skew & Max Pain Dashboard")

st.markdown(
    """
    Analyze:

    - Implied Volatility (IV) skew
    - Call / Put Open Interest
    - Max Pain
    - Aggregate option payout at expiration
    - Option-chain data

    **Important:** Max Pain is calculated independently from IV filtering.
    """
)


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("⚙️ Configuration")

ticker_symbol = (
    st.sidebar.text_input(
        "Enter Ticker Symbol",
        value=DEFAULT_TICKER,
    )
    .upper()
    .strip()
)

if not ticker_symbol:
    st.error("Please enter a ticker symbol.")
    st.stop()


# ============================================================
# DATA FUNCTIONS
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def load_stock_data(symbol: str):
    """
    Fetch available option expirations and current stock price.

    Price priority:
        1. fast_info.last_price
        2. 1-day historical close
    """

    ticker = yf.Ticker(symbol)

    # --------------------------------------------------------
    # Expirations
    # --------------------------------------------------------

    try:
        expirations = list(ticker.options)
    except Exception:
        expirations = []

    # --------------------------------------------------------
    # Current price
    # --------------------------------------------------------

    current_price = None

    try:
        fast_info = ticker.fast_info

        try:
            current_price = fast_info.get("last_price")
        except Exception:
            current_price = None

        if current_price is not None:
            current_price = float(current_price)

    except Exception:
        current_price = None

    # --------------------------------------------------------
    # Historical fallback
    # --------------------------------------------------------

    if current_price is None or not np.isfinite(current_price):
        try:
            hist = ticker.history(
                period="1d",
                auto_adjust=False,
            )

            if not hist.empty:
                current_price = float(hist["Close"].iloc[-1])

        except Exception:
            current_price = None

    return expirations, current_price


@st.cache_data(ttl=300, show_spinner=False)
def fetch_option_chain(symbol: str, expiration: str):
    """
    Fetch complete option chain.

    IMPORTANT:
    No strike filtering or IV filtering happens here.
    """

    ticker = yf.Ticker(symbol)

    option_chain = ticker.option_chain(expiration)

    calls = option_chain.calls.copy()
    puts = option_chain.puts.copy()

    return calls, puts


# ============================================================
# LOAD STOCK DATA
# ============================================================

with st.spinner(f"Loading {ticker_symbol}..."):

    expirations, current_price = load_stock_data(
        ticker_symbol
    )


if not expirations:
    st.error(
        f"""
        ❌ No option expirations were found for **{ticker_symbol}**.

        Possible causes:

        - Invalid ticker
        - No listed options
        - Yahoo Finance temporarily unavailable
        - Network/API issue
        """
    )
    st.stop()


if current_price is None or current_price <= 0:
    st.error(
        f"❌ Could not determine a valid price for {ticker_symbol}."
    )
    st.stop()


# ============================================================
# SIDEBAR SETTINGS
# ============================================================

selected_exp = st.sidebar.selectbox(
    "Expiration Date",
    expirations,
)


st.sidebar.markdown("---")

st.sidebar.subheader("IV Skew Settings")

moneyness_range = st.sidebar.slider(
    "Skew Range (% of Spot)",
    min_value=50,
    max_value=100,
    value=(65, 135),
    step=5,
)

skew_x_axis = st.sidebar.radio(
    "Skew X-Axis",
    [
        "Moneyness (%)",
        "Strike Price ($)",
    ],
)


# ============================================================
# LOAD OPTION CHAIN
# ============================================================

try:

    with st.spinner(
        f"Loading option chain for {selected_exp}..."
    ):

        calls_raw, puts_raw = fetch_option_chain(
            ticker_symbol,
            selected_exp,
        )

except Exception as e:

    st.error(
        f"❌ Unable to load option chain: {e}"
    )
    st.stop()


# ============================================================
# VALIDATE OPTION CHAIN
# ============================================================

if calls_raw.empty and puts_raw.empty:

    st.error(
        "❌ The selected expiration contains no option contracts."
    )
    st.stop()


# ============================================================
# STANDARDIZE NUMERIC COLUMNS
# ============================================================

def clean_option_data(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy()

    numeric_columns = [
        "strike",
        "lastPrice",
        "bid",
        "ask",
        "volume",
        "openInterest",
        "impliedVolatility",
    ]

    for column in numeric_columns:

        if column in df.columns:
```
