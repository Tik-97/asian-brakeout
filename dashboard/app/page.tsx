import { loadTradingHouseData } from "./lib/dashboard-data";
import { Dashboard } from "./ui/dashboard";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function Page() {
  const data = await loadTradingHouseData();
  return <Dashboard data={data} />;
}
