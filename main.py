# main.py
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yfinance as yf
import urllib.parse
from datetime import datetime
import time
from groq import Groq
import re 
from GoogleNews import GoogleNews
import os # 新增：用來處理檔案路徑
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

app = FastAPI()

# ==========================================
# ⚠️ 路徑設定 (關鍵修改)
# ==========================================
# 取得 main.py 所在的目錄
CURRENT_DIR = Path(__file__).resolve().parent

HTML_FILE = CURRENT_DIR / "index.html"
LOGO_FILE = CURRENT_DIR / "logo.PNG"
LOGO_WHITE_FILE = CURRENT_DIR / "logo_white.png"

# ==========================================
# ⚠️ API KEY
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 1. 路由設定：讀取 index.html 與 logo
# ==========================================

@app.get("/")
async def read_root():
    if not HTML_FILE.exists():
        return {"error": f"找不到檔案: {HTML_FILE}"}
    return FileResponse(str(HTML_FILE))

@app.get("/logo.PNG")
async def get_logo():
    if not LOGO_FILE.exists():
        return {"error": "找不到 Logo 圖片"}
    return FileResponse(str(LOGO_FILE))

@app.get("/logo_white.png")
async def get_logo_white():
    if not LOGO_WHITE_FILE.exists():
        return {"error": "找不到淺色 Logo 圖片"}
    return FileResponse(str(LOGO_WHITE_FILE))
# ==========================================
# 以下為原本的股票/新聞/聊天邏輯 (維持不變)
# ==========================================

def format_ticker(symbol: str):
    symbol = symbol.upper().strip()
    if symbol.isdigit():
        return f"{symbol}.TW"
    return symbol

# ... (fetch_news_by_lib 函式維持不變) ...
def fetch_google_rss_news(query: str, lang: str = "zh"):
    """使用 Google News 官方 RSS 備援，支援文字搜索，能穩定獲得精準語系新聞"""
    try:
        if lang == 'zh':
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        else:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
        
        root = ET.fromstring(xml_data)
        news_list = []
        for item in root.findall('.//item')[:5]:
            title = item.findtext('title', default='')
            link = item.findtext('link', default='')
            pubDate = item.findtext('pubDate', default='Recent')
            source = item.find('source')
            publisher = source.text if source is not None else "Google News RSS"
            
            if pubDate != 'Recent' and len(pubDate) >= 16:
                pubDate = pubDate[:16] # 將時間簡化，例如 'Wed, 06 Dec 2023'
                
            if title and link:
                news_list.append({"title": title, "link": link, "publisher": publisher, "time": pubDate})
        return news_list
    except Exception as e:
        print(f"Google RSS 備援失敗: {e}")
        return []

def fetch_news_by_lib(query, lang='zh'):
    print(f"啟動 GoogleNews Lib: {query} (Lang: {lang})")
    formatted_results = []
    try:
        if lang == 'en':
            googlenews = GoogleNews(lang='en', region='US')
        else:
            googlenews = GoogleNews(lang='zh-TW', region='TW')
        googlenews.search(query)
        results = googlenews.result()
        googlenews.clear()
        
        for item in results[:5]:
            title = item.get('title', '')
            link = item.get('link', '')
            media = item.get('media', 'Google News')
            date = item.get('date', 'Recent')
            if not title or not link: continue
            formatted_results.append({
                "title": title, "link": link, "publisher": media, "time": date
            })
    except Exception as e:
        print(f"GoogleNews Lib Error: {e}")
    return formatted_results
def fetch_yfinance_news(ticker_name: str):
    try:
        stock = yf.Ticker(ticker_name)
        yf_news = stock.news or []
        results = []
        for n in yf_news[:5]:
            results.append({
                "title": n.get("title", ""),
                "link": n.get("link", ""),
                "publisher": n.get("publisher", "Yahoo Finance"),
                "time": datetime.fromtimestamp(n.get("providerPublishTime", 0)).strftime("%Y-%m-%d")
                        if n.get("providerPublishTime") else "Recent"
            })
        return results
    except Exception as e:
        print(f"yfinance news error: {e}")
        return []
@app.get("/api/news/{symbol}")
async def get_only_news(symbol: str, lang: str = "zh"):
    try:
        ticker_name = format_ticker(symbol)
        stock = yf.Ticker(ticker_name)
        info = stock.info

        if lang == 'zh':
            search_keyword = f"{symbol.upper()} 股票"
        else:
            search_keyword = info.get('shortName') or info.get('longName') or ticker_name

        # 先用 yfinance
        news_data = fetch_yfinance_news(ticker_name)

        # 再嘗試 GoogleNews / RSS
        if not news_data:
            news_data = fetch_news_by_lib(search_keyword, lang)

        if not news_data:
            news_data = fetch_google_rss_news(search_keyword, lang)

        return news_data
    except Exception as e:
        print(f"Get News Error: {e}")
        return []

# ... (chat_search_logic 函式維持不變) ...
def chat_search_logic(query):
    results = []

    potential_tickers = re.findall(r'[a-zA-Z0-9]+', query)
    for t in potential_tickers:
        if len(t) < 2 and not t.isdigit():
            continue
        if t.lower() in ['is', 'the', 'in', 'on', 'at', 'stock', 'news', 'buy', 'sell']:
            continue

        try:
            formatted_ticker = format_ticker(t)

            # 先用 yfinance
            yf_news = fetch_yfinance_news(formatted_ticker)
            if yf_news:
                for n in yf_news[:3]:
                    results.append(
                        f"標題: {n['title']}\n時間: {n['time']}\n來源連結: {n['link']}\n說明: {n['publisher']}"
                    )
                break

            # 再用 GoogleNews / RSS
            lib_results = fetch_news_by_lib(f"{t} 新聞", lang='zh')
            if lib_results:
                for r in lib_results[:3]:
                    results.append(
                        f"標題: {r['title']}\n時間: {r['time']}\n來源連結: {r['link']}\n說明: Google News"
                    )
                break

            rss_results = fetch_google_rss_news(f"{formatted_ticker} 股票", lang='zh')
            if rss_results:
                for n in rss_results[:3]:
                    results.append(
                        f"標題: {n['title']}\n時間: {n['time']}\n來源連結: {n['link']}\n說明: {n['publisher']}"
                    )
                break
        except Exception:
            pass

    if not results:
        return None

    return "\n\n".join(results)

@app.post("/api/chat")
async def chat_with_ai(payload: dict = Body(...)):
    user_message = payload.get("message", "")
    if not user_message:
        raise HTTPException(status_code=400, detail="Message is empty")
    try:
        search_context = chat_search_logic(user_message)
        if not search_context:
            return {"reply": "抱歉，目前網路連線受限，Google News 與 Yahoo 財經暫時無法回應，請稍後再試。"}
        
        system_prompt = f"""
        你是一個使用繁體中文回答使用者問題的專業的股市分析助手。
        【任務】請根據以下提供的「財經新聞資料」回答問題。
        【資料區】{search_context}
        【回答規則】
        1. **一定要引用資料**：內容必須基於上述新聞。
        2. **繁體中文**：請用繁體中文回答。
        3. **附上來源**：回答結尾請列出參考的新聞標題與連結。
        4. **移除空行**：回答的文字中不能夠帶有沒有任何內容的空白行。
        """
        
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
            temperature=0.3, max_completion_tokens=3000, top_p=1, stream=False
        )
        ai_response = completion.choices[0].message.content
        return {"reply": ai_response}
    except Exception as e:
        print(f"Chat Error: {e}")
        return {"reply": "抱歉，系統發生錯誤，請稍後再試。"}

@app.get("/api/stock/{symbol}")
async def get_stock_info(symbol: str, lang: str = "zh"):
    try:
        ticker_name = format_ticker(symbol)
        stock = yf.Ticker(ticker_name)
        info = stock.info
        price = info.get('currentPrice') or info.get('regularMarketPrice')
        if price is None:
            hist_today = stock.history(period="1d")
            if not hist_today.empty:
                price = hist_today['Close'].iloc[-1]
            else:
                raise HTTPException(status_code=404, detail="Stock not found")
        
        if lang == 'zh': 
            search_keyword = f"{symbol.upper()} 股票"
        else: 
            search_keyword = info.get('shortName') or info.get('longName') or ticker_name
        
        news_data = fetch_news_by_lib(search_keyword, lang)

        if not news_data:
            print(f"GoogleNews 無結果，啟動 Google RSS 備援取得 {search_keyword} 新聞...")
            news_data = fetch_google_rss_news(search_keyword, lang)

        return {
            "symbol": ticker_name, "name": info.get('longName', ticker_name),
            "price": price, "currency": info.get('currency', 'USD'),
            "day_high": info.get('dayHigh', 'N/A'), "day_low": info.get('dayLow', 'N/A'),
            "volume": info.get('volume', 'N/A'), "previous_close": info.get('previousClose', 'N/A'),
            "pe_ratio": info.get('trailingPE', 'N/A'), "year_high": info.get('fiftyTwoWeekHigh', 'N/A'),
            "year_low": info.get('fiftyTwoWeekLow', 'N/A'), "news": news_data
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market-indices")
async def get_market_indices():
    indices_symbols = {
        "^TWII": "加權指數",
        "^GSPC": "標普 500",
        "^DJI": "道瓊工業",
        "^IXIC": "納斯達克"
    }
    results = []
    try:
        for symbol, name in indices_symbols.items():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_price = hist['Close'].iloc[-1]
                change = curr_price - prev_close
                pct_change = (change / prev_close) * 100
                results.append({
                    "symbol": symbol, "name": name,
                    "price": curr_price, "change": change, "percent_change": pct_change
                })
        return results
    except Exception as e:
        print(f"Indices Error: {e}")
        return []

@app.get("/api/history/{symbol}")
async def get_stock_history(symbol: str, period: str = "1y", interval: str = "1d"):
    try:
        ticker_name = format_ticker(symbol)
        stock = yf.Ticker(ticker_name)
        hist = stock.history(period=period, interval=interval)
        if hist.empty: raise HTTPException(status_code=404, detail="No history data found")
        dates = hist.index.strftime('%Y-%m-%d %H:%M').tolist()
        def floor_val(x): return int(x * 1000) / 1000.0
        return {
            "dates": dates,
            "open": [floor_val(x) for x in hist['Open'].tolist()],
            "high": [floor_val(x) for x in hist['High'].tolist()],
            "low": [floor_val(x) for x in hist['Low'].tolist()],
            "close": [floor_val(x) for x in hist['Close'].tolist()],
            "volume": hist['Volume'].tolist()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
