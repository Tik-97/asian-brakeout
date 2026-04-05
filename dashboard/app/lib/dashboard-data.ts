import { promises as fs } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const dataDir = path.resolve(__dirname, "../../public/data");

export type Summary = {
  AccountCurrency: string;
  InitialDepositUSD: number;
  PriceModel: string;
  NetPnLUSD: number;
  TotalWithdrawnUSD: number;
  FinalTradingEquityUSD: number;
  EndingTotalValueUSD: number;
  ReturnPctOnInitial: number;
  AcceptedTrades: number;
  WinRatePct: number;
  ProfitFactor: number;
  MaxDrawdownTotalValuePct: number;
  TotalOvernightFundingUSD: number;
};

export type TradeRow = {
  symbol: string;
  side: string;
  fill_time_utc: string;
  exit_time_utc: string;
  exit_reason: string;
  portfolio_pnl_account: string | number;
  accepted?: string;
};

export type EventRow = {
  time: string;
  event_type: string;
  symbol: string;
  trading_equity: string | number;
  total_value: string | number;
  withdrawal_amount: string | number;
};

export type WithdrawalRow = {
  time_utc: string;
  symbol: string;
  withdrawal_kind: string;
  withdrawal_amount: string | number;
  trading_equity_after_withdrawal: string | number;
};

export type DashboardData = {
  summary: Summary;
  trades: TradeRow[];
  wins: TradeRow[];
  losses: TradeRow[];
  events: EventRow[];
  withdrawals: WithdrawalRow[];
};

export type LivePairStatus = {
  symbol: string;
  has_pending_order?: boolean;
  has_open_position?: boolean;
  open_pnl?: number;
  asian_high?: number | string;
  asian_low?: number | string;
  breakout_detected?: boolean;
  breakout_side?: string;
  entry?: number | string;
  stop_loss?: number | string;
  take_profit?: number | string;
  fill_price?: number | string;
  block_reason?: string;
  position_status?: string;
};

export type LiveStatus = {
  updated_at_utc?: string;
  account?: {
    balance?: number;
    available?: number;
    margin?: number;
    currency?: string;
    open_positions?: number;
    working_orders?: number;
    open_pnl?: number;
  };
  pairs?: LivePairStatus[];
};

export type PairRoomData = {
  symbol: string;
  title: string;
  personality: string;
  roomTheme: string;
  contributionBalance: number;
  contributionPnl: number;
  winRatePct: number;
  wins: number;
  losses: number;
  lastTradePnl: number;
  lastTradeResult: "TP" | "SL" | "EXIT";
  lastTradeMood: "happy" | "frustrated";
  drawdownPct: number;
  latestEquity: number;
  curveValues: number[];
  pnlValues: number[];
  recentTrades: TradeRow[];
};

export type TradingHouseData = DashboardData & {
  liveStatus: LiveStatus | null;
  rooms: PairRoomData[];
};

type LiveDashboardPayload = DashboardData & {
  liveStatus?: LiveStatus | null;
};

function parseCsv<T>(text: string): T[] {
  const trimmed = text.trim();
  if (!trimmed) {
    return [];
  }
  const lines = trimmed.split(/\r?\n/);
  if (lines.length <= 1) {
    return [];
  }
  const headers = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const values = line.split(",");
    return headers.reduce<Record<string, string>>((acc, header, index) => {
      acc[header] = values[index] ?? "";
      return acc;
    }, {}) as T;
  });
}

async function readDataFile(fileName: string) {
  const filePath = path.join(dataDir, fileName);
  return fs.readFile(filePath, "utf-8");
}

async function readOptionalDataFile(fileName: string) {
  const filePath = path.join(dataDir, fileName);
  try {
    return await fs.readFile(filePath, "utf-8");
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

function normalizeLiveDashboardPayload(payload: LiveDashboardPayload | null): LiveDashboardPayload | null {
  if (!payload || typeof payload !== "object" || !payload.summary) {
    return null;
  }

  return {
    summary: payload.summary,
    trades: payload.trades ?? [],
    wins: payload.wins ?? [],
    losses: payload.losses ?? [],
    events: payload.events ?? [],
    withdrawals: payload.withdrawals ?? [],
    liveStatus: payload.liveStatus ?? null,
  };
}

async function readLiveDashboardSnapshot(): Promise<LiveDashboardPayload | null> {
  const liveDashboardText = await readOptionalDataFile("live_dashboard.json");
  if (!liveDashboardText) {
    return null;
  }

  try {
    return normalizeLiveDashboardPayload(JSON.parse(liveDashboardText) as LiveDashboardPayload);
  } catch {
    return null;
  }
}

export async function loadDashboardData(): Promise<LiveDashboardPayload> {
  const liveDashboard = await readLiveDashboardSnapshot();
  if (liveDashboard) {
    return liveDashboard;
  }

  const [summaryText, tradesText, winsText, lossesText, eventsText, withdrawalsText] = await Promise.all([
    readDataFile("yearly_backtest_2025_2026_GBPJPY_EURJPY_summary.json"),
    readDataFile("yearly_backtest_2025_2026_GBPJPY_EURJPY_real_traded.csv"),
    readDataFile("yearly_backtest_2025_2026_GBPJPY_EURJPY_real_wins.csv"),
    readDataFile("yearly_backtest_2025_2026_GBPJPY_EURJPY_real_losses.csv"),
    readDataFile("yearly_backtest_2025_2026_GBPJPY_EURJPY_events.csv"),
    readDataFile("yearly_backtest_2025_2026_GBPJPY_EURJPY_withdrawals.csv"),
  ]);

  return {
    summary: JSON.parse(summaryText) as Summary,
    trades: parseCsv<TradeRow>(tradesText),
    wins: parseCsv<TradeRow>(winsText),
    losses: parseCsv<TradeRow>(lossesText),
    events: parseCsv<EventRow>(eventsText),
    withdrawals: parseCsv<WithdrawalRow>(withdrawalsText),
  };
}

function round2(value: number) {
  return Math.round(value * 100) / 100;
}

function pairMeta(symbol: string) {
  if (symbol === "EURJPY") {
    return {
      title: "Room 1",
      personality: "Calm, analytical, minimalist",
      roomTheme: "euro",
    };
  }
  return {
    title: "Room 2",
    personality: "Aggressive, energetic, reactive",
    roomTheme: "sterling",
  };
}

function computeDrawdown(values: number[]) {
  let peak = Number.NEGATIVE_INFINITY;
  let maxDrawdown = 0;
  for (const value of values) {
    peak = Math.max(peak, value);
    if (peak > 0) {
      maxDrawdown = Math.min(maxDrawdown, ((value - peak) / peak) * 100);
    }
  }
  return maxDrawdown;
}

function inferTradeResult(exitReason: string) {
  if (exitReason === "take_profit") {
    return "TP";
  }
  if (exitReason === "stop_loss") {
    return "SL";
  }
  return "EXIT";
}

export async function loadTradingHouseData(): Promise<TradingHouseData> {
  const base = await loadDashboardData();
  const liveStatusText = await readOptionalDataFile("live_status.json");
  const acceptedTrades = base.trades.filter((trade) => String(trade.accepted).toLowerCase() !== "false");
  const symbols = ["EURJPY", "GBPJPY"];

  const rooms: PairRoomData[] = symbols.map((symbol) => {
    const trades = acceptedTrades.filter((trade) => trade.symbol === symbol);
    let runningContribution = base.summary.InitialDepositUSD / symbols.length;
    const curveValues = trades.map((trade) => {
      runningContribution += Number(trade.portfolio_pnl_account);
      return round2(runningContribution);
    });
    const pnlValues = trades.map((trade) => round2(Number(trade.portfolio_pnl_account)));
    const wins = trades.filter((trade) => Number(trade.portfolio_pnl_account) > 0).length;
    const losses = trades.filter((trade) => Number(trade.portfolio_pnl_account) <= 0).length;
    const lastTrade = trades.at(-1);
    const lastTradePnl = lastTrade ? Number(lastTrade.portfolio_pnl_account) : 0;
    const meta = pairMeta(symbol);

    return {
      symbol,
      title: meta.title,
      personality: meta.personality,
      roomTheme: meta.roomTheme,
      contributionBalance: curveValues.at(-1) ?? base.summary.InitialDepositUSD / symbols.length,
      contributionPnl: round2(trades.reduce((sum, trade) => sum + Number(trade.portfolio_pnl_account), 0)),
      winRatePct: trades.length ? (wins / trades.length) * 100 : 0,
      wins,
      losses,
      lastTradePnl,
      lastTradeResult: inferTradeResult(lastTrade?.exit_reason ?? ""),
      lastTradeMood: lastTradePnl >= 0 ? "happy" : "frustrated",
      drawdownPct: computeDrawdown(curveValues),
      latestEquity: curveValues.at(-1) ?? 0,
      curveValues,
      pnlValues,
      recentTrades: trades.slice(-8),
    };
  });

  return {
    ...base,
    liveStatus: base.liveStatus ?? (liveStatusText ? (JSON.parse(liveStatusText) as LiveStatus) : null),
    rooms,
  };
}
