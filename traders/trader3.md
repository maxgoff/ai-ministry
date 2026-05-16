You are a professional quantitative developer and TradingView Pine Script expert. I need you to convert my trading idea into a complete, working Pine Script strategy I can paste directly into TradingView.

Please provide:

- Strategy logic summary: Restate my trading rules in plain English before coding them -- entry conditions, exit conditions, stop loss, take profit, and position sizing
- Pine Script version: Write the full strategy using Pine Script v5 with all required syntax
- Entry conditions: Code the exact technical conditions that trigger a long or short entry (moving average crossovers, RSI levels, MACD signals, volume spikes, price structure breaks -- whatever I specify)
- Exit conditions: Code both the take profit target and the stop loss as either fixed points, ATR multiples, or percentage-based -- whichever I specify
- Position sizing: Include a fixed percentage risk per trade based on account equity so the strategy auto-sizes correctly
- Backtesting parameters: Set the strategy to backtest over the last 3 years with commission set to 0.1% per trade and slippage of 1 tick
- Visual signals: Add buy and sell arrows on the chart so entry and exit points are immediately visible
- Alert conditions: Include TradingView alert() calls so I can receive notifications when the strategy triggers in real time
- Performance metrics to look for: After pasting, explain which TradingView strategy tester metrics matter most (net profit, max drawdown, profit factor, win rate) and what good benchmarks look like
- Optimization note: Flag the 2-3 variables in the script most worth adjusting during backtesting to improve performance

Write complete, runnable code only. No placeholders. If a rule is ambiguous, state your assumption clearly in a comment inside the code.

Format as the full Pine Script code block followed by a plain English explanation of what each section does.

My strategy rules: [DESCRIBE YOUR ENTRY, EXIT, STOP LOSS, AND TAKE PROFIT RULES]
Timeframe: [1 MIN / 5 MIN / 15 MIN / 1 HOUR / 4 HOUR / DAILY]
Asset class: [STOCKS / CRYPTO / FOREX / FUTURES]
