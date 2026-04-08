"use client";

import { startTransition, useEffect, useMemo, useState } from "react";

import type { LivePairStatus, TradingHouseData } from "../lib/dashboard-data";

const pairLogos: Record<string, string> = {
  GBPJPY: "/gbp-jpy.svg",
  EURJPY: "/eur-jpy.svg",
  USDJPY: "/usd-jpy.svg",
  AUDJPY: "/aud-jpy.svg",
};

type CharacterMood = "idle" | "waiting" | "happy" | "angry";
type RoomKey = "skeleton" | "zombie";
type TraderDialogueStage = "prompt" | "report";

type TraderDialogueState = {
  room: RoomKey;
  symbol: string;
  stage: TraderDialogueStage;
};

type FightPose = "idle" | "attack" | "hurt" | "dying";
type FightSide = "player" | "enemy";

type FightTeamState = {
  roster: string[];
  index: number;
  health: number;
  pose: FightPose;
};

type FightState = {
  playerTeam: FightTeamState;
  enemyTeam: FightTeamState;
  turn: FightSide;
  marker: number;
  direction: 1 | -1;
  message: string;
  banner: string | null;
  winner: FightSide | null;
  locked: boolean;
};

type RoomCharacterConfig = {
  name: string;
  idle: string;
  waiting: string;
  happy: string;
  angry: string;
  attack: string;
  hurt: string;
  dying: string;
};

type RoomSceneConfig = {
  key: RoomKey;
  title: string;
  backgroundSrc: string;
  dashboardSrc: string;
  promptSprite: string;
  promptName: string;
  navigateLabel: string;
  helperLabel: string;
  traders: [string, string];
  characters: Record<string, RoomCharacterConfig>;
  fightTeam: string[];
};

const skeletonRoomConfig: RoomSceneConfig = {
  key: "skeleton",
  title: "Skeleton Room",
  backgroundSrc: "/BackgroundSkeleton.png",
  dashboardSrc: "/DashboardSkeleton.png",
  promptSprite: "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Idle/0_Skeleton_Crusader_Idle_000.png",
  promptName: "King Tigran",
  navigateLabel: "Go to Zombie Room",
  helperLabel: "Tap on trader for daily report",
  traders: ["EURJPY", "GBPJPY"],
  characters: {
    EURJPY: {
      name: "Sir Antosh",
      idle: "/Characters/Skeletons/Antosh EURJPY/PNG/PNG Sequences/Idle/0_Skeleton_Crusader_Idle_000.png",
      waiting:
        "/Characters/Skeletons/Antosh EURJPY/PNG/PNG Sequences/Idle Blinking/0_Skeleton_Crusader_Idle Blinking_009.png",
      happy:
        "/Characters/Skeletons/Antosh EURJPY/PNG/PNG Sequences/Walking/0_Skeleton_Crusader_Walking_011.png",
      angry: "/Characters/Skeletons/Antosh EURJPY/PNG/PNG Sequences/Hurt/0_Skeleton_Crusader_Hurt_006.png",
      attack: "/Characters/Skeletons/Antosh EURJPY/PNG/PNG Sequences/Slashing/0_Skeleton_Crusader_Slashing_011.png",
      hurt: "/Characters/Skeletons/Antosh EURJPY/PNG/PNG Sequences/Hurt/0_Skeleton_Crusader_Hurt_011.png",
      dying: "/Characters/Skeletons/Antosh EURJPY/PNG/PNG Sequences/Dying/0_Skeleton_Crusader_Dying_014.png",
    },
    GBPJPY: {
      name: "Gevor Bones",
      idle: "/Characters/Skeletons/Gevor GBPJPY/PNG/PNG Sequences/Idle/0_Skeleton_Crusader_Idle_000.png",
      waiting:
        "/Characters/Skeletons/Gevor GBPJPY/PNG/PNG Sequences/Idle Blinking/0_Skeleton_Crusader_Idle Blinking_009.png",
      happy:
        "/Characters/Skeletons/Gevor GBPJPY/PNG/PNG Sequences/Walking/0_Skeleton_Crusader_Walking_011.png",
      angry: "/Characters/Skeletons/Gevor GBPJPY/PNG/PNG Sequences/Hurt/0_Skeleton_Crusader_Hurt_006.png",
      attack: "/Characters/Skeletons/Gevor GBPJPY/PNG/PNG Sequences/Slashing/0_Skeleton_Crusader_Slashing_011.png",
      hurt: "/Characters/Skeletons/Gevor GBPJPY/PNG/PNG Sequences/Hurt/0_Skeleton_Crusader_Hurt_011.png",
      dying: "/Characters/Skeletons/Gevor GBPJPY/PNG/PNG Sequences/Dying/0_Skeleton_Crusader_Dying_014.png",
    },
    TIKO: {
      name: "King Tigran",
      idle: "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Idle/0_Skeleton_Crusader_Idle_000.png",
      waiting:
        "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Idle Blinking/0_Skeleton_Crusader_Idle Blinking_009.png",
      happy: "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Walking/0_Skeleton_Crusader_Walking_011.png",
      angry: "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Hurt/0_Skeleton_Crusader_Hurt_006.png",
      attack: "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Slashing/0_Skeleton_Crusader_Slashing_011.png",
      hurt: "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Hurt/0_Skeleton_Crusader_Hurt_011.png",
      dying: "/Characters/Skeletons/Tiko/PNG/PNG Sequences/Dying/0_Skeleton_Crusader_Dying_014.png",
    },
  },
  fightTeam: ["EURJPY", "GBPJPY", "TIKO"],
};

const zombieRoomConfig: RoomSceneConfig = {
  key: "zombie",
  title: "Zombie Room",
  backgroundSrc: "/BackgroundZombie.png",
  dashboardSrc: "/DashboardZombie.png",
  promptSprite: "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Idle/0_Zombie_Villager_Idle_000.png",
  promptName: "Rotface Chief",
  navigateLabel: "Back to Skeleton Room",
  helperLabel: "Tap on trader for daily report",
  traders: ["USDJPY", "AUDJPY"],
  characters: {
    USDJPY: {
      name: "Dollar Rot",
      idle: "/Characters/Zombie/Zombie_Villager_1/PNG/PNG Sequences/Idle/0_Zombie_Villager_Idle_000.png",
      waiting:
        "/Characters/Zombie/Zombie_Villager_1/PNG/PNG Sequences/Idle Blinking/0_Zombie_Villager_Idle Blinking_009.png",
      happy: "/Characters/Zombie/Zombie_Villager_1/PNG/PNG Sequences/Walking/0_Zombie_Villager_Walking_011.png",
      angry: "/Characters/Zombie/Zombie_Villager_1/PNG/PNG Sequences/Hurt/0_Zombie_Villager_Hurt_006.png",
      attack: "/Characters/Zombie/Zombie_Villager_1/PNG/PNG Sequences/Slashing/0_Zombie_Villager_Slashing_011.png",
      hurt: "/Characters/Zombie/Zombie_Villager_1/PNG/PNG Sequences/Hurt/0_Zombie_Villager_Hurt_011.png",
      dying: "/Characters/Zombie/Zombie_Villager_1/PNG/PNG Sequences/Dying/0_Zombie_Villager_Dying_014.png",
    },
    AUDJPY: {
      name: "Aussie Bite",
      idle: "/Characters/Zombie/Zombie_Villager_2/PNG/PNG Sequences/Idle/0_Zombie_Villager_Idle_000.png",
      waiting:
        "/Characters/Zombie/Zombie_Villager_2/PNG/PNG Sequences/Idle Blinking/0_Zombie_Villager_Idle Blinking_009.png",
      happy: "/Characters/Zombie/Zombie_Villager_2/PNG/PNG Sequences/Walking/0_Zombie_Villager_Walking_011.png",
      angry: "/Characters/Zombie/Zombie_Villager_2/PNG/PNG Sequences/Hurt/0_Zombie_Villager_Hurt_006.png",
      attack: "/Characters/Zombie/Zombie_Villager_2/PNG/PNG Sequences/Slashing/0_Zombie_Villager_Slashing_011.png",
      hurt: "/Characters/Zombie/Zombie_Villager_2/PNG/PNG Sequences/Hurt/0_Zombie_Villager_Hurt_011.png",
      dying: "/Characters/Zombie/Zombie_Villager_2/PNG/PNG Sequences/Dying/0_Zombie_Villager_Dying_014.png",
    },
    CHIEF: {
      name: "Rotface",
      idle: "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Idle/0_Zombie_Villager_Idle_000.png",
      waiting:
        "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Idle Blinking/0_Zombie_Villager_Idle Blinking_009.png",
      happy: "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Walking/0_Zombie_Villager_Walking_011.png",
      angry: "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Hurt/0_Zombie_Villager_Hurt_006.png",
      attack: "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Slashing/0_Zombie_Villager_Slashing_011.png",
      hurt: "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Hurt/0_Zombie_Villager_Hurt_011.png",
      dying: "/Characters/Zombie/Zombie_Villager_3/PNG/PNG Sequences/Dying/0_Zombie_Villager_Dying_014.png",
    },
  },
  fightTeam: ["USDJPY", "AUDJPY", "CHIEF"],
};

const roomConfigs: Record<RoomKey, RoomSceneConfig> = {
  skeleton: skeletonRoomConfig,
  zombie: zombieRoomConfig,
};

const FIGHT_MAX_HEALTH = 100;
const FIGHT_GREEN_MIN = 44;
const FIGHT_GREEN_MAX = 56;

function getOpponentRoomKey(room: RoomKey): RoomKey {
  return room === "skeleton" ? "zombie" : "skeleton";
}

function createFightState(scene: RoomSceneConfig): FightState {
  const enemyScene = roomConfigs[getOpponentRoomKey(scene.key)];
  const firstPlayer = scene.fightTeam[0];
  const firstEnemy = enemyScene.fightTeam[0];
  return {
    playerTeam: {
      roster: scene.fightTeam,
      index: 0,
      health: fighterMaxHealth(firstPlayer),
      pose: "idle",
    },
    enemyTeam: {
      roster: enemyScene.fightTeam,
      index: 0,
      health: fighterMaxHealth(firstEnemy),
      pose: "idle",
    },
    turn: "player",
    marker: 0,
    direction: 1,
    message: `${scene.characters[scene.fightTeam[0]].name} enters the arena.`,
    banner: "Fight!",
    winner: null,
    locked: false,
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function fighterMaxHealth(fighterId: string) {
  if (fighterId === "TIKO" || fighterId === "CHIEF") {
    return 140;
  }
  return FIGHT_MAX_HEALTH;
}

function fighterSprite(character: RoomCharacterConfig, pose: FightPose) {
  if (pose === "attack") {
    return character.attack;
  }
  if (pose === "hurt") {
    return character.hurt;
  }
  if (pose === "dying") {
    return character.dying;
  }
  return character.idle;
}

function renderPairBadge(symbol: string, sizeClass: "small" | "tiny" = "small") {
  const logo = pairLogos[symbol];
  if (!logo) {
    return <span className={`pair-text ${sizeClass}`}>{symbol}</span>;
  }
  return <img src={logo} alt={`${symbol} logo`} className={`pair-logo ${sizeClass}`} />;
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function buildLinePath(values: number[], width: number, height: number) {
  if (!values.length) {
    return "";
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function sessionTheme(nowUtc: Date) {
  const hour = nowUtc.getUTCHours();
  if (hour >= 0 && hour < 8) {
    return { label: "Asian Glow", className: "session-asian" };
  }
  if (hour >= 8 && hour < 16) {
    return { label: "London Pulse", className: "session-london" };
  }
  return { label: "Overnight Drift", className: "session-night" };
}

function resolveCharacterMood(data: TradingHouseData, symbol: string): CharacterMood {
  const livePair = data.liveStatus?.pairs?.find((pair) => pair.symbol === symbol);
  const todayUtc = data.liveStatus?.updated_at_utc?.slice(0, 10) ?? "";
  if (livePair?.has_pending_order) {
    return "waiting";
  }
  if (livePair?.has_open_position) {
    const openPnl = Number(livePair.open_pnl ?? 0);
    if (openPnl > 0) {
      return "happy";
    }
    if (openPnl < 0) {
      return "angry";
    }
    return "idle";
  }
  if (livePair?.latest_trade_closed_at?.slice(0, 10) === todayUtc) {
    const latestTradePnl = Number(livePair.latest_trade_pnl ?? 0);
    if (latestTradePnl > 0) {
      return "happy";
    }
    if (latestTradePnl < 0) {
      return "angry";
    }
  }
  return "idle";
}

function moodSpeech(mood: CharacterMood) {
  if (mood === "happy") {
    return "Yuhu!";
  }
  if (mood === "angry") {
    return "Grrrr...";
  }
  if (mood === "waiting") {
    return "Come on...";
  }
  return "...";
}

function traderSpeech(data: TradingHouseData, symbol: string, mood: CharacterMood) {
  const livePair = data.liveStatus?.pairs?.find((pair) => pair.symbol === symbol);
  if (livePair?.has_open_position) {
    return "Let's do it";
  }
  if (livePair?.block_reason) {
    return "⚠️";
  }
  if (livePair?.has_pending_order) {
    return "On it...";
  }
  return moodSpeech(mood);
}

function previewPairStatus(livePair: LivePairStatus | undefined) {
  if (livePair?.has_open_position) {
    return { label: "Open", className: "state-open" };
  }
  if (livePair?.has_pending_order) {
    return { label: "Pending", className: "state-pending" };
  }
  if (livePair?.block_reason) {
    return { label: "Blocked", className: "state-blocked" };
  }
  if (livePair?.breakout_detected) {
    return { label: "Triggered", className: "state-triggered" };
  }
  return { label: "Watching", className: "state-idle" };
}

function previewPairDetail(livePair: LivePairStatus | undefined, fallbackWinRate: number) {
  if (livePair?.has_open_position) {
    return `P&L ${formatMoney(Number(livePair.open_pnl ?? 0))}`;
  }
  if (livePair?.has_pending_order && livePair.entry !== undefined) {
    return `Entry ${formatLevel(livePair.entry)}`;
  }
  if (livePair?.block_reason) {
    return "No entry";
  }
  return `${formatPct(fallbackWinRate)} WR`;
}

function formatLevel(value: number | string | undefined) {
  if (value === undefined || value === null || value === "") {
    return "n/a";
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return numeric.toFixed(3);
  }
  return String(value);
}

function extractUtcDate(value: string | undefined) {
  if (!value) {
    return "";
  }
  const normalized = value.includes(" ") ? value.replace(" ", "T") : value;
  return normalized.slice(0, 10);
}

function weekendDayName(currentUtc: Date) {
  const day = currentUtc.getUTCDay();
  if (day === 6) {
    return "Saturday";
  }
  if (day === 0) {
    return "Sunday";
  }
  return null;
}

function buildTraderUpdate(data: TradingHouseData, symbol: string, currentUtc: Date) {
  const weekendName = weekendDayName(currentUtc);
  const livePair = data.liveStatus?.pairs?.find((pair) => pair.symbol === symbol);
  const room = data.rooms.find((item) => item.symbol === symbol);
  const todayUtc = data.liveStatus?.updated_at_utc?.slice(0, 10) ?? "";
  const todayTrades = data.trades.filter((trade) => {
    if (trade.symbol !== symbol) {
      return false;
    }
    const fillDate = extractUtcDate(trade.fill_time_utc);
    const exitDate = extractUtcDate(trade.exit_time_utc);
    if (!todayUtc) {
      return false;
    }
    return fillDate === todayUtc || exitDate === todayUtc;
  });
  const latestTodayTrade = todayTrades.at(-1);
  const latestKnownTrade = room?.recentTrades.at(-1);

  const lines: string[] = [];
  lines.push("Boss, today stats are following...");
  lines.push(`Bid: ${formatLevel(livePair?.bid)}`);
  lines.push(`Ask: ${formatLevel(livePair?.ask)}`);
  lines.push(`Mid: ${formatLevel(livePair?.mid_price)}`);

  if (weekendName) {
    lines.push(`Boss, today is ${weekendName}.`);
    lines.push("Market is resting.");
    lines.push("No breakout updates for now.");
    return lines;
  }

  if (livePair?.asian_high !== undefined || livePair?.asian_low !== undefined) {
    lines.push(`Asian High: ${formatLevel(livePair?.asian_high)}`);
    lines.push(`Asian Low: ${formatLevel(livePair?.asian_low)}`);
  } else {
    lines.push("Asian High: n/a");
    lines.push("Asian Low: n/a");
  }

  if (livePair?.has_open_position) {
    lines.push(`Position open: ${livePair.breakout_side ?? "active"}`);
    lines.push(`Entry: ${formatLevel(livePair.entry ?? livePair.fill_price)}`);
    lines.push(`SL: ${formatLevel(livePair.stop_loss)}`);
    lines.push(`TP: ${formatLevel(livePair.take_profit)}`);
    lines.push(`P&L: ${formatMoney(Number(livePair.open_pnl ?? 0))}`);
  } else if (livePair?.has_pending_order) {
    lines.push(`Breakout detected: ${livePair.breakout_side ?? "yes"}`);
    lines.push("Position filled: no");
    if (livePair.entry !== undefined) {
      lines.push(`Entry: ${formatLevel(livePair.entry)}`);
    }
    if (livePair.stop_loss !== undefined) {
      lines.push(`SL: ${formatLevel(livePair.stop_loss)}`);
    }
    if (livePair.take_profit !== undefined) {
      lines.push(`TP: ${formatLevel(livePair.take_profit)}`);
    }
  } else if (livePair?.breakout_detected) {
    lines.push(`Breakout detected: ${livePair.breakout_side ?? "yes"}`);
    lines.push("Position opened: no");
    lines.push(`Reason: ${livePair.block_reason ?? livePair.position_status ?? "not provided"}`);
  } else if (todayTrades.length > 0 && latestTodayTrade) {
    const pnl = Number(latestTodayTrade.portfolio_pnl_account);
    lines.push("No live snapshot connected.");
    lines.push(`Latest today trade: ${latestTodayTrade.exit_reason}`);
    lines.push(`P&L: ${formatMoney(pnl)}`);
  } else if (livePair) {
    lines.push("No breakout detected.");
    lines.push("No position opened.");
  } else if (latestKnownTrade) {
    const pnl = Number(latestKnownTrade.portfolio_pnl_account);
    lines.push("Live day snapshot not connected.");
    lines.push(`Last closed trade: ${latestKnownTrade.exit_reason}`);
    lines.push(`P&L: ${formatMoney(pnl)}`);
  } else {
    lines.push("No breakout detected.");
    lines.push("No position opened.");
  }

  return lines;
}

export function Dashboard({ data }: { data: TradingHouseData }) {
  const [currentData, setCurrentData] = useState(data);
  const [nowUtc, setNowUtc] = useState<Date | null>(null);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [traderDialogue, setTraderDialogue] = useState<TraderDialogueState | null>(null);
  const [activeRoom, setActiveRoom] = useState<RoomKey>("skeleton");
  const [fightOpen, setFightOpen] = useState(false);
  const [fightState, setFightState] = useState<FightState>(() => createFightState(roomConfigs.skeleton));
  const activeScene = roomConfigs[activeRoom];

  useEffect(() => {
    setCurrentData(data);
  }, [data]);

  useEffect(() => {
    setNowUtc(new Date());
    const timer = window.setInterval(() => setNowUtc(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;

    async function refreshLiveDashboard() {
      try {
        const response = await fetch("/api/live-dashboard", { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as TradingHouseData;
        if (!active || !payload?.summary) {
          return;
        }
        startTransition(() => {
          setCurrentData(payload);
        });
      } catch {
        // Keep the last good snapshot visible when polling fails.
      }
    }

    void refreshLiveDashboard();
    const timer = window.setInterval(() => {
      void refreshLiveDashboard();
    }, 20_000);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!fightOpen) {
      return;
    }

    const timer = window.setInterval(() => {
      setFightState((current) => {
        if (current.winner || current.locked || current.turn !== "player") {
          return current;
        }

        let nextMarker = current.marker + current.direction * 2.35;
        let nextDirection = current.direction;

        if (nextMarker >= 100) {
          nextMarker = 100;
          nextDirection = -1;
        } else if (nextMarker <= 0) {
          nextMarker = 0;
          nextDirection = 1;
        }

        return {
          ...current,
          marker: nextMarker,
          direction: nextDirection as 1 | -1,
        };
      });
    }, 36);

    return () => window.clearInterval(timer);
  }, [fightOpen]);

  useEffect(() => {
    if (!fightOpen || !fightState.banner || fightState.winner) {
      return;
    }

    const timer = window.setTimeout(() => {
      setFightState((current) => ({
        ...current,
        banner: current.winner ? current.banner : null,
      }));
    }, 900);

    return () => window.clearTimeout(timer);
  }, [fightOpen, fightState.banner, fightState.winner]);

  useEffect(() => {
    if (!fightOpen) {
      return;
    }
    if (fightState.turn !== "enemy" || fightState.locked || fightState.winner) {
      return;
    }

    const enemyDelay = window.setTimeout(() => {
      const enemyRoll = Math.random();
      const damage = enemyRoll > 0.72 ? 24 : enemyRoll > 0.28 ? 15 : 9;
      const strongHit = damage >= 24;

      setFightState((current) => {
        if (current.turn !== "enemy" || current.locked || current.winner) {
          return current;
        }

        const playerRoster = current.playerTeam.roster;
        const enemyRoster = current.enemyTeam.roster;
        const attackerId = enemyRoster[current.enemyTeam.index];
        const defenderId = playerRoster[current.playerTeam.index];
        const enemyScene = roomConfigs[getOpponentRoomKey(activeScene.key)];
        const attackerName = enemyScene.characters[attackerId].name;
        const defenderName = activeScene.characters[defenderId].name;
        const nextHealth = clamp(current.playerTeam.health - damage, 0, fighterMaxHealth(defenderId));
        const defeated = nextHealth <= 0;
        const nextPlayerIndex = defeated ? current.playerTeam.index + 1 : current.playerTeam.index;
        const playerOut = nextPlayerIndex >= playerRoster.length;

        const nextState: FightState = {
          ...current,
          locked: true,
          winner: playerOut ? "enemy" : null,
          message: playerOut
            ? `${attackerName} knocks out ${defenderName}. The undead win.`
            : strongHit
              ? `${attackerName} lands a brutal counter on ${defenderName}.`
              : `${attackerName} answers back with a scrappy hit.`,
          banner: playerOut ? "KO" : defeated ? "Next Fighter" : null,
          playerTeam: {
            ...current.playerTeam,
            index: current.playerTeam.index,
            health: nextHealth,
            pose: defeated ? "dying" : "hurt",
          },
          enemyTeam: {
            ...current.enemyTeam,
            pose: "attack",
          },
        };

        window.setTimeout(() => {
          setFightState((latest) => {
            if (latest.winner) {
              return latest;
            }
            const replacedPlayerIndex = defeated ? latest.playerTeam.index + 1 : latest.playerTeam.index;
            const latestDefenderId = latest.playerTeam.roster[replacedPlayerIndex];
            return {
              ...latest,
              locked: false,
              turn: "player",
              playerTeam: {
                ...latest.playerTeam,
                index: replacedPlayerIndex,
                health: defeated ? fighterMaxHealth(latestDefenderId) : latest.playerTeam.health,
                pose: "idle",
              },
              enemyTeam: {
                ...latest.enemyTeam,
                pose: "idle",
              },
              banner: defeated ? "Next Fighter" : null,
              message: defeated
                ? `${activeScene.characters[latestDefenderId].name} jumps in. Time your strike.`
                : `${activeScene.characters[latestDefenderId].name} steps up. Time your strike.`,
            };
          });
        }, defeated ? 1150 : 650);

        return nextState;
      });
    }, 850);

    return () => window.clearTimeout(enemyDelay);
  }, [activeScene, fightOpen, fightState.locked, fightState.turn, fightState.winner]);

  const totalValues = currentData.events.map((row) => Number(row.total_value));
  const equityValues = currentData.events.map((row) => Number(row.trading_equity));
  const totalValuePath = buildLinePath(totalValues, 620, 150);
  const equityPath = buildLinePath(equityValues, 620, 150);
  const bestWin = currentData.wins.length
    ? currentData.wins.reduce((best, row) => {
        const pnl = Number(row.portfolio_pnl_account);
        return pnl > best ? pnl : best;
      }, Number.NEGATIVE_INFINITY)
    : 0;
  const worstLoss = currentData.losses.length
    ? currentData.losses.reduce((worst, row) => {
        const pnl = Number(row.portfolio_pnl_account);
        return pnl < worst ? pnl : worst;
      }, Number.POSITIVE_INFINITY)
    : 0;

  const trackedPairs = useMemo(
    () => Array.from(new Set(currentData.trades.map((row) => row.symbol))),
    [currentData.trades],
  );
  const session = sessionTheme(nowUtc ?? new Date(Date.UTC(2000, 0, 1, 12, 0, 0)));
  const latestWithdrawal = currentData.withdrawals.at(-1);
  const latestTrades = currentData.trades.slice(-6).reverse();
  const liveAccount = currentData.liveStatus?.account;
  const liveBalance = Number(liveAccount?.balance ?? currentData.summary.FinalTradingEquityUSD);
  const liveMargin = Number(
    liveAccount?.margin ??
      Math.max(currentData.summary.EndingTotalValueUSD - currentData.summary.FinalTradingEquityUSD, 0),
  );
  const livePnl = Number(liveAccount?.open_pnl ?? currentData.summary.NetPnLUSD);

  const activeTraderConfigs = activeScene.traders.map((symbol) => ({
    symbol,
    mood: resolveCharacterMood(currentData, symbol),
    character: activeScene.characters[symbol],
  }));
  const activeDialogueLines = traderDialogue
    ? buildTraderUpdate(currentData, traderDialogue.symbol, nowUtc ?? new Date())
    : [];
  const activeDialogueName = traderDialogue
    ? roomConfigs[traderDialogue.room].characters[traderDialogue.symbol]?.name ??
      roomConfigs[traderDialogue.room].promptName
    : "";
  const activeDialogueSprite = traderDialogue
    ? traderDialogue.stage === "prompt"
      ? roomConfigs[traderDialogue.room].promptSprite
      : roomConfigs[traderDialogue.room].characters[traderDialogue.symbol]?.idle ?? ""
    : "";
  const activeRoomPairs = activeScene.traders.map((symbol) => {
    const livePair = currentData.liveStatus?.pairs?.find((pair) => pair.symbol === symbol);
    const roomData = currentData.rooms.find((room) => room.symbol === symbol);
    return {
      symbol,
      livePair,
      roomData,
      status: previewPairStatus(livePair),
      detail: previewPairDetail(livePair, roomData?.winRatePct ?? 0),
    };
  });
  const activeRoomTradeCount = activeRoomPairs.reduce(
    (sum, item) => sum + (item.roomData?.wins ?? 0) + (item.roomData?.losses ?? 0),
    0,
  );
  const activeRoomOpenCount = activeRoomPairs.filter((item) => item.livePair?.has_open_position).length;

  const topMetrics = [
    { label: "Time", value: nowUtc ? `UTC ${nowUtc.toISOString().slice(11, 19)}` : "UTC --:--:--" },
    { label: "Balance", value: formatMoney(liveBalance) },
    { label: "Margin", value: formatMoney(liveMargin) },
    { label: "P&L", value: formatMoney(livePnl) },
  ];

  function switchRoom() {
    setTraderDialogue(null);
    setFightOpen(false);
    setActiveRoom((current) => (current === "skeleton" ? "zombie" : "skeleton"));
  }

  function openFight() {
    setTraderDialogue(null);
    setFightState(createFightState(activeScene));
    setFightOpen(true);
  }

  function closeFight() {
    setFightOpen(false);
  }

  function resetFight() {
    setFightState(createFightState(activeScene));
  }

  function strike() {
    setFightState((current) => {
      if (current.winner || current.locked || current.turn !== "player") {
        return current;
      }

      const playerRoster = current.playerTeam.roster;
      const enemyRoster = current.enemyTeam.roster;
      const attackerId = playerRoster[current.playerTeam.index];
      const defenderId = enemyRoster[current.enemyTeam.index];
      const attackerName = activeScene.characters[attackerId].name;
      const enemyScene = roomConfigs[getOpponentRoomKey(activeScene.key)];
      const defenderName = enemyScene.characters[defenderId].name;
      const hitStrong = current.marker >= FIGHT_GREEN_MIN && current.marker <= FIGHT_GREEN_MAX;
      const damage = hitStrong ? 26 : 11;
      const nextHealth = clamp(current.enemyTeam.health - damage, 0, fighterMaxHealth(defenderId));
      const defeated = nextHealth <= 0;
      const nextEnemyIndex = defeated ? current.enemyTeam.index + 1 : current.enemyTeam.index;
      const enemyOut = nextEnemyIndex >= enemyRoster.length;

      const nextState: FightState = {
        ...current,
        locked: true,
        turn: enemyOut ? "player" : "enemy",
        winner: enemyOut ? "player" : null,
        message: enemyOut
          ? `${attackerName} crushes ${defenderName}. Your team wins the brawl.`
          : hitStrong
            ? `${attackerName} hits ${defenderName} with a strong strike.`
            : `${attackerName} clips ${defenderName} with a weak hit.`,
        banner: enemyOut ? "KO" : defeated ? "Next Fighter" : null,
        playerTeam: {
          ...current.playerTeam,
          pose: "attack",
        },
        enemyTeam: {
          ...current.enemyTeam,
          index: current.enemyTeam.index,
          health: nextHealth,
          pose: defeated ? "dying" : "hurt",
        },
      };

      window.setTimeout(() => {
        setFightState((latest) => {
          if (latest.winner) {
            return latest;
          }
          const replacedEnemyIndex = defeated ? latest.enemyTeam.index + 1 : latest.enemyTeam.index;
          const nextEnemyId = latest.enemyTeam.roster[replacedEnemyIndex];
          return {
            ...latest,
            locked: false,
            playerTeam: {
              ...latest.playerTeam,
              pose: "idle",
            },
            enemyTeam: {
              ...latest.enemyTeam,
              index: replacedEnemyIndex,
              health: defeated ? fighterMaxHealth(nextEnemyId) : latest.enemyTeam.health,
              pose: "idle",
            },
            banner: defeated ? "Next Fighter" : null,
            message: defeated
              ? `${enemyScene.characters[nextEnemyId].name} rushes in to keep fighting.`
              : `${enemyScene.characters[nextEnemyId].name} is preparing a counterattack.`,
          };
        });
      }, defeated ? 1150 : 620);

      return nextState;
    });
  }

  const enemyScene = roomConfigs[getOpponentRoomKey(activeScene.key)];
  const fightLeftId = fightState.playerTeam.roster[fightState.playerTeam.index];
  const fightRightId = fightState.enemyTeam.roster[fightState.enemyTeam.index];
  const fightLeftCharacter = activeScene.characters[fightLeftId];
  const fightRightCharacter = enemyScene.characters[fightRightId];
  const fightIndicatorLeft = clamp(fightState.playerTeam.health, 0, FIGHT_MAX_HEALTH);
  const fightIndicatorRight = clamp(fightState.enemyTeam.health, 0, FIGHT_MAX_HEALTH);

  return (
    <main className={`shell ${session.className}`}>
      <section className="scene-shell">
        <div className={`scene-stage room-${activeScene.key}`}>
          <img src={activeScene.backgroundSrc} alt={`${activeScene.title} background`} className="scene-background" />

          <div className="scene-room-badge">{activeScene.title}</div>

          <div className="top-board">
            <div className="top-board-grid">
              {topMetrics.map((item) => (
                <div key={item.label} className="top-board-item">
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          </div>

          {activeTraderConfigs.map((trader, index) => (
            <button
              key={`${activeScene.key}-${trader.symbol}`}
              type="button"
              className={`character-slot ${index === 0 ? "left" : "right"}`}
              onClick={() =>
                setTraderDialogue({ room: activeScene.key, symbol: trader.symbol, stage: "prompt" })
              }
              aria-label={`Talk to ${trader.character.name}`}
            >
              <div className={`speech-pop mood-${trader.mood}`}>
                <span>{traderSpeech(currentData, trader.symbol, trader.mood)}</span>
              </div>
                <img
                  src={trader.character[trader.mood]}
                  alt={`${trader.symbol} trader`}
                  className={`character-sprite ${index === 0 ? "eur" : "gbp"} mood-${trader.mood}`}
                />
            </button>
          ))}

          <button
            type="button"
            className="terminal-button"
            onClick={() => setDashboardOpen(true)}
            aria-label="Open dashboard"
          >
            <img src={activeScene.dashboardSrc} alt="Dashboard terminal" className="terminal-image" />
            <div className="terminal-board">
              <div className="terminal-board-grid">
                <div>
                  <span>Trades</span>
                  <strong>{activeRoomTradeCount}</strong>
                </div>
                <div>
                  <span>Open</span>
                  <strong>{activeRoomOpenCount}</strong>
                </div>
              </div>

              <div className="terminal-board-list">
                {activeRoomPairs.map((pair) => (
                  <div key={pair.symbol} className="terminal-board-row">
                    <span className="terminal-board-pair">
                      {renderPairBadge(pair.symbol, "tiny")}
                      {pair.symbol}
                    </span>
                    <span className={`terminal-board-state ${pair.status.className}`}>{pair.status.label}</span>
                    <small>{pair.detail}</small>
                  </div>
                ))}
              </div>

              <div className="terminal-board-footer">
                <strong>Tap to open full stats</strong>
              </div>
            </div>
          </button>

          <div className="scene-action-bar">
            <button type="button" className="scene-fight-button" onClick={openFight}>
              Fight
            </button>
            <button type="button" className="scene-nav-button" onClick={switchRoom}>
              {activeScene.navigateLabel}
            </button>
          </div>

          <div className="scene-helper">{activeScene.helperLabel}</div>
        </div>

        {dashboardOpen ? (
          <div className="dashboard-overlay" onClick={() => setDashboardOpen(false)}>
            <div className="dashboard-panel" onClick={(event) => event.stopPropagation()}>
              <div className="panel-top">
                <div>
                  <p className="eyebrow">Guild Dashboard</p>
                  <h2>House Stats</h2>
                </div>
                <button type="button" className="close-button" onClick={() => setDashboardOpen(false)}>
                  Close
                </button>
              </div>

              <div className="pair-strip">
                {trackedPairs.map((pair) => (
                  <div key={pair} className="pair-chip">
                    {renderPairBadge(pair, "small")}
                    <span>{pair}</span>
                  </div>
                ))}
              </div>

              <div className="metrics-grid">
                <article className="metric-card accent">
                  <span>Total Value</span>
                  <strong>{formatMoney(currentData.summary.EndingTotalValueUSD)}</strong>
                  <small>{formatPct(currentData.summary.ReturnPctOnInitial)}</small>
                </article>
                <article className="metric-card">
                  <span>Net PnL</span>
                  <strong>{formatMoney(currentData.summary.NetPnLUSD)}</strong>
                  <small>{currentData.summary.AcceptedTrades} accepted trades</small>
                </article>
                <article className="metric-card">
                  <span>Withdrawn</span>
                  <strong>{formatMoney(currentData.summary.TotalWithdrawnUSD)}</strong>
                  <small>{latestWithdrawal ? latestWithdrawal.withdrawal_kind : "No withdrawals"}</small>
                </article>
                <article className="metric-card">
                  <span>Drawdown</span>
                  <strong>{formatPct(currentData.summary.MaxDrawdownTotalValuePct)}</strong>
                  <small>Profit factor {currentData.summary.ProfitFactor.toFixed(2)}</small>
                </article>
              </div>

              <div className="board-chart">
                <div className="panel-head">
                  <div>
                    <p className="eyebrow">Portfolio Path</p>
                    <h3>Equity vs Total Value</h3>
                  </div>
                  <div className="legend">
                    <span><i className="dot blue" /> Equity</span>
                    <span><i className="dot green" /> Total</span>
                  </div>
                </div>
                <svg viewBox="0 0 620 150" className="chart">
                  <path d={equityPath} fill="none" stroke="#73f0ff" strokeWidth="4" strokeLinecap="square" />
                  <path d={totalValuePath} fill="none" stroke="#70f59a" strokeWidth="4" strokeLinecap="square" />
                </svg>
              </div>

              <div className="board-split">
                <div className="panel mini-panel">
                  <div className="panel-head">
                    <div>
                      <p className="eyebrow">Execution</p>
                      <h3>Snapshot</h3>
                    </div>
                  </div>
                  <div className="stats-list compact">
                    <div><span>Win Rate</span><strong>{formatPct(currentData.summary.WinRatePct)}</strong></div>
                    <div><span>Best Win</span><strong>{formatMoney(bestWin)}</strong></div>
                    <div><span>Worst Loss</span><strong>{formatMoney(worstLoss)}</strong></div>
                    <div><span>Funding</span><strong>{formatMoney(currentData.summary.TotalOvernightFundingUSD)}</strong></div>
                  </div>
                </div>

                <div className="panel mini-panel">
                  <div className="panel-head">
                    <div>
                      <p className="eyebrow">Latest Trades</p>
                      <h3>Recent</h3>
                    </div>
                  </div>
                  <div className="trade-list">
                    {latestTrades.map((row) => {
                      const pnl = Number(row.portfolio_pnl_account);
                      return (
                        <div key={`${row.symbol}-${row.fill_time_utc}`} className="trade-item">
                          <span className="trade-pair">
                            {renderPairBadge(row.symbol, "tiny")}
                            {row.symbol}
                          </span>
                          <span>{row.exit_reason}</span>
                          <strong className={pnl >= 0 ? "good" : "bad"}>{formatMoney(pnl)}</strong>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {traderDialogue ? (
          <div
            className="dialogue-overlay"
            onClick={() =>
              setTraderDialogue((current) => {
                if (!current) {
                  return null;
                }
                if (current.stage === "prompt") {
                  return { ...current, stage: "report" };
                }
                return null;
              })
            }
          >
            <div
              className={`dialogue-scene ${traderDialogue.stage === "prompt" ? "dialogue-scene-prompt" : ""}`}
              onClick={(event) => {
                event.stopPropagation();
                if (traderDialogue.stage === "prompt") {
                  setTraderDialogue((current) => (current ? { ...current, stage: "report" } : null));
                }
              }}
            >
              <button
                type="button"
                className="dialogue-close"
                onClick={(event) => {
                  event.stopPropagation();
                  setTraderDialogue(null);
                }}
                aria-label="Close trader update"
              >
                x
              </button>
              <img src={activeDialogueSprite} alt={`${activeDialogueName} close-up`} className="dialogue-hero" />

              {traderDialogue.stage === "prompt" ? (
                <div className="dialogue-bubble boss-bubble">
                  <p>{activeDialogueName}, what are updates for today?</p>
                  <span>Tap anywhere</span>
                </div>
              ) : (
                <div className="dialogue-bubble trader-bubble">
                  {activeDialogueLines.map((line) => (
                    <p key={line}>{line}</p>
                  ))}
                  <span>Tap outside to close</span>
                </div>
              )}
            </div>
          </div>
        ) : null}

        {fightOpen ? (
          <div className="fight-overlay" onClick={closeFight}>
            <div className="fight-panel" onClick={(event) => event.stopPropagation()}>
              <button type="button" className="dialogue-close" onClick={closeFight} aria-label="Close fight">
                x
              </button>
              <img src="/battleground.png" alt="Battleground" className="fight-background" />

              <div className="fight-head">
                <p className="eyebrow">Leisure Mode</p>
                <h2>Trader Fight</h2>
              </div>

              <div className="fight-scoreline">
                <div className="fight-team-tag">
                  <strong>{activeScene.title}</strong>
                  <span>{fightState.playerTeam.index + 1}/3 fighter</span>
                </div>
                <div className="fight-team-tag">
                  <strong>{enemyScene.title}</strong>
                  <span>{fightState.enemyTeam.index + 1}/3 fighter</span>
                </div>
              </div>

              <div className="fight-stage">
                {fightState.banner ? <div className="fight-banner">{fightState.banner}</div> : null}
                <div
                  className={`fight-fighter left${fightState.turn === "player" ? " active" : ""} pose-${fightState.playerTeam.pose}`}
                >
                  <div className="fight-health">
                    <span>{fightLeftCharacter.name}</span>
                    <div className="fight-health-bar">
                      <i style={{ width: `${fightIndicatorLeft}%` }} />
                    </div>
                  </div>
                  <img
                    src={fighterSprite(fightLeftCharacter, fightState.playerTeam.pose)}
                    alt={fightLeftCharacter.name}
                    className="fight-sprite left"
                  />
                </div>

                <div
                  className={`fight-fighter right${fightState.turn === "enemy" ? " active" : ""} pose-${fightState.enemyTeam.pose}`}
                >
                  <div className="fight-health">
                    <span>{fightRightCharacter.name}</span>
                    <div className="fight-health-bar">
                      <i style={{ width: `${fightIndicatorRight}%` }} />
                    </div>
                  </div>
                  <img
                    src={fighterSprite(fightRightCharacter, fightState.enemyTeam.pose)}
                    alt={fightRightCharacter.name}
                    className="fight-sprite right"
                  />
                </div>
              </div>

              <div className="fight-controls">
                <div className="fight-message">{fightState.message}</div>
                <div className="timing-track" aria-hidden="true">
                  <div className="timing-green-zone" />
                  <div className="timing-marker" style={{ left: `${fightState.marker}%` }} />
                </div>
                <div className="fight-buttons">
                  <button
                    type="button"
                    className="fight-strike-button"
                    onClick={strike}
                    disabled={fightState.locked || Boolean(fightState.winner) || fightState.turn !== "player"}
                  >
                    Strike
                  </button>
                  <button type="button" className="fight-reset-button" onClick={resetFight}>
                    Reset
                  </button>
                </div>
                {fightState.winner ? (
                  <div className="fight-winner">
                    Winner: {fightState.winner === "player" ? activeScene.title : enemyScene.title}
                  </div>
                ) : (
                  <div className="fight-tip">Hit inside the green zone for a strong attack.</div>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}
