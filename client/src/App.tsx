import { SettingsBar } from "./components/SettingsBar";
import { BatchPanel } from "./components/BatchPanel";
import { WidgetList } from "./components/WidgetList";
import { AddWidgetMenu } from "./components/AddWidgetMenu";
import { SaveLoadButtons } from "./components/SaveLoadButtons";
import { LabelPreview } from "./components/LabelPreview";
import { PrintButton } from "./components/PrintButton";
import { Footer } from "./components/Footer";
import { useLabelStore } from "./state/useLabelStore";
import { fetchPrinters } from "./lib/api";
import { useEffect } from "react";

export default function App() {
  const setAvailablePrinters = useLabelStore((s) => s.setAvailablePrinters);

  // Fetch available printers on app load
  useEffect(() => {
    const loadPrinters = async () => {
      try {
        const printers = await fetchPrinters();
        setAvailablePrinters(printers);
      } catch (error) {
        console.error("Failed to load printers:", error);
        // Silently fail - UI will work without printer list
      }
    };
    loadPrinters();
  }, [setAvailablePrinters]);

  return (
    <div className="min-h-screen bg-gray-100 p-4">
      <h1 className="text-2xl font-bold text-center mb-4">Labelle Web</h1>
      <div className="flex flex-col lg:flex-row gap-4 mt-4">
        <div className="flex-1 min-w-0 lg:order-2">
          <LabelPreview />
        </div>
        <div className="w-full lg:w-96 lg:flex-shrink-0 space-y-4 lg:order-1">
          <WidgetList />
          <AddWidgetMenu />
          <PrintButton />
          <div className="pt-4">
            <SaveLoadButtons />
          </div>
          <BatchPanel />
          <SettingsBar />
        </div>
      </div>
      <Footer />
    </div>
  );
}
