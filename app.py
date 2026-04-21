from flask import Flask, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/',
    'X-Requested-With': 'XMLHttpRequest',
}

cache = {}
CACHE_TTL = 90

def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get('https://www.nseindia.com', timeout=10)
    except:
        pass
    return s

# ── INDICATORS ────────────────────────────────────────────

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def calc_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 2)

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 0
    trs = []
    for i in range(1, min(len(highs), len(lows), len(closes))):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    if not trs:
        return 0
    return round(sum(trs[-period:]) / min(period, len(trs)), 2)

def calc_macd(prices):
    if len(prices) < 26:
        return 'neutral'
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    macd  = ema12 - ema26
    if macd > 0:
        return 'bullish'
    elif macd < 0:
        return 'bearish'
    return 'neutral'

# ── FETCH PRICE HISTORY ───────────────────────────────────

def fetch_history(symbol):
    key = f'hist_{symbol}'
    if key in cache and time.time() - cache[key]['ts'] < 3600:
        return cache[key]['data']
    try:
        s = get_session()
        url = f'https://www.nseindia.com/api/chart-databyindex?index={symbol}EQN'
        r = s.get(url, timeout=10)
        d = r.json()
        gd = d.get('grapthData', d.get('graphData', []))
        if not gd:
            return []
        closes = [float(x[1]) for x in gd if x[1]][-50:]
        cache[key] = {'data': closes, 'ts': time.time()}
        return closes
    except:
        return []

# ── FETCH QUOTE ───────────────────────────────────────────

def fetch_quote(symbol):
    key = f'q_{symbol}'
    if key in cache and time.time() - cache[key]['ts'] < CACHE_TTL:
        return cache[key]['data']
    try:
        s = get_session()
        r = s.get(f'https://www.nseindia.com/api/quote-equity?symbol={symbol}', timeout=10)
        d = r.json()
        pi   = d.get('priceInfo', {})
        idhl = pi.get('intraDayHighLow', {})
        whl  = pi.get('weekHighLow', {})
        price = float(pi.get('lastPrice', 0))
        prev  = float(pi.get('previousClose', price))
        result = {
            'symbol':  symbol,
            'name':    d.get('info', {}).get('companyName', symbol),
            'sector':  d.get('metadata', {}).get('industry', 'NSE'),
            'price':   price,
            'open':    float(pi.get('open', price)),
            'high':    float(idhl.get('max', price)),
            'low':     float(idhl.get('min', price)),
            'prev':    prev,
            'change':  round(price - prev, 2),
            'pct':     round(float(pi.get('pChange', 0)), 2),
            'w52h':    float(whl.get('max', price)),
            'w52l':    float(whl.get('min', price)),
            'volume':  int(d.get('marketDeptOrderBook', {}).get('tradeInfo', {}).get('totalTradedVolume', 0)),
        }
        cache[key] = {'data': result, 'ts': time.time()}
        return result
    except:
        return None

# ── COMPUTE INDICATORS ────────────────────────────────────

def compute_indicators(symbol, quote):
    price = quote['price']
    high  = quote['high']
    low   = quote['low']
    pct   = quote['pct']

    hist = fetch_history(symbol)

    if len(hist) >= 15:
        closes = hist
        highs  = [p * 1.005 for p in hist]
        lows_  = [p * 0.995 for p in hist]
        rsi    = calc_rsi(closes)
        ema9   = calc_ema(closes, 9)
        ema21  = calc_ema(closes, 21)
        ema50  = calc_ema(closes, min(50, len(closes)))
        atr    = calc_atr(highs, lows_, closes)
        macd   = calc_macd(closes)
    else:
        # Fallback estimates when no history available
        rsi  = min(80, max(20, 50 + pct * 3))
        ema9 = ema21 = ema50 = price
        atr  = max(abs(high - low), price * 0.01)
        macd = 'bullish' if pct > 0 else 'bearish'

    # Range positions
    day_range = round((price - low) / (high - low) * 100, 1) if high > low else 50
    w52_range = round((price - quote['w52l']) / (quote['w52h'] - quote['w52l']) * 100, 1) if quote['w52h'] > quote['w52l'] else 50

    return {
        'rsi':       round(rsi, 1),
        'ema9':      ema9,
        'ema21':     ema21,
        'ema50':     ema50,
        'atr':       round(atr, 2),
        'macd':      macd,
        'day_range': day_range,
        'w52_range': w52_range,
        'above_ema9':  price > ema9,
        'above_ema21': price > ema21,
        'above_ema50': price > ema50,
    }

# ── GENERATE SIGNAL ───────────────────────────────────────

def generate_signal(quote, inds, mode):
    price  = quote['price']
    pct    = quote['pct']
    rsi    = inds['rsi']
    atr    = inds['atr'] if inds['atr'] > 0 else price * 0.01
    macd   = inds['macd']
    above9 = inds['above_ema9']
    above21= inds['above_ema21']
    above50= inds['above_ema50']
    is_buy = pct >= 0

    # ATR-based targets
    if mode == 'intraday':
        tgt_atr = 1.5
        sl_atr  = 1.0
    else:
        tgt_atr = 3.0
        sl_atr  = 1.5

    if is_buy:
        entry  = round(price, 2)
        target = round(price + atr * tgt_atr, 2)
        sl     = round(price - atr * sl_atr, 2)
    else:
        entry  = round(price, 2)
        target = round(price - atr * tgt_atr, 2)
        sl     = round(price + atr * sl_atr, 2)

    reward = abs(target - entry)
    risk   = abs(sl - entry)
    rr     = f"1:{round(reward/risk, 1)}" if risk > 0 else "1:1.5"

    # Confidence scoring (0-10)
    score = 0
    if is_buy:
        if 40 < rsi < 70:  score += 2
        if rsi < 60:       score += 1
        if above9:         score += 1
        if above21:        score += 1
        if above50:        score += 1
        if macd == 'bullish': score += 2
        if pct > 2:        score += 1
        if inds['day_range'] > 60: score += 1
    else:
        if 30 < rsi < 60:  score += 2
        if rsi > 40:       score += 1
        if not above9:     score += 1
        if not above21:    score += 1
        if not above50:    score += 1
        if macd == 'bearish': score += 2
        if pct < -2:       score += 1
        if inds['day_range'] < 40: score += 1

    conf = 'High' if score >= 6 else 'Medium' if score >= 3 else 'Low'

    # Build reason text
    ema_txt = ''
    if is_buy:
        if above9 and above21: ema_txt = 'Above EMA9 & EMA21 — uptrend confirmed'
        elif above9: ema_txt = 'Above EMA9 — short-term bullish'
        else: ema_txt = 'Below EMAs — caution, momentum only'
        reason = (f"Up +{abs(pct):.2f}% | RSI {rsi} | {ema_txt} | "
                  f"MACD {macd} | ATR {atr:.2f} → Target {tgt_atr}x ATR | "
                  f"Day range at {inds['day_range']:.0f}%")
    else:
        if not above9 and not above21: ema_txt = 'Below EMA9 & EMA21 — downtrend'
        elif not above9: ema_txt = 'Below EMA9 — short-term bearish'
        else: ema_txt = 'Above EMAs — reversion short'
        reason = (f"Down {abs(pct):.2f}% | RSI {rsi} | {ema_txt} | "
                  f"MACD {macd} | ATR {atr:.2f} → Target {tgt_atr}x ATR | "
                  f"Day range at {inds['day_range']:.0f}%")

    return {
        'type':      'BUY' if is_buy else 'SELL',
        'symbol':    quote['symbol'],
        'name':      quote['name'],
        'sector':    quote['sector'],
        'price':     price,
        'pct':       pct,
        'change':    quote['change'],
        'entry':     entry,
        'target':    target,
        'sl':        sl,
        'rr':        rr,
        'rsi':       rsi,
        'atr':       round(atr, 2),
        'macd':      macd,
        'ema9':      inds['ema9'],
        'ema21':     inds['ema21'],
        'above_ema9':   above9,
        'above_ema21':  above21,
        'above_ema50':  above50,
        'day_range':    inds['day_range'],
        'w52_range':    inds['w52_range'],
        'confidence':   conf,
        'score':     score,
        'reason':    reason,
    }

# ── ROUTES ────────────────────────────────────────────────

@app.route('/')
def home():
    return jsonify({'status': 'InvestIN API v2.0 — Technical Indicators'})

@app.route('/indices')
def indices():
    try:
        s = get_session()
        r = s.get('https://www.nseindia.com/api/allIndices', timeout=10)
        data = r.json().get('data', [])
        result = {}
        for item in data:
            name = item.get('index', '')
            if name in ['NIFTY 50', 'NIFTY BANK', 'NIFTY IT', 'INDIA VIX']:
                result[name] = {
                    'name':   name,
                    'price':  float(item.get('last', 0)),
                    'change': float(item.get('variation', 0)),
                    'pct':    float(item.get('percentChange', 0)),
                }
        return jsonify({'status': 'ok', 'data': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/quote/<symbol>')
def quote_route(symbol):
    data = fetch_quote(symbol.upper())
    if data:
        return jsonify({'status': 'ok', 'data': data})
    return jsonify({'status': 'error'}), 500

@app.route('/quotes/<symbols>')
def quotes_route(symbols):
    sym_list = [s.strip().upper() for s in symbols.split(',')[:15]]
    results = {}
    for sym in sym_list:
        data = fetch_quote(sym)
        if data:
            results[sym] = data
        time.sleep(0.3)
    return jsonify({'status': 'ok', 'data': results})

@app.route('/scan/<mode>')
def scan(mode):
    """Full technical scan with RSI, ATR, EMA, MACD indicators"""
    if mode not in ['intraday', 'swing']:
        mode = 'intraday'

    try:
        s = get_session()
        r1 = s.get('https://www.nseindia.com/api/live-analysis-variations?index=gainers', timeout=10)
        gainers_raw = r1.json().get('NIFTY', {}).get('data', [])[:8]
        time.sleep(0.5)
        r2 = s.get('https://www.nseindia.com/api/live-analysis-variations?index=loosers', timeout=10)
        losers_raw  = r2.json().get('NIFTY', {}).get('data', [])[:8]
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

    signals = []

    # BUY signals from gainers
    buy_count = 0
    for item in gainers_raw:
        if buy_count >= 5:
            break
        sym = item.get('symbol', '')
        if not sym:
            continue
        try:
            quote = fetch_quote(sym)
            if not quote or quote['price'] <= 0:
                continue
            time.sleep(0.3)
            inds   = compute_indicators(sym, quote)
            signal = generate_signal(quote, inds, mode)
            signals.append(signal)
            buy_count += 1
        except Exception as e:
            continue

    # SELL signals from losers
    sell_count = 0
    for item in losers_raw:
        if sell_count >= 5:
            break
        sym = item.get('symbol', '')
        if not sym:
            continue
        try:
            quote = fetch_quote(sym)
            if not quote or quote['price'] <= 0:
                continue
            time.sleep(0.3)
            inds   = compute_indicators(sym, quote)
            signal = generate_signal(quote, inds, mode)
            signals.append(signal)
            sell_count += 1
        except Exception as e:
            continue

    return jsonify({
        'status': 'ok',
        'mode':   mode,
        'count':  len(signals),
        'data':   signals
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
