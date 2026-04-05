import { NextResponse } from "next/server";

import { loadTradingHouseData } from "../../lib/dashboard-data";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const data = await loadTradingHouseData();
  return NextResponse.json(data, {
    headers: {
      "Cache-Control": "no-store, max-age=0",
    },
  });
}
