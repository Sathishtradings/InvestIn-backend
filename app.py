from flask import Flask, jsonify
from flask_cors import CORS
import requests
import json
import time

app = Flask(__name__)
CORS(app)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/',
}

cache = {}
CACHE_TTL = 60  # seconds

def get_nse_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get('https://www.nseindia.com', timeout=10)
    return s

def fetch_quote(symbol):
    key = symbol
    if key in cache and time.time() - cache[key]['ts'] < CACHE_TTL:
        return cache[key]['data']
    try:
        s = get_nse_session()
        url = f'https://www.nseindia.com/api/quote-equity?symbol={symbol}'
        r = s.get(url, timeout=10)
        d = r.json()
        pd = d.get('priceInfo', {})
        result = {
            'symbol': symbol,
            'name': d.get('info', {}).get('companyName', symbol),
            'price': pd.get('lastPrice', 0),
            'open': pd.get('open', 0),
            'high': pd.get('intraDayHighLow', {}).get('max', 0),
            'low': pd.get('intraDayHighLow', {}).get('min', 0),
            'prev': pd.get('previousClose', 0),
            'change': pd.get('change', 0),
            'pct': pd.get('pChange', 0),
            'week52High': pd.get('weekHighLow', {}).get('max', 0),
            'week52Low': pd.get('weekHighLow', {}).get('min', 0),
            'volume': d.get('marketDeptOrderBook', {}).get('tradeInfo', {}).get('totalTradedVolume', 0),
        }
        cache[key] = {'data': result, 'ts': time.time()}
        return result
    except Exception as e:
        return None

def fetch_index(index_name):
    try:
        s = get_nse_session()
        url = f'https://www.nseindia.com/api/allIndices'
        r = s.get(url, timeout=10)
        data = r.json().get('data', [])
        for item in data:
            if item.get('index') == index_name:
                return {
                    'name': index_name,
                    'price': item.get('last', 0),
                    'change': item.get('variation', 0),
                    'pct': item.get('percentChange', 0),
                }
        return None
    except:
        return None

@app.route('/')
def home():
    return jsonify({'status': 'InvestIN API running', 'version': '1.0'})

@app.route('/quote/<symbol>')
def quote(symbol):
    data = fetch_quote(symbol.upper())
    if data:
        return jsonify({'status': 'ok', 'data': data})
    return jsonify({'status': 'error', 'message': 'Could not fetch'}), 500

@app.route('/quotes/<symbols>')
def quotes(symbols):
    sym_list = symbols.upper().split(',')[:15]  # max 15
    results = {}
    for sym in sym_list:
        data = fetch_quote(sym.strip())
        if data:
            results[sym.strip()] = data
        time.sleep(0.3)
    return jsonify({'status': 'ok', 'data': results})

@app.route('/indices')
def indices():
    index_names = ['NIFTY 50', 'NIFTY BANK', 'NIFTY IT', 'INDIA VIX']
    results = {}
    for name in index_names:
        data = fetch_index(name)
        if data:
            results[name] = data
    return jsonify({'status': 'ok', 'data': results})

@app.route('/scan/<mode>')
def scan(mode):
    """Return top gainers/losers for signal scanning"""
    try:
        s = get_nse_session()
        if mode == 'gainers':
            url = 'https://www.nseindia.com/api/live-analysis-variations?index=gainers'
        elif mode == 'losers':
            url = 'https://www.nseindia.com/api/live-analysis-variations?index=loosers'
        else:
            url = 'https://www.nseindia.com/api/live-analysis-variations?index=gainers'
        r = s.get(url, timeout=10)
        data = r.json().get('NIFTY', {}).get('data', [])[:10]
        results = []
        for item in data:
            results.append({
                'symbol': item.get('symbol',''),
                'name': item.get('meta', {}).get('companyName', item.get('symbol','')),
                'price': item.get('ltp', 0),
                'change': item.get('netPrice', 0),
                'pct': item.get('netPrice', 0),
                'volume': item.get('tradedQuantity', 0),
                'high': item.get('dayHigh', 0),
                'low': item.get('dayLow', 0),
            })
        return jsonify({'status': 'ok', 'data': results})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
