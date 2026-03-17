import { useState, useEffect, useRef } from 'react';

// Types from Backend
type PrecioData = { precio: number; cambio_pct: number; volumen: number; ts: string };
type EtfData = { net_flow_hoy_millones: number; acumulado_millones: number; ultima_actualizacion: string; error: string; detalle: any[] };
type YieldsData = { valor: number; cambio_bps: number; cambio_pct: number; ultima_actualizacion: string; error: string };
type CorrelacionesData = { spy_btc_60m: number; spy_uso_60m: number; ultima_actualizacion: string };
type MacroData = { sentiment_score: number; noticias: any[]; ultima_actualizacion: string; error: string };

type StoreData = {
  precios: Record<string, PrecioData>;
  btc_etf_inflows: EtfData;
  yields: Record<string, YieldsData>;
  correlaciones: CorrelacionesData;
  macro: MacroData;
  ws_conectado: boolean;
  usando_fallback: boolean;
};

// Component: Ticker Flash Effect
const TickerValue = ({ value, type = 'price', isPercent = false, isBps = false }: { value: number, type?: 'price'|'pct', isPercent?: boolean, isBps?: boolean }) => {
  const [flashClass, setFlashClass] = useState('');
  const prevValue = useRef(value);

  useEffect(() => {
    if (value !== prevValue.current && prevValue.current !== undefined) {
      setFlashClass(value > prevValue.current ? 'flash-up-text' : 'flash-down-text');
      const timer = setTimeout(() => setFlashClass(''), 800);
      prevValue.current = value;
      return () => clearTimeout(timer);
    }
    prevValue.current = value;
  }, [value]);

  let display = value?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  if (type === 'pct') {
    display = (value > 0 ? '+' : '') + value?.toFixed(2);
  }

  return (
    <span className={`${flashClass} tabular-nums`}>
      {display}{isPercent ? '%' : ''}{isBps ? ' bps' : ''}
    </span>
  );
};

export default function App() {
  const [store, setStore] = useState<StoreData | null>(null);
  const [clock, setClock] = useState('');
  
  // Watchlist & Search State
  const [watchlist, setWatchlist] = useState<string[]>(() => {
    const saved = localStorage.getItem('mb_watchlist');
    return saved ? JSON.parse(saved) : ['AAPL', 'TSLA'];
  });
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // Clock
  useEffect(() => {
    const t = setInterval(() => setClock(new Date().toISOString().substring(11, 19) + ' UTC'), 1000);
    return () => clearInterval(t);
  }, []);

  // WebSockets
  useEffect(() => {
    let timeout: number;
    const connect = () => {
      const ws = new WebSocket('ws://localhost:8000/ws');
      wsRef.current = ws;
      
      ws.onopen = () => {
        // Enviar subscripcion de watchlist guardada
        ws.send(JSON.stringify({ action: 'subscribe', symbols: watchlist }));
      };
      
      ws.onmessage = (e) => {
        try { setStore(JSON.parse(e.data)); } catch(err) {}
      };
      
      ws.onclose = () => { timeout = setTimeout(connect, 2000); };
    };
    connect();
    return () => { clearTimeout(timeout); if (wsRef.current) wsRef.current.close(); };
  }, [watchlist]);

  // Search Debounce Hook
  useEffect(() => {
    if (searchQuery.length < 2) {
      setSearchResults([]);
      return;
    }
    const delayDebounceFn = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await fetch(`http://localhost:8000/api/search?q=${searchQuery}`);
        const data = await res.json();
        if (data.result) setSearchResults(data.result.slice(0, 8)); // Top 8
      } catch (err) { }
      setIsSearching(false);
    }, 400);

    return () => clearTimeout(delayDebounceFn);
  }, [searchQuery]);

  const addToWatchlist = (symbol: string) => {
    if (!watchlist.includes(symbol)) {
      const newW = [...watchlist, symbol];
      setWatchlist(newW);
      localStorage.setItem('mb_watchlist', JSON.stringify(newW));
      setSearchQuery('');
      setSearchResults([]);
      
      // Dynamic subscribe if WS open
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ action: 'subscribe', symbols: [symbol] }));
      }
    }
  };

  const removeFromWatchlist = (symbol: string) => {
    const newW = watchlist.filter(s => s !== symbol);
    setWatchlist(newW);
    localStorage.setItem('mb_watchlist', JSON.stringify(newW));
  };

  const sSpy = store?.precios['SPY'];
  const sBtc = store?.precios['BINANCE:BTCUSDT'];
  const sUso = store?.precios['USO'];
  
  const etf = store?.btc_etf_inflows;
  const tnx = store?.yields['TNX'];
  const corr = store?.correlaciones;
  const mac = store?.macro;

  const isLive = store?.ws_conectado;

  return (
    <>
      <header>
        <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          <div>
            <span className={`status-dot ${isLive ? 'status-live' : ''}`} style={{ backgroundColor: isLive ? '' : 'var(--accent-down)' }}></span>
            MB_EFICAZ_PRO // {store?.usando_fallback ? 'FALLBACK' : 'LIVE'}
          </div>
          
          {/* SEARCH BAR */}
          <div className="search-container">
            <input 
              type="text" 
              className="search-input" 
              placeholder="SEARCH ASSETS (e.g. AAPL)..." 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchResults.length > 0 && (
              <div className="search-results">
                {searchResults.map((res: any, idx: number) => (
                  <div key={idx} className="search-result-item" onClick={() => addToWatchlist(res.symbol)}>
                    <div>
                      <div className="symbol">{res.symbol}</div>
                      <div className="desc">{res.description}</div>
                    </div>
                    <div style={{ fontSize: '10px', color: 'var(--text-dim)' }}>{res.type}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div>SYS_TIME // <span className="tabular-nums">{clock}</span></div>
      </header>

      <main>
        {/* LEFT RAIL: Smart Money & Macro Quant */}
        <div className="panel">
          <div className="panel-header">Alpha & Smart Money</div>
          <div className="panel-content">
            
            {/* 10Y Yields */}
            <div style={{ marginBottom: '24px' }}>
              <div className="text-dim" style={{ fontSize: '11px', marginBottom: '4px' }}>10Y TREASURY YIELD (^TNX)</div>
              {tnx?.error && <div className="text-warn text-xs">Error: {tnx.error}</div>}
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px' }}>
                <span className="text-primary" style={{ fontSize: '1.8rem', fontWeight: 600 }}>
                  <TickerValue value={tnx?.valor || 0} isPercent={true} />
                </span>
                <span className={tnx?.cambio_bps! > 0 ? 'text-up' : 'text-down'} style={{ fontWeight: 600 }}>
                  <TickerValue value={tnx?.cambio_bps || 0} type="pct" isBps={true} />
                </span>
              </div>
            </div>

            {/* ETF Inflows */}
            <div style={{ marginBottom: '24px' }}>
              <div className="text-dim" style={{ fontSize: '11px', marginBottom: '4px' }}>BTC ETF NET INFLOWS (DAILY)</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px' }}>
                <span className={etf?.net_flow_hoy_millones! > 0 ? 'text-up' : 'text-down'} style={{ fontSize: '1.8rem', fontWeight: 600 }}>
                  {etf?.net_flow_hoy_millones! > 0 ? '+' : ''}{etf?.net_flow_hoy_millones?.toFixed(1)}M
                </span>
              </div>
              <div className="text-dim" style={{ fontSize: '11px', marginTop: '4px' }}>
                CUMULATIVE: {etf?.acumulado_millones}M
              </div>
            </div>

            {/* Correlations */}
            <div>
              <div className="text-dim" style={{ fontSize: '11px', marginBottom: '8px' }}>P-CORRELATION (ROLLING 60m)</div>
              <table className="quant-table">
                <thead><tr><th>ASSET PAIR</th><th>COEF</th></tr></thead>
                <tbody>
                  <tr>
                    <td>SPY / BTC</td>
                    <td className="tabular-nums text-primary">{corr?.spy_btc_60m?.toFixed(2)}</td>
                  </tr>
                  <tr>
                    <td>SPY / USO</td>
                    <td className="tabular-nums text-primary">{corr?.spy_uso_60m?.toFixed(2)}</td>
                  </tr>
                </tbody>
              </table>
              <div className="text-dim" style={{ fontSize: '10px', marginTop: '8px' }}>
                UPDT: {corr?.ultima_actualizacion}
              </div>
            </div>

          </div>
        </div>

        {/* CENTER: Action Grid */}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          
          <div className="multi-row" style={{ height: '50%' }}>
            {/* SPY */}
            <div className="panel" style={{ borderBottom: '1px solid var(--panel-border)' }}>
              <div className="panel-header" style={{ color: 'var(--accent-brand)' }}>EQUITY INDEX (PROXY)</div>
              <div className="panel-content" style={{ justifyContent: 'center' }}>
                <div className="ticker-box">
                  <span className="ticker-symbol">SPY</span>
                  <span className="ticker-price text-primary">
                    <TickerValue value={sSpy?.precio || 0} />
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span className="text-dim">VOL: {sSpy?.volumen?.toLocaleString()}</span>
                  <span className={`px-2 py-1 rounded font-semibold ${sSpy?.cambio_pct! > 0 ? 'bg-up text-up' : 'bg-down text-down'}`}>
                    <TickerValue value={sSpy?.cambio_pct || 0} type="pct" isPercent={true} />
                  </span>
                </div>
              </div>
            </div>

            {/* BTC */}
            <div className="panel">
              <div className="panel-header" style={{ color: '#f7931a' }}>CRYPTO ASSET</div>
              <div className="panel-content" style={{ justifyContent: 'center' }}>
                <div className="ticker-box">
                  <span className="ticker-symbol">BTCUSDT</span>
                  <span className="ticker-price text-primary">
                    <TickerValue value={sBtc?.precio || 0} />
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span className="text-dim">VOL: {(sBtc?.volumen || 0)?.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                  <span className={`px-2 py-1 rounded font-semibold ${sBtc?.cambio_pct! > 0 ? 'bg-up text-up' : 'bg-down text-down'}`}>
                    <TickerValue value={sBtc?.cambio_pct || 0} type="pct" isPercent={true} />
                  </span>
                </div>
              </div>
            </div>
          </div>
          
          {/* USER WATCHLIST CUSTOM */}
          <div className="panel" style={{ height: '50%', borderTop: '1px solid var(--panel-border)' }}>
            <div className="panel-header">MY WATCHLIST</div>
            <div className="watchlist-grid" style={{ overflowY: 'auto' }}>
              {watchlist.map((sym, i) => {
                const data = store?.precios[sym];
                return (
                  <div key={i} className="watch-card">
                    <div className="watch-remove" onClick={() => removeFromWatchlist(sym)}>✕</div>
                    <div className="watch-symbol" style={{ color: 'var(--accent-brand)' }}>{sym}</div>
                    <div className={`watch-price ${!data ? 'text-dim' : ''}`}>
                      {data ? <TickerValue value={data.precio} /> : '---'}
                    </div>
                    <div style={{ fontSize: '11px' }} className={data?.cambio_pct! > 0 ? 'text-up' : data?.cambio_pct! < 0 ? 'text-down' : 'text-dim'}>
                      {data ? <TickerValue value={data.cambio_pct} type="pct" isPercent={true} /> : '0.00%'}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

        </div>

        {/* RIGHT RAIL: News Feed */}
        <div className="panel">
          <div className="panel-header">LIVE NEWS FEED</div>
          
          <div style={{ padding: '12px', borderBottom: '1px solid var(--panel-border)' }}>
            <div className="text-dim" style={{ fontSize: '10px', marginBottom: '4px' }}>AI SENTIMENT INDEX</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ height: '4px', flexGrow: 1, backgroundColor: '#222', borderRadius: '2px', overflow: 'hidden' }}>
                <div style={{ 
                  height: '100%', 
                  width: `${Math.min(Math.max((mac?.sentiment_score || 0) + 50, 0), 100)}%`,
                  backgroundColor: mac?.sentiment_score! > 10 ? 'var(--accent-up)' : mac?.sentiment_score! < -10 ? 'var(--accent-down)' : 'var(--accent-warn)',
                  transition: 'width 0.5s ease'
                }}></div>
              </div>
              <span className="tabular-nums" style={{ fontSize: '11px', fontWeight: 600 }}>{mac?.sentiment_score?.toFixed(1)}</span>
            </div>
          </div>

          <div className="panel-content" style={{ overflowY: 'auto' }}>
            {mac?.noticias?.map((n: any, idx: number) => (
              <div key={idx} className="news-item">
                <div className="news-time">{n.time} | {n.source.toUpperCase()}</div>
                <div style={{ fontSize: '12px' }}>{n.headline}</div>
              </div>
            ))}
          </div>

        </div>

      </main>
    </>
  );
}
